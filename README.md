# BTP 2026: Wide-Angle Lens Distortion Correction

B.Tech project on measuring and correcting geometric (barrel) distortion in
smartphone ultra-wide cameras.

## Repository layout

```
.
├── data/                                 raw captures (unedited, straight off the phone)
│   ├── session_2026-10-09_tape_grid/     session 1: hand-taped grid on a wall
│   │   ├── main_26mm/                    main camera, 5.4 mm, f/1.8 (26 mm eq.)
│   │   └── ultrawide_13mm/               ultra-wide, 1.7 mm, f/2.2 (13 mm eq.)
│   ├── session_2026-11-05_printed_grid/  session 2: printed square grid
│   │   ├── main_26mm/
│   │   ├── ultrawide_13mm/
│   │   └── 20261105_234411.mp4           33 s, 1440x1440 @ 30 fps sweep
│   └── misc/                             one-off test shots from other phones
├── docs/
│   └── metadata_tool.md                  full docs for the EXIF tool
├── reports/
│   ├── exif_report.csv                   one row per photo (device, lens, exposure)
│   └── exif_report_full.json             every EXIF tag per photo
├── tools/
│   └── extract_metadata.py               Phase 1: EXIF extraction + device ID
└── requirements.txt
```

## Quick start

```bash
pip install -r requirements.txt
# Install ExifTool too (recommended): https://exiftool.org
python tools/extract_metadata.py data -r --quiet --out-dir reports
```

See [docs/metadata_tool.md](docs/metadata_tool.md) for details.

## Capture sessions

| Session | Target | Device | Main (26 mm) | Ultra-wide (13 mm) | Notes |
|---|---|---|---|---|---|
| 2026-10-09 | Black tape grid on wall | Samsung SM-G990B2 | 6 | 5 | Mix of 4000x3000 and 2992x2992 (1:1 crop). Tape strips are uneven, so not usable as geometric ground truth. |
| 2026-11-05 | Printed 12x12 square grid | Samsung SM-G990B2 | 2 | 3 | All 2992x2992. Plus one 33 s video. |
| misc | n/a | Apple iPhone 11 | n/a | n/a | Single test shot (4032x3024). |

No photo contains GPS data.

## Findings so far

- **The phone's JPEGs look pre-corrected.** The ultra-wide (13 mm eq.) shots of
  the printed grid show almost straight lines, which a 13 mm lens would not
  produce optically. Samsung applies *Ultra wide shape correction* by default,
  so these JPEGs are probably not a clean "distorted" source.
- **1:1 crop discards the corners**, which is where radial distortion is
  strongest. Calibration shots should use the full 4:3 sensor (4000x3000).
- EXIF on this device does **not** report focus/subject distance.

## Roadmap

- [x] Phase 1: EXIF / device identification tool
- [x] First capture sessions (tape grid, printed grid)
- [ ] Re-capture with shape correction **off** and/or in RAW (DNG); run the
      opcode check to confirm the RAW is uncorrected
- [ ] Switch to a checkerboard / ChArUco target on a rigid flat board, full 4:3
- [ ] Calibration: estimate intrinsics + distortion coefficients (OpenCV)
- [ ] Undistortion + evaluation (straight-line error, reprojection error)
