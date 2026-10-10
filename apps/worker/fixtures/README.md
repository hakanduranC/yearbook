# Worker fixtures

Generated deterministically by `uv run python fixtures/generate.py` (Pillow, pillow-heif, ffmpeg;
no downloads). Re-running rewrites every file byte for byte except the MP4 (ffmpeg stamps the
encoder version). All photos are < 300 KB; the clip is ~180 KB.

One evening in Berlin, 2024-06-14, so capture-time grouping and dedupe have something to bite on.

| File | What it exercises |
|---|---|
| `01_IMG_7421.jpg` … `10_IMG_7430.jpg` | JPEGs 800×600 to 1600×1200 with EXIF `DateTimeOriginal` + `OffsetTimeOriginal` (+02:00), 18:05 to 23:20 |
| `03_IMG_7423_portrait.jpg` | EXIF orientation 6: stored 1600×1200, must come out 1200×1600 |
| `06_IMG_7426_gps.jpg` | GPS IFD (52.52 N, 13.405 E) → `media.gps` |
| `08_IMG_7428_nooffset.jpg` | `DateTimeOriginal` without an offset tag → interpreted in the event timezone |
| `11_IMG_7425_copy_q50.jpg` | Same picture as `05` re-encoded at quality 50, taken 40 s later → near duplicate |
| `12_DSC_0042.jpg` | Another camera naming scheme |
| `13_IMG_20240614_211400.jpg` | No EXIF at all; capture time from the filename → `captured_src = filename` |
| `14_logo_alpha.png` | PNG with alpha and no metadata → flattened onto white, `captured_src = upload` |
| `15_IMG_0199.heic` | HEIC written by pillow-heif with EXIF → decode path for iPhone photos |
| `16_IMG_7422_copy.jpg` | Byte-identical copy of `02` → exact duplicate |
| `17_clip.mp4` | 3 s `testsrc2` 640×360 H.264 + AAC, `creation_time` 2024-06-14T20:30:00Z → poster + `video.mp4` |

`private/` is gitignored. Drop real iPhone HEICs (10-bit, HDR) and a `.mov` there; the
integration tests pick up anything in it when present.
