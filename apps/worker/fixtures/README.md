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

## Takeout archive (`takeout.zip`)

Also written by `generate.py`, from the fixtures above, for the importer tests:

| Entry | What it exercises |
|---|---|
| `Sommerfest 2024/IMG_7421.jpg` + `IMG_7421.jpg.json` | sidecar with `photoTakenTime`, `geoData` and two `people` names |
| `Sommerfest 2024/IMG_7422.jpg` + `….supplemental-metadata.json` | the newer sidecar suffix, one name, `geoData` 0/0 (ignored) |
| `Sommerfest 2024/IMG_7424_sehr_langer_dateiname_vom_telefon.jpg` + `….j.json` | Google's truncated sidecar name (matched by prefix) |
| `Sommerfest 2024/IMG_7425.jpg` | no sidecar; byte-identical to fixture 05, so a duplicate when that is already imported |
| `Sommerfest 2024/VID_20240614_223000.mp4` + sidecar | a video with a sidecar time |
| `Winter 2023/IMG_20231224_180000.jpg` + sidecar | outside the fixture event's window: stays in the library |
| `*/metadata.json` | album metadata, must be ignored |

## Portraits (`faces/`)

Ten public-domain NASA portraits from Wikimedia Commons (US federal government works), fetched
and re-encoded at 800 px by `uv run python fixtures/fetch_faces.py`; `SOURCES.json` lists title,
page, author and license per file, `labels.json` holds the hand labels for
`yearbook-worker eval-cluster`. Four identities with two single portraits each (Whitson,
Williams, Jemison, Kelly) plus two group photos (Williams with Wilmore; the STS-47 crew with
Jemison). The `ml` tests expect faces on every file, four persons with two or more faces, and
purity ≥ 0.99 on the eight singles.
