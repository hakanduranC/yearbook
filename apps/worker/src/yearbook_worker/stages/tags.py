"""tags: Florence-2 caption → `media.caption` + `media_tags(florence)`, OCR → `media_tags(ocr)`."""

from __future__ import annotations

import re
import unicodedata

import psycopg

from yearbook_worker.analysis import AnalysisContext
from yearbook_worker.stages.variants import resize_long_edge

CAPTION_TASK = "<MORE_DETAILED_CAPTION>"
OCR_TASK = "<OCR>"
OCR_MAX_TOKENS = 64
MAX_TAGS = 40
MIN_LEN = 3

_WORD = re.compile(r"[^\W\d_]+(?:['\u2019-][^\W\d_]+)*", re.UNICODE)
_OCR_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)

# English function words plus the scaffolding Florence-2 captions always use.
STOPWORDS = frozenset(
    word
    for line in (
        "a an the and or but if while of at by for with about against between into through",
        "during before after above below to from up down in out on off over under again further",
        "then once here there when where why how all any both each few more most other some such",
        "no nor not only own same so than too very can will just should now is are was were be",
        "been being have has had having do does did doing i me my we our you your he him his she",
        "her it its they them their what which who whom this that these those am as until because",
        "also one two three four five several many much",
        "image picture photo photograph shows showing shown seen visible appears appear appearing",
        "seems seem looks looking like background foreground front left right side top bottom",
        "center centre middle overall scene setting view close-up closeup taken captured camera",
        "suggests suggesting indicating indicates likely possibly perhaps something someone",
        "somewhere",
    )
    for word in line.split()
)

CAPTION_UPDATE_SQL = "update media set caption = %(caption)s where id = %(id)s"
DELETE_TAGS_SQL = "delete from media_tags where media_id = %(id)s and source = any(%(sources)s)"
INSERT_TAG_SQL = """
insert into media_tags (media_id, tag, source) values (%(id)s, %(tag)s, %(source)s)
on conflict do nothing
"""


def _normalize(word: str) -> str:
    return unicodedata.normalize("NFKC", word).lower().strip("'\u2019-")


def extract_caption_tags(caption: str, *, limit: int = MAX_TAGS) -> list[str]:
    """Lower-cased content words (≥ 3 letters, not stop words), first occurrence order."""
    out: list[str] = []
    seen: set[str] = set()
    for match in _WORD.finditer(caption or ""):
        word = _normalize(match.group(0))
        if len(word) < MIN_LEN or word in STOPWORDS or word in seen:
            continue
        seen.add(word)
        out.append(word)
        if len(out) >= limit:
            break
    return out


def extract_ocr_words(text: str, *, limit: int = MAX_TAGS) -> list[str]:
    """Lower-cased OCR tokens of at least 3 characters, letters or digits, de-duplicated."""
    out: list[str] = []
    seen: set[str] = set()
    for match in _OCR_TOKEN.finditer(text or ""):
        token = _normalize(match.group(0))
        if len(token) < MIN_LEN or token in seen or (token.isdigit() and len(token) < 4):
            continue
        seen.add(token)
        out.append(token)
        if len(out) >= limit:
            break
    return out


def run(ctx: AnalysisContext, conn: psycopg.Connection) -> None:
    image = resize_long_edge(ctx.image, 1024)
    caption = ctx.hub.florence_task(
        image, CAPTION_TASK, max_new_tokens=ctx.settings.worker_caption_max_tokens
    )
    ocr = ctx.hub.florence_task(image, OCR_TASK, max_new_tokens=OCR_MAX_TOKENS)
    conn.execute(CAPTION_UPDATE_SQL, {"id": ctx.media.id, "caption": caption[:2000] or None})
    conn.execute(DELETE_TAGS_SQL, {"id": ctx.media.id, "sources": ["florence", "ocr"]})
    for tag in extract_caption_tags(caption):
        conn.execute(INSERT_TAG_SQL, {"id": ctx.media.id, "tag": tag, "source": "florence"})
    for tag in extract_ocr_words(ocr):
        conn.execute(INSERT_TAG_SQL, {"id": ctx.media.id, "tag": tag, "source": "ocr"})
