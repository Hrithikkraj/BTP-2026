# EXIF Metadata Extractor & Device Identifier

A small Phase-1 tool for the wide-angle lens correction project. Point it at
the photos you've taken on different phones, and it will:

- Print every useful piece of EXIF metadata for each image (camera settings,
  lens, date, GPS, etc.)
- Tell you **which phone took each photo** (Make + Model from EXIF)
- Flag RAW/DNG files that already contain embedded lens-correction opcodes
  (`OpcodeList1/2/3`, `WarpRectilinear`) — this is exactly the "is the
  source already pre-corrected by the ISP?" check from the project's
  RAW-vs-JPEG gate test
- Save a `exif_report.csv` summary (one row per photo — a head start on
  `capture_log_template.csv`) and a `exif_report_full.json` with everything
  it found, for later scripting

## 1. Setup

Install **ExifTool** first — it reads far more (HEIC, DNG maker notes,
lens-correction opcodes) than any pure-Python library:

```bash
# Ubuntu / Debian
sudo apt install libimage-exiftool-perl

# macOS
brew install exiftool

# Windows
# Download the .exe from https://exiftool.org and add it to PATH
```

Then install the Python fallback libraries (used automatically if ExifTool
isn't found, and harmless to have installed either way):

```bash
pip install -r requirements.txt
```

## 2. Usage

```bash
# A single photo
python tools/extract_metadata.py IMG_0001.jpg

# Several specific photos
python tools/extract_metadata.py phone1/IMG_0001.jpg phone2/20260820_091244.jpg

# A whole folder of photos (non-recursive)
python tools/extract_metadata.py data/session_2026-11-05_printed_grid/

# Just the summary table, skip the full per-photo printout
python tools/extract_metadata.py data/session_2026-11-05_printed_grid/ --quiet

# Every photo under data/, including sub-folders
python tools/extract_metadata.py data -r --quiet --out-dir reports

# Choose where the CSV/JSON reports get written
python tools/extract_metadata.py data/session_2026-11-05_printed_grid/ --out-dir ./reports
```

Supported formats: JPG, PNG, TIFF, HEIC/HEIF, and common RAW types
(DNG, ARW, CR2, CR3, NEF, RW2, ORF).

## 3. What you get

For each image, a printed block like:

```
==================================================================
FILE: IMG_0001.jpg
==================================================================
  Image Dimensions          : 4032 x 3024
  Camera Make               : Apple
  Camera Model              : iPhone 13 Pro
  Lens Model                : iPhone 13 Pro back triple camera 5.7mm f/1.5
  Date Taken                : 2026:08:20 14:32:10
  Focal Length              : 5.7 mm
  Aperture                  : 1.5
  Shutter Speed             : 1/120
  ISO                       : 100
  GPS Location              : 28.613900° N, 77.209000° E

  📱 Captured on: Apple iPhone 13 Pro
  (read via: exiftool)
```

...followed by a summary table across all images, and two saved files:

- `exif_report.csv` — one row per photo (filename, make, model, lens,
  date, focal length, aperture, shutter speed, ISO, size, GPS)
- `exif_report_full.json` — the complete raw metadata per photo, plus any
  RAW opcode warnings, in case you need fields the CSV doesn't cover

If a photo has **no** Make/Model (common after it's been through WhatsApp,
Instagram, or a screenshot tool — these strip EXIF), the tool says so
explicitly rather than guessing.

## 4. Where this fits in the project

This covers the EXIF/device-fingerprinting half of `characterize.py`
(Phase 1 in the repo layout from the project context: "RAW-vs-JPEG, EXIF,
is it pre-corrected?"). It directly answers two of the project's open
questions:

- **Does EXIF report focus distance?** — check the "Focus / Subject
  Distance" line in the per-image printout (populated only if the phone
  reports it; most phones don't).
- **Is the RAW source pre-corrected?** — for `.dng`/RAW files, check the
  opcode warning. If opcodes are present, that file has already been
  geometrically corrected by the phone's ISP profile and isn't a clean
  "distorted" source for calibration.

You can drop `extract_metadata.py`'s logic straight into
`lens-correction/calibration/characterize.py` once you're ready to wire it
into the rest of the pipeline — the functions are written to be imported,
not just run from the command line (`from extract_metadata import
get_metadata, identify_device, check_raw_opcodes`).

## 5. Known limitations

- Without ExifTool, HEIC files (the default iPhone photo format) will
  return almost no data — Pillow/exifread can't parse HEIC's container
  format. Installing ExifTool fixes this.
- Maker-specific tags (e.g. some Samsung/Xiaomi computational-photography
  flags) are only decoded by ExifTool, not the fallback.
- Model-code-to-marketing-name mapping (e.g. `SM-G991B` → "Galaxy S21") is
  intentionally **not** done — those lookup tables go stale and can be
  wrong, so the tool reports the raw Make/Model exactly as the phone wrote
  it.
