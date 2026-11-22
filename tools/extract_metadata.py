"""
EXIF Metadata Extractor & Device Identifier
============================================
Phase-1 utility for the wide-angle lens correction project.

Given one image, several images, or a whole folder of phone photos, this
script:

  1. Prints ALL metadata returned by ExifTool for each image, plus a useful summary.
  2. Identifies which phone (make + model) took each photo.
  3. For RAW/DNG files, flags whether the file already carries embedded
     lens-correction opcodes (OpcodeList1/2/3, WarpRectilinear) -- this is
     exactly the "is the source pre-corrected?" question from the project's
     RAW-vs-JPEG gate test.
  4. Saves a per-image JSON dump and a CSV summary table (compatible with
     the project's capture_log_template.csv) so the results can be reused
     for calibration / evaluation later.

Usage
-----
    python extract_metadata.py PATH [PATH ...] [-r] [--out-dir DIR] [--quiet]

    PATH        one or more image files, and/or folders (folders are
                scanned for supported image types; add -r to recurse)
    --out-dir   where to write exif_report.csv / exif_report_full.json
                (default: alongside the first input path)
    --quiet     skip the full per-image printout, show only the summary
                table (the CSV/JSON are always written either way)

Backends
--------
Uses ExifTool (https://exiftool.org) when it is available on PATH, since
it gives the most complete and accurate results across JPEG, HEIC, and
RAW/DNG formats, and can decode maker-specific notes.

If ExifTool is NOT installed, the script automatically falls back to
Pillow + exifread. That fallback works fine for ordinary JPEG/TIFF
photos, but will not decode HEIC files or maker notes -- so, e.g. Apple's
lens ID string may be missing and iPhone HEIC files may show almost no
data. Install ExifTool for best results:

    Ubuntu/Debian : sudo apt install libimage-exiftool-perl
    macOS         : brew install exiftool
    Windows       : https://exiftool.org (download the .exe)
"""

import argparse
import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

SUPPORTED_EXTS = {
    ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".heif",
    ".dng", ".raw", ".arw", ".cr2", ".cr3", ".nef", ".rw2", ".orf",
}
RAW_EXTS = {".dng", ".raw", ".arw", ".cr2", ".cr3", ".nef", ".rw2", ".orf"}

# (display label, list of possible source keys, in priority order)
DISPLAY_FIELDS = [
    ("Camera Make",              ["Make"]),
    ("Camera Model",             ["Model"]),
    ("Lens Model",               ["LensModel", "LensID", "LensInfo", "Lens"]),
    ("Software / OS Version",    ["Software"]),
    ("Date Taken",               ["DateTimeOriginal", "CreateDate", "DateTime"]),
    ("Focal Length",             ["FocalLength"]),
    ("35mm Equivalent",          ["FocalLengthIn35mmFormat", "FocalLengthIn35mmFilm"]),
    ("Aperture",                 ["FNumber", "Aperture"]),
    ("Shutter Speed",            ["ExposureTime", "ShutterSpeed"]),
    ("ISO",                      ["ISO", "ISOSpeedRatings"]),
    ("White Balance",            ["WhiteBalance"]),
    ("Flash",                    ["Flash"]),
    ("Exposure Program",         ["ExposureProgram"]),
    ("Metering Mode",            ["MeteringMode"]),
    ("Focus / Subject Distance", ["SubjectDistance", "FocusDistance", "ObjectDistance"]),
    ("Orientation",              ["Orientation"]),
    ("Color Space",              ["ColorSpace"]),
]

LOWERCASE_MAKES = {  # Android makers that report an all-lowercase Make tag
    "samsung", "xiaomi", "oneplus", "google", "motorola",
    "oppo", "vivo", "realme", "asus", "sony", "huawei", "nokia", "lenovo",
}


# --------------------------------------------------------------------------
# Backend 1: ExifTool (preferred)
# --------------------------------------------------------------------------

def has_exiftool() -> bool:
    return shutil.which("exiftool") is not None


def exiftool_location():
    """Return the ExifTool executable found on PATH, if any."""
    return shutil.which("exiftool")


def read_with_exiftool(path: Path):
    try:
        result = subprocess.run(
            ["exiftool", "-j", "-G1", "-a", "-s", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        return data[0] if data else {}
    except Exception as exc:
        return {"_error": f"ExifTool failed: {exc}"}


def check_raw_opcodes(path: Path):
    """Look for embedded DNG lens-correction opcodes. Only meaningful for
    RAW/DNG files, and only when ExifTool is available."""
    if path.suffix.lower() not in RAW_EXTS or not has_exiftool():
        return None
    try:
        result = subprocess.run(
            ["exiftool", "-j", "-G1", "-a",
             "-DNGVersion", "-OpcodeList1", "-OpcodeList2", "-OpcodeList3",
             "-WarpRectilinear", "-WarpFisheye", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        tags = data[0] if data else {}
        found = {k: v for k, v in tags.items()
                 if any(term in k for term in ("Opcode", "Warp"))}
        return found or None
    except Exception:
        return None


# --------------------------------------------------------------------------
# Backend 2: Pillow + exifread fallback (used only if ExifTool is missing)
# --------------------------------------------------------------------------

def read_with_fallback(path: Path):
    from PIL import Image, ExifTags

    out = {}
    try:
        img = Image.open(path)
        out["ImageWidth"], out["ImageHeight"] = img.size
        out["FileType"] = (img.format or path.suffix.lstrip(".").upper())

        exif = img.getexif()
        for tag_id, val in exif.items():
            out[ExifTags.TAGS.get(tag_id, str(tag_id))] = val

        try:  # Exif SubIFD (0x8769): FNumber, ISO, LensModel, etc.
            for tag_id, val in exif.get_ifd(0x8769).items():
                out[ExifTags.TAGS.get(tag_id, str(tag_id))] = val
        except Exception:
            pass

        try:  # GPS IFD (0x8825)
            gps = exif.get_ifd(0x8825)
            for tag_id, val in gps.items():
                out[ExifTags.GPSTAGS.get(tag_id, str(tag_id))] = val
        except Exception:
            pass

    except Exception as exc:
        out["_error"] = f"Could not open image: {exc}"
        return out

    # Try exifread too, in case it caught something Pillow missed
    # (e.g. some DNG/TIFF tags). Never overwrites values Pillow already found.
    try:
        import exifread
        with open(path, "rb") as f:
            tags = exifread.process_file(f, details=False)
        for k, v in tags.items():
            short = k.split(" ")[-1]
            out.setdefault(short, str(v))
    except Exception:
        pass

    _tidy_fallback_values(out)
    return out


def _tidy_fallback_values(meta: dict):
    """Pillow/exifread return raw numeric EXIF values; reformat the common
    ones to match ExifTool's friendlier human-readable style."""
    et = meta.get("ExposureTime")
    if et is not None:
        try:
            et_f = float(et)
            if 0 < et_f < 1:
                meta["ExposureTime"] = f"1/{round(1 / et_f)}"
        except (TypeError, ValueError):
            pass

    wb = meta.get("WhiteBalance")
    if wb in (0, 1):
        meta["WhiteBalance"] = "Auto" if wb == 0 else "Manual"

    orient_map = {
        1: "Horizontal (normal)", 2: "Mirror horizontal", 3: "Rotate 180",
        4: "Mirror vertical", 6: "Rotate 90 CW", 8: "Rotate 270 CW",
    }
    if meta.get("Orientation") in orient_map:
        meta["Orientation"] = orient_map[meta["Orientation"]]


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

def get_metadata(path: Path):
    """Returns (metadata_dict, backend_name)."""
    if has_exiftool():
        return read_with_exiftool(path), "exiftool"
    return read_with_fallback(path), "pillow+exifread (fallback -- install exiftool for full accuracy)"


def _lookup(meta: dict, key: str):
    """Find a tag by name. ExifTool is run with -G1, so its keys carry a
    group prefix (e.g. "IFD0:Make", "ExifIFD:FNumber"); the fallback backend
    returns bare names. Accept either, preferring an exact match."""
    if key in meta:
        return meta[key]
    suffix = ":" + key
    for k, v in meta.items():
        if k.endswith(suffix):
            return v
    return None


def first_present(meta: dict, keys):
    for k in keys:
        val = _lookup(meta, k)
        if val not in (None, "", "-"):
            return val
    return None


def gps_string(meta: dict):
    pos = first_present(meta, ["GPSPosition"])
    if pos:
        return pos
    lat, lon = first_present(meta, ["GPSLatitude"]), first_present(meta, ["GPSLongitude"])
    if lat is None or lon is None:
        return None
    lat_ref = first_present(meta, ["GPSLatitudeRef"]) or ""
    lon_ref = first_present(meta, ["GPSLongitudeRef"]) or ""

    def to_decimal(v):
        if isinstance(v, (tuple, list)) and len(v) == 3:
            d, m, s = v
            return float(d) + float(m) / 60 + float(s) / 3600
        try:
            return float(v)
        except Exception:
            return None

    lat_d, lon_d = to_decimal(lat), to_decimal(lon)
    if lat_d is None or lon_d is None:
        return f"{lat} {lat_ref}, {lon} {lon_ref}"
    return f"{lat_d:.6f}\u00b0 {lat_ref}, {lon_d:.6f}\u00b0 {lon_ref}"


def image_size_string(meta: dict):
    size = first_present(meta, ["ImageSize"])
    if size:
        return str(size).replace("x", " x ")
    w = first_present(meta, ["ImageWidth", "ExifImageWidth"])
    h = first_present(meta, ["ImageHeight", "ExifImageHeight"])
    if w and h:
        return f"{w} x {h}"
    return None


def identify_device(meta: dict) -> str:
    make = first_present(meta, ["Make"])
    model = first_present(meta, ["Model"])
    if not make and not model:
        return "Unknown (no Make/Model in EXIF -- likely stripped by a " \
               "messaging app, screenshot, or edited image)"
    if make and make.lower() in LOWERCASE_MAKES:
        make = make.capitalize()
    if make and model and str(model).lower().startswith(str(make).lower()):
        return str(model)  # avoid "Apple Apple iPhone 13 Pro"-style repeats
    return " ".join(str(x) for x in (make, model) if x)


def fmt(label, value):
    return f"  {label:<26}: {value}"


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def print_report(path: Path, meta: dict, backend: str, opcode_hits):
    print("=" * 78)
    print(f"FILE: {path.name}")
    print("=" * 78)

    if meta.get("_error"):
        print(f"  Could not read this file: {meta['_error']}")
        print()
        return

    # Human-readable highlights
    size = image_size_string(meta)
    if size:
        print(fmt("Image Dimensions", size))

    for label, keys in DISPLAY_FIELDS:
        val = first_present(meta, keys)
        if val is not None:
            print(fmt(label, val))

    gps = gps_string(meta)
    if gps:
        print(fmt("GPS Location", gps))

    device = identify_device(meta)

    print()
    print(f"  📱 Captured on: {device}")
    print(f"  (read via: {backend})")

    # Full ExifTool metadata
    print()
    print(f"  ALL METADATA ({backend.split(' ')[0]})")
    print("  " + "-" * 74)

    for key, value in meta.items():
        if key.startswith("_"):
            continue

        # ExifTool may return lists/dictionaries for some tags.
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, default=str)

        print(f"  {key:<38}: {value}")

    if opcode_hits:
        print()
        print("  ⚠  RAW/DNG lens-correction opcodes found:")
        for k, v in opcode_hits.items():
            print(f"      {k} = {v}")
        print("     -> This file may already be geometrically corrected")
        print("        by the phone's ISP profile. Re-check before using")
        print("        it as an 'uncorrected' source (see project gate test).")
    elif path.suffix.lower() in RAW_EXTS and has_exiftool():
        print()
        print("  No lens-correction opcodes found -- likely a genuinely")
        print("  uncorrected RAW source.")

    print()


def print_summary_table(rows):
    if not rows:
        return
    headers = ["Filename", "Make", "Model", "Device", "Date Taken"]
    widths = [max(len(h), *(len(str(r[h])) for r in rows)) for h in headers]
    print("SUMMARY")
    print("-" * (sum(widths) + 3 * (len(headers) - 1)))
    print(" | ".join(h.ljust(w) for h, w in zip(headers, widths)))
    print("-+-".join("-" * w for w in widths))
    for r in rows:
        print(" | ".join(str(r[h]).ljust(w) for h, w in zip(headers, widths)))
    print()


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def collect_image_paths(inputs, recursive=False):
    paths = []
    for raw in inputs:
        p = Path(raw)
        if p.is_dir():
            children = p.rglob("*") if recursive else p.iterdir()
            for child in sorted(children):
                if child.is_file() and child.suffix.lower() in SUPPORTED_EXTS:
                    paths.append(child)
        elif p.is_file():
            paths.append(p)
        else:
            print(f"Warning: path not found, skipping: {raw}", file=sys.stderr)
    return paths


def main():
    parser = argparse.ArgumentParser(description="Extract EXIF metadata and identify the source phone for images.")
    parser.add_argument("paths", nargs="+", help="Image file(s) and/or folder(s) of images")
    parser.add_argument("--out-dir", default=None, help="Where to write exif_report.csv / .json (default: next to the first input)")
    parser.add_argument("-r", "--recursive", action="store_true", help="Also scan sub-folders of any folder given")
    parser.add_argument("--quiet", action="store_true", help="Only print the summary table, not the full per-image report")
    args = parser.parse_args()

    images = collect_image_paths(args.paths, args.recursive)
    if not images:
        print("No supported images found.", file=sys.stderr)
        sys.exit(1)

    if not has_exiftool():
        print("Note: ExifTool not found on PATH -- using the Pillow/exifread "
              "fallback. Results will be less complete, especially for HEIC "
              "and RAW files. Install ExifTool for best results (see the "
              "README).\n")

    out_dir = Path(args.out_dir) if args.out_dir else (
        images[0].parent if images[0].is_file() else images[0]
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_rows = []
    json_dump = []
    csv_rows = []

    for path in images:
        meta, backend = get_metadata(path)
        opcode_hits = check_raw_opcodes(path)

        if not args.quiet:
            print_report(path, meta, backend, opcode_hits)

        device = identify_device(meta)
        make = first_present(meta, ["Make"]) or ""
        model = first_present(meta, ["Model"]) or ""
        date_taken = first_present(
            meta, ["DateTimeOriginal", "CreateDate", "DateTime"]
        ) or ""

        summary_rows.append({
            "Filename": path.name,
            "Make": make,
            "Model": model,
            "Device": device,
            "Date Taken": date_taken,
        })

        csv_rows.append({
            "Filename": path.name,
            "Make": make,
            "Model": model,
            "Device": device,
            "DateTaken": date_taken,
            "LensModel": first_present(meta, ["LensModel", "LensID", "LensInfo"]) or "",
            "FocalLength": first_present(meta, ["FocalLength"]) or "",
            "Aperture": first_present(meta, ["FNumber", "Aperture"]) or "",
            "ShutterSpeed": first_present(meta, ["ExposureTime", "ShutterSpeed"]) or "",
            "ISO": first_present(meta, ["ISO", "ISOSpeedRatings"]) or "",
            "ImageSize": image_size_string(meta) or "",
            "GPS": gps_string(meta) or "",
        })
        json_dump.append({
            "file": str(path),
            "backend": backend,
            "device": device,
            "raw_opcode_warning": opcode_hits,
            "metadata": meta,
        })

    print_summary_table(summary_rows)

    csv_path = out_dir / "exif_report.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "Filename", "Make", "Model", "Device", "DateTaken",
            "LensModel", "FocalLength", "Aperture",
            "ShutterSpeed", "ISO", "ImageSize", "GPS",
        ])
        writer.writeheader()
        writer.writerows(csv_rows)

    json_path = out_dir / "exif_report_full.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_dump, f, indent=2, default=str)

    print(f"Saved summary CSV  -> {csv_path}")
    print(f"Saved full JSON    -> {json_path}")


if __name__ == "__main__":
    main()
