"""A fake of the Go API's MCP server with the SDD §9 tool names and plausible results.

Runs as a Starlette app under uvicorn in a thread (`serve_in_thread`). It records every call and
the headers it saw so tests can assert that the viewer's token and event slug were forwarded.
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Any

import uvicorn
from mcp.server.fastmcp import Context, FastMCP

from .. import ids

# Deterministic fixture ids (22-char base64url of fixed bytes).
P_ME = ids.encode(b"person-me-000000")
P_ANNA = ids.encode(b"person-anna-0000")
P_BEN = ids.encode(b"person-ben-00000")
P_ANNA2 = ids.encode(b"person-anna-k-00")
MEDIA = [ids.encode(f"media-{i:010d}".encode()) for i in range(12)]
ALBUM = ids.encode(b"album-00000000-1")

PERSONS = {
    P_ME: {
        "id": P_ME,
        "event_slug": "sommerfest-x1y2",
        "display_name": "Hakan",
        "named": True,
        "face_count": 37,
        "media_count": 37,
        "is_me": True,
        "hidden": False,
        "linked": True,
    },
    P_ANNA: {
        "id": P_ANNA,
        "event_slug": "sommerfest-x1y2",
        "display_name": "Anna",
        "named": True,
        "face_count": 22,
        "media_count": 20,
        "is_me": False,
        "hidden": False,
        "linked": False,
    },
    P_BEN: {
        "id": P_BEN,
        "event_slug": "sommerfest-x1y2",
        "display_name": "Ben",
        "named": True,
        "face_count": 9,
        "media_count": 9,
        "is_me": False,
        "hidden": False,
        "linked": False,
    },
}
# Which persons appear on which media.
MEDIA_PERSONS = {
    MEDIA[0]: [P_ME, P_ANNA],
    MEDIA[1]: [P_ME, P_ANNA],
    MEDIA[2]: [P_ME],
    MEDIA[3]: [P_ANNA],
    MEDIA[4]: [P_ME, P_BEN],
    MEDIA[5]: [P_BEN],
    MEDIA[6]: [],
    MEDIA[7]: [P_ME, P_ANNA, P_BEN],
    MEDIA[8]: [P_ANNA],
    MEDIA[9]: [],
    MEDIA[10]: [P_ME],
    MEDIA[11]: [P_ME, P_ANNA],
}


def _item(mid: str, i: int) -> dict[str, Any]:
    return {
        "id": mid,
        "kind": "video" if i == 9 else "photo",
        "captured_at": f"2026-07-18T{14 + i % 8:02d}:{(i * 7) % 60:02d}:00+02:00",
        "person_ids": MEDIA_PERSONS[mid],
        "score": round(0.4 + (i % 6) * 0.1, 2),
        "like_count": i % 3,
        "variants": {
            "thumb": f"http://public.test/v/{mid}/thumb.webp",
            "small": f"http://public.test/v/{mid}/small.webp",
            "medium": f"http://public.test/v/{mid}/medium.webp",
            "large": f"http://public.test/v/{mid}/large.webp",
        },
    }


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.headers: list[dict[str, str]] = []

    def reset(self) -> None:
        self.calls.clear()
        self.headers.clear()


def make_server(
    recorder: Recorder | None = None, ambiguous_anna: bool = False
) -> tuple[FastMCP, Recorder]:
    rec = recorder or Recorder()
    mcp = FastMCP("yearbook-fake", stateless_http=True, json_response=True)

    def record(ctx: Context, name: str, args: dict[str, Any]) -> None:
        rec.calls.append((name, args))
        try:
            req = ctx.request_context.request
            rec.headers.append(
                {
                    "authorization": req.headers.get("authorization", ""),
                    "x-event-slug": req.headers.get("x-event-slug", ""),
                }
            )
        except Exception:
            rec.headers.append({})

    @mcp.tool(description="Find named persons in scope by name. Returns matches per query.")
    def resolve_people(names: list[str], ctx: Context) -> dict[str, Any]:
        record(ctx, "resolve_people", {"names": names})
        matches = []
        for n in names:
            low = n.lower()
            found = [
                p
                for p in PERSONS.values()
                if p["display_name"] and low in p["display_name"].lower()
            ]
            if low == "anna" and ambiguous_anna:
                found = [
                    {**PERSONS[P_ANNA], "display_name": "Anna M."},
                    {**PERSONS[P_ANNA], "id": P_ANNA2, "display_name": "Anna K.", "face_count": 6},
                ]
            matches.append({"query": n, "persons": found})
        return {"matches": matches}

    @mcp.tool(description="Hybrid search over media in scope with structured filters.")
    def search_media(
        ctx: Context,
        text: str | None = None,
        people_all: list[str] | None = None,
        people_any: list[str] | None = None,
        people_exclude: list[str] | None = None,
        me: bool = False,
        kind: str | None = None,
        from_: str | None = None,
        to: str | None = None,
        day_part: str | None = None,
        uploaded_by_me: bool = False,
        liked_by_me: bool = False,
        faces_min: int | None = None,
        faces_max: int | None = None,
        min_score: float | None = None,
        tags: list[str] | None = None,
        age_min: int | None = None,
        age_max: int | None = None,
        age_mode: str | None = None,
        order_by: str = "recent",
        limit: int = 60,
    ) -> dict[str, Any]:
        args = {k: v for k, v in locals().items() if k != "ctx" and v not in (None, False, [])}
        record(ctx, "search_media", args)
        want = set(people_all or [])
        if me:
            want.add(P_ME)
        hits = []
        for i, mid in enumerate(MEDIA):
            ps = set(MEDIA_PERSONS[mid])
            if want and not want <= ps:
                continue
            if people_any and not ps & set(people_any):
                continue
            if people_exclude and ps & set(people_exclude):
                continue
            if kind == "video" and i != 9:
                continue
            if kind == "photo" and i == 9:
                continue
            if faces_max is not None and len(ps) > faces_max:
                continue
            if text and "zebra" in text.lower():
                continue
            hits.append(_item(mid, i))
        if min_score is not None:
            hits = [h for h in hits if h["score"] >= min_score]
        if order_by == "best":
            hits.sort(key=lambda h: -h["score"])
        hits = hits[: max(1, min(limit, 200))]
        return {"count": len(hits), "media_ids": [h["id"] for h in hits], "items": hits}

    @mcp.tool(description="Rank media by quality score; without ids ranks the whole scope.")
    def rank_best(
        ctx: Context, media_ids: list[str] | None = None, limit: int = 20
    ) -> dict[str, Any]:
        record(ctx, "rank_best", {"media_ids": media_ids, "limit": limit})
        pool = media_ids or MEDIA
        items = sorted(
            (_item(m, MEDIA.index(m)) for m in pool if m in MEDIA), key=lambda h: -h["score"]
        )
        items = items[:limit]
        return {"count": len(items), "media_ids": [h["id"] for h in items], "items": items}

    @mcp.tool(description="List persons in scope.")
    def list_people(ctx: Context) -> dict[str, Any]:
        record(ctx, "list_people", {})
        return {"persons": list(PERSONS.values())}

    @mcp.tool(description="Metadata of one media item: time, caption, tags, persons, variant URLs.")
    def describe_media(media_id: str, ctx: Context) -> dict[str, Any]:
        record(ctx, "describe_media", {"media_id": media_id})
        if media_id not in MEDIA:
            raise ValueError("not found")
        it = _item(media_id, MEDIA.index(media_id))
        return {**it, "caption": "People at a table outdoors", "tags": ["outdoor", "table", "cake"]}

    @mcp.tool(description="Create an album from media ids. Returns the Album.")
    def create_album(title: str, media_ids: list[str], ctx: Context) -> dict[str, Any]:
        record(ctx, "create_album", {"title": title, "media_ids": media_ids})
        return {
            "id": ALBUM,
            "event_slug": "sommerfest-x1y2",
            "title": title,
            "kind": "agent",
            "count": len(media_ids),
            "can_edit": True,
        }

    @mcp.tool(description="Like a media item as the viewer.")
    def like_media(media_id: str, ctx: Context) -> dict[str, Any]:
        record(ctx, "like_media", {"media_id": media_id})
        return {"media_id": media_id, "like_count": 3, "liked": True}

    @mcp.tool(description="Create a share link for an album.")
    def share_album(album_id: str, ctx: Context) -> dict[str, Any]:
        record(ctx, "share_album", {"album_id": album_id})
        return {"share_id": ids.encode(b"share-0000000001"), "url": "http://web.test/s/share"}

    @mcp.tool(description="Start a zip export of media ids.")
    def export_zip(media_ids: list[str], ctx: Context) -> dict[str, Any]:
        record(ctx, "export_zip", {"media_ids": media_ids})
        return {"url": "http://web.test/api/v1/media/zip/abc", "count": len(media_ids)}

    @mcp.tool(
        description="Counts for the scope: media, photos, videos, persons, uploaders, busiest hour."
    )
    def event_stats(ctx: Context) -> dict[str, Any]:
        record(ctx, "event_stats", {})
        return {
            "media": 412,
            "photos": 398,
            "videos": 14,
            "persons": 23,
            "uploaders": 31,
            "busiest_hour": "2026-07-18T21:00:00+02:00",
            "first_at": "2026-07-18T14:02:00+02:00",
            "last_at": "2026-07-19T01:40:00+02:00",
        }

    @mcp.tool(
        description="One read-only SELECT over v_events, v_media, v_persons, v_faces, v_tags, "
        "v_likes."
    )
    def run_query(sql: str, ctx: Context) -> dict[str, Any]:
        record(ctx, "run_query", {"sql": sql})
        low = sql.lower().strip()
        if not low.startswith("select"):
            raise ValueError(f'only a single SELECT is allowed (got "{sql[:30]}")')
        if "v_nonexistent" in low:
            raise ValueError('relation "v_nonexistent" does not exist')
        if "v_persons" in low:
            return {
                "columns": ["id", "display_name", "n"],
                "rows": [[P_ANNA, "Anna", 20], [P_BEN, "Ben", 9]],
                "row_count": 2,
            }
        if "date_trunc" in low:
            return {
                "columns": ["h", "n"],
                "rows": [
                    [f"2026-07-18T{h:02d}:00:00+02:00", n]
                    for h, n in (
                        (14, 12),
                        (15, 40),
                        (16, 55),
                        (17, 61),
                        (18, 44),
                        (19, 70),
                        (20, 58),
                        (21, 72),
                    )
                ],
                "row_count": 8,
            }
        return {"columns": ["n"], "rows": [[37]], "row_count": 1}

    return mcp, rec


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeMCPServer:
    """`with FakeMCPServer() as srv: srv.url` runs the fake over streamable HTTP in a thread."""

    def __init__(self, ambiguous_anna: bool = False) -> None:
        self.mcp, self.recorder = make_server(ambiguous_anna=ambiguous_anna)
        self.port = _free_port()
        self.url = f"http://127.0.0.1:{self.port}/mcp"
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> FakeMCPServer:
        app = self.mcp.streamable_http_app()
        config = uvicorn.Config(
            app, host="127.0.0.1", port=self.port, log_level="warning", lifespan="on"
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        deadline = time.time() + 10
        while not self._server.started:
            if time.time() > deadline:
                raise RuntimeError("fake MCP server did not start")
            time.sleep(0.05)
        return self

    def __exit__(self, *exc: object) -> None:
        if self._server:
            self._server.should_exit = True
        if self._thread:
            self._thread.join(timeout=5)
