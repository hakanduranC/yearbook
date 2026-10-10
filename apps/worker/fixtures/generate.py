"""Generate the committed fixture set deterministically (no downloads).

Run: `uv run python fixtures/generate.py` from apps/worker. Rewrites every fixture file.
The set covers one evening (2024-06-14, Berlin): 12 JPEGs with EXIF DateTimeOriginal,
two exact duplicates, two near duplicates, a PNG with alpha, a HEIC, a JPEG without EXIF
but with a dated filename, and a 3 s MP4 from ffmpeg's testsrc.
"""

from __future__ import annotations

import random
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pillow_heif
from PIL import Image, ImageDraw
from PIL.TiffImagePlugin import IFDRational

HERE = Path(__file__).resolve().parent
pillow_heif.register_heif_opener()

EXIF_IFD = 0x8769
GPS_IFD = 0x8825
ORIENTATION = 0x0112
DATETIME_ORIGINAL = 0x9003
OFFSET_TIME_ORIGINAL = 0x9011
MAKE, MODEL = 0x010F, 0x0110


@dataclass(frozen=True)
class Photo:
    name: str
    size: tuple[int, int]
    seed: int
    taken: str | None  # EXIF "YYYY:MM:DD HH:MM:SS" or None for no EXIF
    offset: str | None = "+02:00"
    orientation: int = 1
    gps: tuple[float, float] | None = None
    quality: int = 80


# fmt: off
PHOTOS: tuple[Photo, ...] = (
    Photo("01_IMG_7421.jpg",          (1600, 1200), 1,  "2024:06:14 18:05:11"),
    Photo("02_IMG_7422.jpg",          (1600, 1200), 2,  "2024:06:14 18:31:40"),
    Photo("03_IMG_7423_portrait.jpg", (1600, 1200), 3,  "2024:06:14 19:02:05", orientation=6),
    Photo("04_IMG_7424.jpg",          (1200,  900), 4,  "2024:06:14 19:40:59"),
    Photo("05_IMG_7425.jpg",          (1600,  900), 5,  "2024:06:14 20:15:30"),
    Photo("06_IMG_7426_gps.jpg",      (1024,  768), 6,  "2024:06:14 20:48:12",
          gps=(52.5200, 13.4050)),
    Photo("07_IMG_7427.jpg",          ( 800,  600), 7,  "2024:06:14 21:14:00"),
    Photo("08_IMG_7428_nooffset.jpg", (1400, 1050), 8,  "2024:06:14 21:59:33", offset=None),
    Photo("09_IMG_7429.jpg",          (1600, 1200), 9,  "2024:06:14 22:37:08"),
    Photo("10_IMG_7430.jpg",          (1280,  960), 10, "2024:06:14 23:20:45"),
    # exact duplicate of 02 (byte identical copy, see below) and near duplicate of 05:
    Photo("11_IMG_7425_copy_q50.jpg", (1600,  900), 5,  "2024:06:14 20:16:10", quality=50),
    Photo("12_DSC_0042.jpg",          (1600, 1067), 12, "2024:06:14 23:51:02"),
)
# fmt: on

NO_EXIF_DATED = Photo("13_IMG_20240614_211400.jpg", (1024, 768), 13, None)
PNG_ALPHA = Photo("14_logo_alpha.png", (800, 600), 14, None)
HEIC = Photo("15_IMG_0199.heic", (1440, 1080), 15, "2024:06:14 19:25:47")
EXACT_DUP_OF = ("02_IMG_7422.jpg", "16_IMG_7422_copy.jpg")
VIDEO = "17_clip.mp4"


def paint(size: tuple[int, int], seed: int, alpha: bool = False) -> Image.Image:
    """A distinct, compressible picture: gradient sky, ground, and a few shapes."""
    rng = random.Random(seed)
    w, h = size
    im = Image.new("RGBA" if alpha else "RGB", size)
    draw = ImageDraw.Draw(im)
    top = tuple(rng.randint(20, 235) for _ in range(3))
    bottom = tuple(rng.randint(20, 235) for _ in range(3))
    for y in range(h):
        t = y / max(1, h - 1)
        color = tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3))
        draw.line([(0, y), (w, y)], fill=(*color, 255) if alpha else color)
    for _ in range(rng.randint(5, 9)):
        x0, y0 = rng.randint(0, w - 1), rng.randint(0, h - 1)
        x1, y1 = min(w, x0 + rng.randint(w // 8, w // 2)), min(h, y0 + rng.randint(h // 8, h // 2))
        color = tuple(rng.randint(0, 255) for _ in range(3))
        fill = (*color, rng.choice([255, 255, 160])) if alpha else color
        if rng.random() < 0.5:
            draw.rectangle([x0, y0, x1, y1], fill=fill)
        else:
            draw.ellipse([x0, y0, x1, y1], fill=fill)
    if alpha:  # transparent corners so flattening onto white is visible
        hole = Image.new("L", size, 255)
        ImageDraw.Draw(hole).ellipse([-w // 3, -h // 3, w // 3, h // 3], fill=0)
        im.putalpha(Image.composite(im.getchannel("A"), hole, hole))
    return im


def exif_for(photo: Photo) -> bytes:
    exif = Image.Exif()
    exif[MAKE] = "Yearbook"
    exif[MODEL] = "Fixture"
    exif[ORIENTATION] = photo.orientation
    ifd = exif.get_ifd(EXIF_IFD)
    assert photo.taken is not None
    ifd[DATETIME_ORIGINAL] = photo.taken
    if photo.offset:
        ifd[OFFSET_TIME_ORIGINAL] = photo.offset
    if photo.gps:
        lat, lon = photo.gps
        gps = exif.get_ifd(GPS_IFD)
        gps[1] = "N" if lat >= 0 else "S"
        gps[2] = _dms(abs(lat))
        gps[3] = "E" if lon >= 0 else "W"
        gps[4] = _dms(abs(lon))
    return exif.tobytes()


def _dms(value: float) -> tuple[IFDRational, IFDRational, IFDRational]:
    deg = int(value)
    minutes_f = (value - deg) * 60
    minutes = int(minutes_f)
    seconds = round((minutes_f - minutes) * 60 * 1000)
    return (IFDRational(deg, 1), IFDRational(minutes, 1), IFDRational(seconds, 1000))


def write_jpeg(photo: Photo) -> Path:
    im = paint(photo.size, photo.seed)
    # Orientation 6 means the stored pixels are rotated 90° CW relative to the scene:
    # keep the stored image landscape; viewers (and our decode stage) turn it portrait.
    out = HERE / photo.name
    kwargs = {"quality": photo.quality, "optimize": True}
    if photo.taken:
        kwargs["exif"] = exif_for(photo)
    im.save(out, format="JPEG", **kwargs)
    return out


def write_png(photo: Photo) -> Path:
    out = HERE / photo.name
    paint(photo.size, photo.seed, alpha=True).save(out, format="PNG", optimize=True)
    return out


def write_heic(photo: Photo) -> Path:
    out = HERE / photo.name
    paint(photo.size, photo.seed).save(out, format="HEIF", quality=55, exif=exif_for(photo))
    return out


def write_video(name: str) -> Path:
    out = HERE / name
    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=duration=3:size=640x360:rate=25",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "48k", "-shortest",
        "-metadata", "creation_time=2024-06-14T20:30:00.000000Z",
        "-movflags", "+faststart", str(out),
    ]  # fmt: skip
    subprocess.run(cmd, check=True)
    return out


def main() -> None:
    written: list[Path] = []
    for photo in PHOTOS:
        written.append(write_jpeg(photo))
    written.append(write_jpeg(NO_EXIF_DATED))
    written.append(write_png(PNG_ALPHA))
    written.append(write_heic(HEIC))
    src, dup = EXACT_DUP_OF
    shutil.copyfile(HERE / src, HERE / dup)
    written.append(HERE / dup)
    written.append(write_video(VIDEO))
    for path in written:
        size = path.stat().st_size
        limit = 2_000_000 if path.suffix == ".mp4" else 300_000
        assert size <= limit, f"{path.name} is {size} bytes"
        print(f"{path.name:32} {size:>8} bytes")


if __name__ == "__main__":
    main()
