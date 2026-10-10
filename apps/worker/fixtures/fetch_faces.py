"""Fetch the public-domain portrait fixtures used by the ML tests (faces, clustering, age).

All files are NASA photographs published on Wikimedia Commons as public domain (works of the
US federal government). Run `uv run python fixtures/fetch_faces.py` from apps/worker to
(re)download them; 800 px renditions re-encoded as JPEG q82 (~1.3 MB in total) are committed
under `fixtures/faces/` together with `SOURCES.json` (title, URL, author, license per file).
No image is AI generated.

Labels: four identities with two single portraits each, plus two group photos that contain one
of them among other crew members. Expected clustering on the eight singles: four persons.
"""

from __future__ import annotations

import io
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageOps

HERE = Path(__file__).resolve().parent
OUT = HERE / "faces"
API = "https://commons.wikimedia.org/w/api.php"
UA = "yearbook-worker-fixtures/0.1 (test fixtures; contact: dev@yearbook.local)"
WIDTH = 800
QUALITY = 82

# fmt: off
FILES: tuple[tuple[str, str], ...] = (
    ("whitson_1", "File:PeggyWhitson-NASA.jpg"),
    ("whitson_2", "File:Peggy Whitson.jpg"),
    ("williams_1", "File:Sunita Williams.jpg"),
    ("williams_2", "File:Sunita Williams in 2018 (cropped).jpg"),
    ("jemison_1", "File:Mae Carol Jemison (cropped 2).jpg"),
    ("jemison_2", "File:Mae Jemison - Official portrait of 1987 astronaut candidate.jpg"),
    ("kelly_1", "File:Scott J. Kelly (cropped).jpg"),
    ("kelly_2", "File:Scott J Kelly.jpg"),
    # groups: Williams + Wilmore (2 faces); STS-47 crew with Jemison (7 faces)
    ("group_williams_wilmore",
     "File:Boeing CFT Crew Portrait-Sunita Williams and Barry Wilmore "
     "(KSC-20240404-PH-NAS01 0001).jpg"),
    ("group_sts47_jemison", "File:STS-47 in-flight crew portrait.jpg"),
)
# fmt: on

# Hand labels for `yearbook-worker eval-cluster` (largest face per file).
LABELS: dict[str, str] = {
    "whitson_1.jpg": "whitson",
    "whitson_2.jpg": "whitson",
    "williams_1.jpg": "williams",
    "williams_2.jpg": "williams",
    "jemison_1.jpg": "jemison",
    "jemison_2.jpg": "jemison",
    "kelly_1.jpg": "kelly",
    "kelly_2.jpg": "kelly",
}


def api(params: dict[str, object]) -> dict:
    url = API + "?" + urllib.parse.urlencode({"format": "json", **params})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def reencode(data: bytes) -> bytes:
    with Image.open(io.BytesIO(data)) as im:
        im = ImageOps.exif_transpose(im) or im
        im = im.convert("RGB")
        if im.width > WIDTH:
            im = im.resize((WIDTH, round(im.height * WIDTH / im.width)), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=QUALITY, optimize=True, progressive=True)
        return buf.getvalue()


def main() -> None:
    OUT.mkdir(exist_ok=True)
    info = api(
        {
            "action": "query",
            "prop": "imageinfo",
            "iiprop": "url|size|extmetadata",
            "iiurlwidth": WIDTH,
            "titles": "|".join(t for _, t in FILES),
        }
    )
    by_title = {}
    for page in info["query"]["pages"].values():
        if "imageinfo" not in page:
            raise SystemExit(f"{page['title']}: not found on Commons")
        by_title[page["title"]] = page["imageinfo"][0]
    # the API normalizes titles (underscores, capitalization); map back via `normalized`
    for n in info["query"].get("normalized", []):
        by_title[n["from"]] = by_title[n["to"]]

    sources = {}
    total = 0
    for label, title in FILES:
        ii = by_title[title]
        meta = ii["extmetadata"]
        license_ = meta.get("LicenseShortName", {}).get("value", "")
        if "public domain" not in license_.lower():
            raise SystemExit(f"{title}: unexpected license {license_!r}")
        dest = OUT / f"{label}.jpg"
        data = reencode(fetch(ii["thumburl"]))
        dest.write_bytes(data)
        total += len(data)
        sources[dest.name] = {
            "title": title,
            "page": ii["descriptionurl"],
            "author": _strip_tags(meta.get("Artist", {}).get("value", "")),
            "license": license_,
            "width": WIDTH,
        }
        print(dest.name, license_, len(data), "bytes")
    (OUT / "SOURCES.json").write_text(json.dumps(sources, indent=2, ensure_ascii=False) + "\n")
    (OUT / "labels.json").write_text(json.dumps(LABELS, indent=2) + "\n")
    print(f"total {total} bytes")


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html).strip()


if __name__ == "__main__":
    main()
