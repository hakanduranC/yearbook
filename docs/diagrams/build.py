# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib>=3.9"]
# ///
"""Builds every diagram embedded in docs/SDD.md.

    uv run docs/diagrams/build.py

Pure matplotlib with explicit layouts, so no Graphviz or Java is needed and the
output is identical on every machine. Coordinates are in "units" where one unit
is 0.1 inch; y grows downward like a page. Colors follow the product's final
design direction (off-white, black ink, gold accent).
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Circle, FancyArrowPatch, Rectangle  # noqa: E402

OUT = Path(__file__).parent
P = {
    "surface": "#f8f7f4", "raised": "#ffffff", "sunken": "#efede8", "tint": "#f1ece2",
    "ink": "#141414", "muted": "#6a675f", "gold": "#9a7645", "rose": "#b9524c",
    "green": "#3d6b4f", "border": "#e3e0d9", "strong": "#6a675f", "ext": "#e6e3dc",
    "ph": "#d9d2c6",
}
plt.rcParams.update({
    "font.family": ["Noto Sans", "DejaVu Sans"],
    "font.size": 10,
    "svg.fonttype": "none",
})
LH = 0.19  # line height in units per point of font size


# ----------------------------------------------------------------- toolkit
def canvas(w, h, title=None, subtitle=None):
    fig = plt.figure(figsize=(w / 10, h / 10), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, w)
    ax.set_ylim(h, 0)
    ax.axis("off")
    fig.patch.set_facecolor(P["surface"])
    if title:
        ax.text(4, 3.5, title, fontsize=15, weight="bold", color=P["ink"], va="top")
    if subtitle:
        ax.text(4, 7.6, subtitle, fontsize=9.5, color=P["muted"], va="top")
    return fig, ax


def save(fig, name):
    for ext in ("png", "svg"):
        fig.savefig(OUT / f"{name}.{ext}", dpi=200, facecolor=fig.get_facecolor())
    plt.close(fig)
    print("wrote", name)


STYLE = {
    "container": dict(fc=P["raised"], ec=P["ink"], lw=1.2, ls="-", tc=P["ink"], sc=P["muted"]),
    "store": dict(fc=P["sunken"], ec=P["ink"], lw=1.2, ls="-", tc=P["ink"], sc=P["muted"]),
    "external": dict(fc=P["ext"], ec=P["strong"], lw=1.0, ls=(0, (4, 3)), tc=P["ink"], sc=P["muted"]),
    "person": dict(fc=P["ink"], ec=P["ink"], lw=1.2, ls="-", tc="#ffffff", sc="#d8d2c8"),
    "accent": dict(fc=P["gold"], ec=P["gold"], lw=1.2, ls="-", tc="#ffffff", sc="#f3e9d6"),
    "note": dict(fc=P["tint"], ec=P["border"], lw=1.0, ls="-", tc=P["ink"], sc=P["muted"]),
    "step": dict(fc=P["raised"], ec=P["ink"], lw=1.0, ls="-", tc=P["ink"], sc=P["muted"]),
    "ghost": dict(fc="none", ec=P["strong"], lw=1.0, ls=(0, (5, 4)), tc=P["muted"], sc=P["muted"]),
}


def box(ax, x, y, w, h, title, sub=None, lines=(), kind="container", fs=10, align="center"):
    s = STYLE[kind]
    ax.add_patch(Rectangle((x, y), w, h, fc=s["fc"], ec=s["ec"], lw=s["lw"], ls=s["ls"], zorder=2))
    tx = x + w / 2 if align == "center" else x + 1.4
    cy = y + 1.3
    ax.text(tx, cy, title, ha=align, va="top", fontsize=fs + 1, weight="bold", color=s["tc"], zorder=3)
    cy += (fs + 1) * LH
    if sub:
        ax.text(tx, cy, sub, ha=align, va="top", fontsize=fs - 2, style="italic", color=s["sc"], zorder=3)
        cy += (fs - 2) * LH + 0.6
    for ln in lines:
        ax.text(tx, cy, ln, ha=align, va="top", fontsize=fs - 1.5, color=s["tc"], zorder=3)
        cy += (fs - 1.5) * LH
    return (x, y, w, h)


def person(ax, x, y, label, sub=None):
    ax.add_patch(Circle((x + 7, y + 2.6), 2.2, fc=P["ink"], ec=P["ink"], zorder=3))
    box(ax, x, y + 4.4, 14, 9.6 if sub else 6, label, sub, kind="person", fs=9)
    return (x, y, 14, 14)


def mid(r, side):
    x, y, w, h = r
    return {"l": (x, y + h / 2), "r": (x + w, y + h / 2), "t": (x + w / 2, y), "b": (x + w / 2, y + h)}[side]


def arrow(ax, a, b, label=None, color=None, ls="-", rad=0.0, lw=1.1, pos=0.5, two=False, fs=8, lcolor=None):
    color = color or P["ink"]
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="<|-|>" if two else "-|>", mutation_scale=11,
                                 color=color, lw=lw, ls=ls, connectionstyle=f"arc3,rad={rad}",
                                 shrinkA=1.5, shrinkB=1.5, zorder=4))
    if label:
        dx, dy = b[0] - a[0], b[1] - a[1]
        mx, my = a[0] + dx * pos, a[1] + dy * pos
        mx += -dy * rad * 0.5
        my += dx * rad * 0.5
        ax.text(mx, my, label, ha="center", va="center", fontsize=fs, color=lcolor or (P["muted"] if color == P["ink"] else color),
                bbox=dict(fc=P["surface"], ec="none", pad=1.6), zorder=5)


def poly(ax, pts, label=None, color=None, ls="-", lw=1.1, seg=None, fs=8):
    """Orthogonal multi-segment arrow. label sits on segment `seg` (default: longest)."""
    color = color or P["ink"]
    xs, ys = [q[0] for q in pts], [q[1] for q in pts]
    ax.add_line(Line2D(xs[:-1], ys[:-1], color=color, lw=lw, ls=ls, zorder=4))
    ax.add_patch(FancyArrowPatch(pts[-2], pts[-1], arrowstyle="-|>", mutation_scale=11, color=color, lw=lw, ls=ls, shrinkA=0, shrinkB=1.5, zorder=4))
    if label:
        if seg is None:
            seg = max(range(len(pts) - 1), key=lambda i: abs(pts[i + 1][0] - pts[i][0]) + abs(pts[i + 1][1] - pts[i][1]))
        a, b = pts[seg], pts[seg + 1]
        ax.text((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, label, ha="center", va="center", fontsize=fs,
                color=P["muted"] if color == P["ink"] else color, bbox=dict(fc=P["surface"], ec="none", pad=1.6), zorder=5)


def band(ax, x, y, w, h, label):
    ax.add_patch(Rectangle((x, y), w, h, fc=P["tint"], ec="none", zorder=0))
    ax.text(x + 1.5, y + h / 2, label, rotation=90, ha="center", va="center", fontsize=9, weight="bold", color=P["muted"], zorder=1)


# ------------------------------------------------------------ 1. C4 container
def c4():
    fig, ax = canvas(176, 112, "Yearbook · container diagram (C4 level 2)",
                     "Who talks to what. Photos, face crops and embeddings stay inside the boundary; only text and metadata cross to OpenAI.")
    bx, by, bw, bh = 34, 12, 98, 94
    ax.add_patch(Rectangle((bx, by), bw, bh, fc="none", ec=P["strong"], lw=1.2, ls=(0, (6, 4)), zorder=1))
    ax.text(bx + 1.5, by + 1.2, "Yearbook  [software system]  ·  one Hetzner VPS + Cloudflare", fontsize=8.5, color=P["muted"], va="top")

    host = person(ax, 8, 16, "Host / member", "signed in, any browser")
    guest = person(ax, 8, 60, "Guest", "phone browser, no account")

    web = box(ax, 42, 20, 30, 17, "Web app", "TanStack Start · Node", ["SSR for public pages, SPA after load,", "upload client, PWA shell"], fs=9)
    api = box(ax, 92, 20, 30, 17, "API", "Go · chi · sqlc", ["auth, events, media, people, likes,", "search, agent loop, MCP server"], fs=9)
    cdn = box(ax, 42, 52, 30, 13, "CDN", "Cloudflare", ["caches thumbnails and posters"], fs=9)
    db = box(ax, 92, 52, 30, 14, "PostgreSQL 16", "+ pgvector", ["system of record, face and image", "vectors, job queue, full-text search"], kind="store", fs=9)
    r2 = box(ax, 42, 82, 30, 15, "Object storage", "Cloudflare R2 (MinIO in dev)", ["originals + crops: private", "variants: public by random key"], kind="store", fs=9)
    wk = box(ax, 92, 82, 30, 15, "Worker", "Python · ONNX Runtime", ["variants, faces, SigLIP, quality,", "tags, age, clustering, transcode"], fs=9)

    oai = box(ax, 146, 20, 26, 14, "OpenAI", "Responses API", ["function calling for", "the chat agent"], kind="external", fs=9)
    mail = box(ax, 146, 52, 26, 11, "Email provider", "Resend / Postmark", ["magic links"], kind="external", fs=9)
    mcp = box(ax, 146, 84, 26, 11, "Other agents", "MCP clients", ["optional"], kind="external", fs=9)

    arrow(ax, mid(host, "r"), (42, 27), "HTTPS")
    arrow(ax, mid(guest, "r"), (42, 33), "scan QR, upload, browse", pos=0.45)
    arrow(ax, mid(guest, "r"), mid(cdn, "l"), "thumbnails", pos=0.5)
    arrow(ax, mid(guest, "r"), (42, 86), "presigned PUT, direct", pos=0.55)
    arrow(ax, mid(web, "r"), mid(api, "l"), "JSON · OpenAPI contract · SSE")
    arrow(ax, mid(api, "b"), mid(db, "t"), "SQL (pgx)")
    arrow(ax, (100, 66), (100, 82), "jobs table, SKIP LOCKED", pos=0.5)
    arrow(ax, (114, 82), (114, 66), "faces, embeddings, scores", pos=0.5)
    arrow(ax, mid(cdn, "b"), mid(r2, "t"), "origin pull")
    arrow(ax, mid(wk, "l"), mid(r2, "r"), "read originals, write variants")
    poly(ax, [(96, 37), (96, 44), (78, 44), (78, 89.5), (72, 89.5)], "presign, delete objects", seg=2)
    arrow(ax, mid(api, "r"), mid(oai, "l"), "text + metadata only", color=P["gold"], lw=1.4)
    arrow(ax, (122, 33), (146, 57), "send magic link", pos=0.55)
    arrow(ax, mid(mcp, "l"), (122, 34), "/mcp, bearer token", pos=0.45)

    box(ax, 36, 100.5, 94, 3.4, "Boundary rule: pixels and biometric vectors never leave this box. The agent sees ids, names people typed, timestamps, captions and counts.",
        kind="note", fs=7.5)
    save(fig, "c4-container")


# ------------------------------------------------------------- 2. ER diagram
def entity(ax, x, y, title, attrs, w=24):
    row = 1.85
    h = 3.2 + row * len(attrs) + 0.6
    ax.add_patch(Rectangle((x, y), w, h, fc=P["raised"], ec=P["ink"], lw=1.0, zorder=2))
    ax.add_patch(Rectangle((x, y), w, 3.0, fc=P["ink"], ec=P["ink"], zorder=2))
    ax.text(x + w / 2, y + 1.5, title, color="#ffffff", ha="center", va="center", weight="bold", fontsize=8.5, zorder=3)
    for i, a in enumerate(attrs):
        yy = y + 3.0 + row * (i + 0.55)
        pk, fk = a.startswith("*"), a.startswith("+")
        name = a.lstrip("*+")
        ax.text(x + 1.1, yy, name, va="center", fontsize=7.4, color=P["ink"], zorder=3,
                weight="bold" if pk else "normal", style="italic" if fk else "normal")
        if pk:
            ax.text(x + w - 1.0, yy, "PK", va="center", ha="right", fontsize=6.5, color=P["gold"], zorder=3)
        elif fk:
            ax.text(x + w - 1.0, yy, "FK", va="center", ha="right", fontsize=6.5, color=P["muted"], zorder=3)
    return (x, y, w, h)


def anchor(r, side, frac=0.5):
    x, y, w, h = r
    return {"l": (x, y + h * frac), "r": (x + w, y + h * frac), "t": (x + w * frac, y), "b": (x + w * frac, y + h)}[side]


def crow(ax, pt, direction, kind):
    """Draw a cardinality marker at pt. direction is the unit vector pointing INTO the box."""
    dx, dy = direction
    nx, ny = -dy, dx
    L, S = 2.2, 1.1
    back = (pt[0] - dx * L, pt[1] - dy * L)
    c = P["ink"]
    if kind == "n":
        for s in (-S, 0, S):
            ax.add_line(Line2D([back[0], pt[0] + nx * s], [back[1], pt[1] + ny * s], color=c, lw=1.0, zorder=4))
    else:  # one
        q = (pt[0] - dx * L * 0.6, pt[1] - dy * L * 0.6)
        ax.add_line(Line2D([q[0] + nx * S, q[0] - nx * S], [q[1] + ny * S, q[1] - ny * S], color=c, lw=1.0, zorder=4))


def rel(ax, a, b, sa, sb, ca="1", cb="n", fa=0.5, fb=0.5, label=None, via=None):
    pa, pb = anchor(a, sa, fa), anchor(b, sb, fb)
    pts = [pa] + (via or []) + [pb]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    ax.add_line(Line2D(xs, ys, color=P["ink"], lw=0.9, zorder=3))
    dirs = {"l": (1, 0), "r": (-1, 0), "t": (0, 1), "b": (0, -1)}
    crow(ax, pa, dirs[sa], ca)
    crow(ax, pb, dirs[sb], cb)
    if label:
        m = len(pts) // 2
        lx, ly = (pts[m - 1][0] + pts[m][0]) / 2, (pts[m - 1][1] + pts[m][1]) / 2
        ax.text(lx, ly, label, fontsize=6.8, color=P["muted"], ha="center", va="center", bbox=dict(fc=P["surface"], ec="none", pad=1.2), zorder=5)


def er():
    fig, ax = canvas(226, 160, "Yearbook · data model",
                     "PostgreSQL + pgvector. Bold = primary key, italic = foreign key. A person is a face cluster in one event; an identity is a human across events.")
    users = entity(ax, 6, 14, "users", ["*id", "email", "display_name", "birthdate (opt.)", "locale"])
    saved = entity(ax, 6, 60, "saved_commands", ["*id", "+owner", "scope", "name / label", "params (json schema)", "sql_template", "approved_at"])
    identities = entity(ax, 6, 108, "identities", ["*id", "+user_id (opt.)", "display_name", "birthdate (opt.)", "link_across"])

    members = entity(ax, 44, 14, "event_members", ["*+event_id", "*+user_id", "role"])
    events = entity(ax, 44, 40, "events", ["*id", "slug", "title", "starts_at, timezone", "location", "+owner_id", "guest_upload, guest_view"])
    guests = entity(ax, 44, 86, "guests", ["*id", "+event_id", "display_name (opt.)", "+user_id (opt.)"])
    albums = entity(ax, 44, 118, "albums", ["*id", "+event_id (opt.)", "owner", "title", "kind"])

    media = entity(ax, 84, 30, "media", ["*id", "+event_id", "+uploader_guest / user", "kind, state", "original_key", "captured_at", "phash, content_sha256", "dup_group_id"], w=26)
    likes = entity(ax, 84, 96, "likes", ["*+media_id", "*actor", "created_at"], w=26)
    items = entity(ax, 84, 122, "album_items", ["*+album_id", "*+media_id", "position"], w=26)

    variants = entity(ax, 126, 8, "media_variants", ["*+media_id", "*name", "key, width, height"])
    emb = entity(ax, 126, 30, "media_embeddings", ["*+media_id", "model", "embedding vector(1152)"])
    quality = entity(ax, 126, 52, "media_quality", ["*+media_id", "sharpness, exposure", "aesthetic", "face_count", "eyes_open, smile", "score"])
    tags = entity(ax, 126, 84, "media_tags", ["*+media_id", "*tag", "*source"])

    faces = entity(ax, 166, 14, "faces", ["*id", "+media_id", "+event_id", "+person_id (nullable)", "bbox, det_score, quality", "embedding vector(512)", "age_est", "eyes_open, smile", "crop_key"])
    persons = entity(ax, 166, 66, "persons", ["*id", "+event_id", "display_name (opt.)", "cover_face", "centroid vector(512)", "hidden"])
    links = entity(ax, 166, 106, "person_links", ["*+person_id", "+identity_id", "confirmed_by", "confidence"])
    constraints = entity(ax, 196, 36, "person_constraints", ["*+face_a", "*+face_b", "kind (must / cannot)"], w=26)

    rel(ax, users, members, "r", "l", "1", "n")
    rel(ax, members, events, "b", "t", "n", "1")
    rel(ax, users, events, "r", "l", "1", "n", fa=0.85, fb=0.55, label="owner")
    rel(ax, users, identities, "l", "l", "1", "1", fa=0.5, fb=0.5, via=[(2, 20.5), (2, 114.5)])
    rel(ax, users, saved, "b", "t", "1", "n", fa=0.7, fb=0.7)
    rel(ax, events, guests, "b", "t", "1", "n")
    rel(ax, events, media, "r", "l", "1", "n", fa=0.35, fb=0.3)
    rel(ax, guests, media, "r", "l", "1", "n", fa=0.5, fb=0.85, via=[(76, 91.6), (76, 45.8)], label="uploader")
    rel(ax, events, albums, "l", "l", "1", "n", fa=0.9, fb=0.5, via=[(40, 55.1), (40, 124.5)])
    rel(ax, albums, items, "r", "l", "1", "n")
    rel(ax, media, items, "b", "t", "1", "n", fa=0.8, fb=0.8)
    rel(ax, media, likes, "b", "t", "1", "n", fa=0.3, fb=0.3)
    rel(ax, media, variants, "r", "l", "1", "n", fa=0.12, fb=0.5)
    rel(ax, media, emb, "r", "l", "1", "1", fa=0.3, fb=0.5)
    rel(ax, media, quality, "r", "l", "1", "1", fa=0.5, fb=0.4)
    rel(ax, media, tags, "r", "l", "1", "n", fa=0.75, fb=0.5)
    rel(ax, media, faces, "t", "t", "1", "n", fa=0.6, fb=0.3, via=[(99.6, 6), (173.2, 6)])
    rel(ax, persons, faces, "t", "b", "1", "n", fa=0.4, fb=0.4)
    rel(ax, events, persons, "r", "l", "1", "n", fa=0.9, fb=0.2, via=[(80, 55.1), (80, 69)], label="per event")
    rel(ax, persons, links, "b", "t", "1", "1", fa=0.5, fb=0.5)
    rel(ax, identities, links, "r", "l", "1", "n", fa=0.5, fb=0.5, label="opt-in, confirmed")
    rel(ax, faces, constraints, "r", "l", "1", "n", fa=0.6, fb=0.5)

    box(ax, 118, 128, 58, 22, "Not shown", None, [
        "sessions, shares, agent_turns, duplicate_groups,",
        "jobs (the Postgres-backed queue).",
        "",
        "Agent access goes through v_* views over these",
        "tables: no embeddings, bboxes, emails or birthdates,",
        "filtered by the caller's memberships (RLS).",
    ], kind="note", fs=8, align="left")
    save(fig, "er-diagram")


# -------------------------------------------------------------- 3. user flows
def step(ax, x, y, label, w=22, h=7, kind="step"):
    return box(ax, x, y, w, h, label, kind=kind, fs=8.5)


def flows():
    fig, ax = canvas(214, 124, "Yearbook · user flows",
                     "Three roles, one album. Gold boxes are the moments the product exists for.")
    band(ax, 4, 14, 206, 32, "HOST")
    band(ax, 4, 50, 206, 34, "GUEST")
    band(ax, 4, 88, 206, 32, "MEMBER")

    h1 = step(ax, 10, 20, "Sign in\n(magic link)")
    h2 = step(ax, 38, 20, "Create event")
    h3 = step(ax, 66, 20, "Show or print\nQR code")
    h4 = step(ax, 120, 20, "Review uploads\nremove, retry")
    h5 = step(ax, 148, 20, "Merge / split\npeople")
    h6 = step(ax, 176, 20, "Curate highlights,\nshare album")
    for a, b in ((h1, h2), (h2, h3), (h4, h5), (h5, h6)):
        arrow(ax, mid(a, "r"), mid(b, "l"))
    arrow(ax, mid(h3, "r"), mid(h4, "l"), "event night", ls=(0, (3, 3)), lw=0.9)

    g1 = step(ax, 10, 58, "Scan QR")
    g2 = step(ax, 38, 58, "Landing page\n(no account)")
    g3 = step(ax, 66, 58, "Pick photos,\nupload resumes", kind="accent")
    g4 = step(ax, 94, 58, "Enter name\n(optional)")
    g5 = step(ax, 122, 58, "\"Is this you?\"\nconfirm", kind="accent")
    g6 = step(ax, 150, 58, "Photos of me", kind="accent")
    g7 = step(ax, 178, 58, "Like, save,\ndownload")
    for a, b in ((g1, g2), (g2, g3), (g3, g4), (g4, g5), (g5, g6), (g6, g7)):
        arrow(ax, mid(a, "r"), mid(b, "l"))
    g8 = step(ax, 122, 73, "Browse gallery,\nBest, Videos")
    arrow(ax, (112, 65), mid(g8, "l"), "not now", pos=0.4)
    arrow(ax, mid(g8, "r"), (161, 65), "tap Me", pos=0.5)

    m1 = step(ax, 10, 96, "Home: albums\nyou're in")
    m2 = step(ax, 38, 96, "Gallery or\nBest of")
    m3 = step(ax, 66, 96, "Ask for anything", kind="accent")
    m4 = step(ax, 94, 96, "Result grid +\nunderstood line")
    m5 = step(ax, 122, 96, "Refine or\nsave as chip")
    m6 = step(ax, 150, 96, "Confirm \"also\nyou?\" elsewhere")
    m7 = step(ax, 178, 96, "Your year", kind="accent")
    for a, b in ((m1, m2), (m2, m3), (m3, m4), (m4, m5), (m1, m6), (m6, m7)):
        if (a, b) == (m1, m6):
            arrow(ax, mid(m1, "b"), mid(m6, "b"), "People across events", rad=0.18, pos=0.5)
        else:
            arrow(ax, mid(a, "r"), mid(b, "l"))

    arrow(ax, mid(h3, "b"), mid(g1, "t"), "guest scans", color=P["gold"], rad=0.25, pos=0.5)
    arrow(ax, mid(g3, "b"), (49, 96), "same album, visible to members instantly", color=P["gold"], pos=0.55, lcolor=P["gold"])
    save(fig, "user-flows")


# ----------------------------------------------------------- 4. sequence diagrams
def sequence(name, title, subtitle, participants, steps, col_w=27, note_h=5.4):
    n = len(participants)
    left, top, row = 6, 13, 5.4
    rows = sum(2.2 if s[0] == "note" else (1.3 if s[0] == "msg" and s[1] == s[2] else 1) for s in steps)
    w = left * 2 + col_w * (n - 1) + 20
    h = top + 9 + row * rows + 6
    fig, ax = canvas(w, h, title, subtitle)
    xs = {k: left + 10 + i * col_w for i, (k, _, _) in enumerate(participants)}
    for k, label, kind in participants:
        box(ax, xs[k] - 9.5, top, 19, 5, label, kind=kind, fs=8.5)
        ax.add_line(Line2D([xs[k], xs[k]], [top + 5, h - 4], color=P["strong"], lw=0.8, ls=(0, (3, 3)), zorder=1))
    y = top + 9
    for s in steps:
        kind = s[0]
        if kind == "msg":
            _, f, t, text, *opt = s
            style = opt[0] if opt else "sync"
            ls = (0, (4, 3)) if style == "return" else "-"
            color = P["gold"] if style == "accent" else P["ink"]
            if f == t:
                x = xs[f]
                d = -1 if f == participants[-1][0] else 1   # last lifeline loops to the left
                ax.add_line(Line2D([x, x + 5 * d, x + 5 * d], [y, y, y + 2.6], color=color, lw=1.0, zorder=3))
                ax.add_patch(FancyArrowPatch((x + 5 * d, y + 2.6), (x + 0.5 * d, y + 2.6), arrowstyle="-|>", mutation_scale=10, color=color, lw=1.0, zorder=3))
                ax.text(x + 6 * d, y + 1.2, text, ha="left" if d > 0 else "right", va="center", fontsize=8, color=P["ink"],
                        bbox=dict(fc=P["surface"], ec="none", pad=1.2), zorder=5)
                y += row * 1.3
            else:
                arrow(ax, (xs[f], y), (xs[t], y), ls=ls, color=color, lw=1.1)
                ax.text((xs[f] + xs[t]) / 2, y - 0.7, text, ha="center", va="bottom", fontsize=8,
                        color=P["gold"] if style == "accent" else P["ink"],
                        bbox=dict(fc=P["surface"], ec="none", pad=1.0), zorder=5)
                y += row
        elif kind == "note":
            _, keys, text = s
            x0 = min(xs[k] for k in keys) - 9.5
            x1 = max(xs[k] for k in keys) + 9.5
            lines = textwrap.wrap(text, width=int((x1 - x0) / 0.62))
            nh = 2.6 + len(lines) * 7.5 * LH
            ax.add_patch(Rectangle((x0, y - 1.2), x1 - x0, nh, fc=P["tint"], ec=P["border"], lw=1.0, zorder=2))
            for i, ln in enumerate(lines):
                ax.text(x0 + 1.6, y + 0.3 + i * 7.5 * LH, ln, ha="left", va="top", fontsize=7.5, color=P["ink"], zorder=3)
            y += row * 2.2
        elif kind == "gap":
            _, text = s
            ax.add_line(Line2D([4, w - 4], [y, y], color=P["border"], lw=1, zorder=1))
            ax.text(w / 2, y - 0.6, text, ha="center", va="bottom", fontsize=8, style="italic", color=P["muted"],
                    bbox=dict(fc=P["surface"], ec="none", pad=1.5))
            y += row
    save(fig, name)


def seq_upload():
    sequence("seq-upload", "Sequence · guest upload",
             "From tapping \"Add your photos\" to a thumbnail in everyone's grid. Bytes go straight to storage; the API only sees metadata.",
             [("g", "Guest browser", "person"), ("w", "Web app", "container"), ("a", "API (Go)", "container"),
              ("s", "Object storage", "store"), ("q", "jobs (Postgres)", "store"), ("k", "Worker (Py)", "container")],
             [
                 ("msg", "g", "w", "pick files (multi-select)"),
                 ("msg", "w", "a", "POST /events/{slug}/uploads  {name, bytes, mime, prefix_sha256}"),
                 ("msg", "a", "a", "media row, state=uploading"),
                 ("msg", "a", "w", "{media_id, presigned PUT or multipart part URLs}", "return"),
                 ("msg", "w", "s", "PUT bytes directly (retry per part, pause offline)", "accent"),
                 ("msg", "s", "w", "200 + ETag", "return"),
                 ("msg", "w", "a", "POST /uploads/{id}/complete {etags}"),
                 ("msg", "a", "s", "HEAD object exists?"),
                 ("msg", "a", "q", "INSERT job(kind=ingest)   ·   media.state=queued"),
                 ("msg", "a", "w", "media (processing cell appears in grid)", "return"),
                 ("gap", "asynchronous, seconds later"),
                 ("msg", "k", "q", "SELECT … FOR UPDATE SKIP LOCKED"),
                 ("msg", "k", "s", "GET original"),
                 ("msg", "k", "k", "probe, decode HEIC, EXIF, variants"),
                 ("msg", "k", "s", "PUT thumb/small/medium/large .webp"),
                 ("msg", "k", "q", "UPDATE media state=ready · NOTIFY media.ready"),
                 ("msg", "a", "w", "SSE media.ready {media_id, variants}", "accent"),
                 ("msg", "w", "g", "cell swaps shimmer for the CDN thumbnail"),
                 ("note", ["k", "q"], "Faces, embeddings, quality, tags and age follow in the same job; People and Best update through later SSE events."),
             ])


def seq_agent():
    sequence("seq-agent", "Sequence · \"photos of me and Anna, only the best\"",
             "The model plans; our tools search. Only text and metadata are sent out. The result is a structured object the UI renders as a grid.",
             [("u", "Member", "person"), ("w", "Web app", "container"), ("a", "API agent loop", "container"),
              ("o", "OpenAI Responses", "external"), ("d", "Postgres (RLS)", "store")],
             [
                 ("msg", "u", "w", "types the sentence"),
                 ("msg", "w", "a", "POST /agent/messages {scope: event, text}"),
                 ("msg", "a", "a", "system prompt: viewer name, event, date, locale, tool list"),
                 ("msg", "a", "o", "input + tools (resolve_people, search_media, rank_best, run_query, present…)", "accent"),
                 ("msg", "o", "a", "tool_call resolve_people(names=[\"me\",\"Anna\"])", "return"),
                 ("msg", "a", "d", "SELECT persons … is_me, name ILIKE 'anna%'"),
                 ("msg", "a", "o", "result: [{me, person 7}, {Anna Berg, person 12, 0.98}]"),
                 ("msg", "o", "a", "tool_call search_media(people_all=[7,12], order=score)", "return"),
                 ("msg", "a", "d", "one SQL: face join ∩ filters, best-of-burst, limit 200"),
                 ("msg", "a", "o", "result: 15 media ids + total"),
                 ("msg", "o", "a", "tool_call rank_best(ids, n=20, diversity=true)", "return"),
                 ("msg", "a", "d", "scores, burst groups"),
                 ("msg", "a", "o", "result: 15 ids ordered"),
                 ("msg", "o", "a", "tool_call present({kind:'media', title, media_ids, refine:[…]}) + understood", "return"),
                 ("msg", "a", "a", "store turn, previous_response_id for follow-ups"),
                 ("msg", "a", "w", "{understood, result, suggestions, saveable:true}", "return"),
                 ("msg", "w", "u", "grid of 15, \"Showing you and Anna Berg · best first\", chips"),
                 ("gap", "optional"),
                 ("msg", "u", "w", "tap \"Save as chip\""),
                 ("msg", "w", "a", "POST /agent/commands {turn_id, label}"),
                 ("msg", "a", "o", "turn final call into a parameterized template"),
                 ("msg", "a", "d", "INSERT saved_commands (approved for owner)"),
                 ("note", ["a", "d"], "Next time the chip runs with no model call. In new conversations it is offered to the model as tool saved_me_and_person(person)."),
             ])


def seq_claim():
    sequence("seq-claim", "Sequence · finding yourself, in one event and across events",
             "Clustering is per event and automatic. Linking a cluster to a human is always a confirmed action.",
             [("g", "Guest / member", "person"), ("w", "Web app", "container"), ("a", "API (Go)", "container"),
              ("d", "Postgres", "store"), ("k", "Worker", "container")],
             [
                 ("gap", "after uploads settle (debounced 60 s)"),
                 ("msg", "k", "d", "cluster_event: load faces + persons + constraints"),
                 ("msg", "k", "k", "assign new faces to centroids (cos ≥ 0.52), HDBSCAN the rest"),
                 ("msg", "k", "d", "UPDATE faces.person_id, persons.centroid, cover_face · NOTIFY people.updated"),
                 ("gap", "guest entered a name after uploading"),
                 ("msg", "w", "a", "GET /events/{slug}/people"),
                 ("msg", "a", "d", "persons + suggested_me (uploader's own photos ∩ most frequent face)"),
                 ("msg", "a", "w", "[{person 7, suggested_me:true, 23 photos}, …]", "return"),
                 ("msg", "w", "g", "\"Is this you?\" card with the face crop"),
                 ("msg", "g", "w", "This is me", "accent"),
                 ("msg", "w", "a", "POST /people/7/claim"),
                 ("msg", "a", "d", "identity for guest/user · INSERT person_links(7 → identity)"),
                 ("msg", "a", "w", "person 7 is_me", "return"),
                 ("msg", "w", "g", "Photos of me (23) · Me badge on cells"),
                 ("gap", "later, signed in, other events"),
                 ("msg", "w", "a", "GET /me/suggestions"),
                 ("msg", "a", "d", "reference set = top 30 faces of claimed persons (+ age if birthdate)"),
                 ("msg", "a", "d", "unclaimed persons in my events: max cosine ≥ 0.45, age-consistent"),
                 ("msg", "a", "w", "[{event: Lisbon, person 41, 0.61}]", "return"),
                 ("msg", "w", "g", "\"Also you, in Lisbon?\" → confirm", "accent"),
                 ("msg", "w", "a", "POST /people/41/claim"),
                 ("note", ["a", "d"], "Each confirmation grows the reference set. Nothing links without a tap; \"Group my face across events\" off stops suggestions entirely."),
             ])


# ---------------------------------------------------------- 5. ingestion stages
def ingest():
    fig, ax = canvas(214, 118, "Yearbook · ingestion pipeline (one media item)",
                     "Each stage is idempotent and records completion, so a crashed job resumes. The photo is usable after stage 4; everything else enriches it.")
    stages_a = [
        ("1 Fetch", "original from R2\nto tmpfs", "~0.1 s"),
        ("2 Probe", "EXIF, GPS, dims,\nffprobe for video", "~0.1 s"),
        ("3 Decode", "HEIC → sRGB,\napply orientation", "~0.2 s"),
        ("4 Variants", "WebP 256 / 640 /\n1280 / 2048 + thumb", "~0.3 s"),
        ("5 Hashes", "SHA-256, pHash,\ndup + burst groups", "~0.1 s"),
    ]
    stages_b = [
        ("6 Faces", "SCRFD detect, ArcFace\nembed, eyes, smile, crop", "~0.4 s"),
        ("7 Embedding", "SigLIP 2 so400m,\n1152-d, normalized", "~0.5 s"),
        ("8 Quality", "aesthetic, sharpness,\nexposure → score", "~0.1 s"),
        ("9 Tags + OCR", "Florence-2 caption,\nOCR → tags, tsvector", "~1.5 s"),
        ("10 Age", "MiVOLO v2 per face\n(face + body crop)", "~0.2 s / face"),
        ("11 Finish", "state=ready, bump\ndebounced cluster job", ""),
    ]
    W, H, G = 30, 15, 5
    ya, yb = 30, 66
    boxes_a, boxes_b = [], []
    for i, (t, d, tm) in enumerate(stages_a):
        x = 39 + i * (W + G)
        boxes_a.append(box(ax, x, ya, W, H, t, None, d.split("\n"), kind="step", fs=8.5))
        ax.text(x + 1, ya + H + 2.2, tm, ha="left", fontsize=7.5, color=P["muted"])
    for i, (t, d, tm) in enumerate(stages_b):
        x = 4 + i * (W + G)
        boxes_b.append(box(ax, x, yb, W, H, t, None, d.split("\n"), kind="step", fs=8.5))
        ax.text(x + 1, yb + H + 2.2, tm, ha="left", fontsize=7.5, color=P["muted"])
    for a, b in zip(boxes_a, boxes_a[1:]):
        arrow(ax, mid(a, "r"), mid(b, "l"))
    for a, b in zip(boxes_b, boxes_b[1:]):
        arrow(ax, mid(a, "r"), mid(b, "l"))
    poly(ax, [mid(boxes_a[-1], "b"), (194, 52), (19, 52), mid(boxes_b[0], "t")])

    trig = box(ax, 4, ya + 2, 14, 11, "job:\ningest", None, [], kind="store", fs=8)
    arrow(ax, mid(trig, "r"), mid(boxes_a[0], "l"))
    ax.text(11, ya + 15, "from jobs table\nSKIP LOCKED", ha="center", va="top", fontsize=7, color=P["muted"])

    vb = box(ax, 39, 12, 62, 10, "Video branches at stage 3", None,
             ["ffmpeg → H.264 mp4 (1080p max), poster at 1 s; sampled frames", "every 3 s go through stages 6–10 so faces and search cover videos"], kind="note", fs=8)
    poly(ax, [mid(boxes_a[2], "t"), (124, 17), (101, 17)], "if video", ls=(0, (3, 3)), lw=0.9, seg=0)

    cl = box(ax, 164, 94, 45, 14, "job: cluster_event", "debounced 60 s, per event", ["assign faces → persons, HDBSCAN", "the rest, respect merges / splits"], kind="store", fs=8.5)
    arrow(ax, mid(boxes_b[-1], "b"), mid(cl, "t"))

    def flag(x, y, text):
        ax.add_patch(Circle((x, y), 1.1, fc=P["gold"], ec=P["gold"], zorder=5))
        ax.text(x + 2.2, y, text, va="center", fontsize=7.5, color=P["gold"], weight="bold", zorder=5)
    flag(boxes_a[3][0] + 1.5, ya - 2.6, "grid shows the photo · SSE media.ready")
    flag(boxes_b[0][0] + 1.5, yb + H + 5.6, "People tab fills after cluster_event")
    flag(boxes_b[1][0] + 1.5, yb + H + 5.6, "text search works")
    flag(boxes_b[2][0] + 1.5, yb + H + 5.6, "Best filter ranks")
    ax.text(107, 114, "Throughput on 4 vCPU, no GPU: 2–4 photos/s end to end · a 500-photo event completes in under five minutes · Florence runs late so People and search are live before captions exist.",
            ha="center", fontsize=7.5, color=P["muted"])
    save(fig, "ingest-pipeline")


# ------------------------------------------------------------- 6. wireframes
def phone(ax, x, y, w=40, h=86):
    ax.add_patch(Rectangle((x, y), w, h, fc=P["raised"], ec=P["ink"], lw=1.3, zorder=2))
    return (x, y, w, h)


def img(ax, x, y, w, h, tone=None):
    ax.add_patch(Rectangle((x, y), w, h, fc=tone or P["sunken"], ec=P["border"], lw=0.6, zorder=3))
    ax.add_line(Line2D([x, x + w], [y, y + h], color=P["border"], lw=0.6, zorder=3))
    ax.add_line(Line2D([x, x + w], [y + h, y], color=P["border"], lw=0.6, zorder=3))


def txt(ax, x, y, w, size=1.0, color=None):
    ax.add_patch(Rectangle((x, y), w, size, fc=color or P["strong"], ec="none", zorder=3))


def label(ax, x, y, s, fs=6.2, color=None, weight="normal", ha="left"):
    ax.text(x, y, s, fontsize=fs, color=color or P["ink"], va="center", ha=ha, zorder=4)


def btn(ax, x, y, w, s, primary=True, h=4.2):
    ax.add_patch(Rectangle((x, y), w, h, fc=P["ink"] if primary else "none", ec=P["ink"], lw=0.9, zorder=3))
    label(ax, x + w / 2, y + h / 2, s, fs=6, color="#ffffff" if primary else P["ink"], ha="center", weight="bold")


def chip(ax, x, y, w, s, active=False, gold=False):
    ec = P["gold"] if gold else P["ink"]
    ax.add_patch(Rectangle((x, y), w, 3.2, fc=P["ink"] if active else "none", ec=ec, lw=0.7, zorder=3))
    label(ax, x + w / 2, y + 1.6, s, fs=5.2, color="#ffffff" if active else (P["gold"] if gold else P["ink"]), ha="center")


def bottombar(ax, f, left, right=None, lw_=None):
    x, y, w, h = f
    by = y + h - 9
    ax.add_line(Line2D([x, x + w], [by, by], color=P["border"], lw=0.8, zorder=3))
    if right:
        btn(ax, x + 2, by + 2.4, w / 2 - 3, left, primary=False)
        btn(ax, x + w / 2 + 1, by + 2.4, w / 2 - 3, right, primary=True)
    else:
        btn(ax, x + 2, by + 2.4, w - 4, left, primary=True)


def grid3(ax, x, y, w, rows, marks=()):
    cell = (w - 0.8) / 3
    for r in range(rows):
        for c in range(3):
            cx, cy = x + c * (cell + 0.4), y + r * (cell + 0.4)
            img(ax, cx, cy, cell, cell)
            if (r, c) in marks:
                ax.add_patch(Rectangle((cx + 0.8, cy + cell - 2.6), 5.5, 1.9, fc="none", ec="#ffffff", lw=0.6, zorder=4))
                ax.add_patch(Rectangle((cx + 0.8, cy + cell - 2.6), 5.5, 1.9, fc=P["gold"], ec="none", zorder=3.5))
                label(ax, cx + 3.55, cy + cell - 1.65, "YOU", fs=3.8, color="#ffffff", ha="center", weight="bold")
    return y + rows * (cell + 0.4)


def wire_landing(ax, x, y):
    f = phone(ax, x, y)
    img(ax, x, y, 40, 52, tone=P["ph"])
    label(ax, x + 20, y + 36, "MERT INVITES YOU TO", fs=4.2, color=P["muted"], ha="center")
    label(ax, x + 20, y + 42, "Anna's Thirtieth", fs=10, ha="center", weight="bold")
    label(ax, x + 20, y + 48, "SAT 14 JUNE · KANTINE FABRIK", fs=4.2, color=P["muted"], ha="center")
    label(ax, x + 20, y + 58, "Add what you captured tonight.", fs=5.6, ha="center")
    label(ax, x + 20, y + 62, "Tomorrow, find every photo you're in.", fs=4.6, color=P["muted"], ha="center")
    btn(ax, x + 3, y + 70, 34, "Add your photos", h=5)
    btn(ax, x + 3, y + 77, 34, "See photos", primary=False)
    return f


def wire_upload(ax, x, y):
    f = phone(ax, x, y)
    label(ax, x + 3, y + 4, "‹  Adding to Anna's 30th", fs=5.8, weight="bold")
    label(ax, x + 6, y + 7.5, "12 of 14 uploaded · you can close this tab", fs=4.2, color=P["muted"])
    states = ["done", "done", "done", "64 %", "waiting for connection", "failed · Retry"]
    for i, s in enumerate(states):
        yy = y + 11 + i * 6.2
        img(ax, x + 3, yy, 5, 5)
        txt(ax, x + 10, yy + 1.2, 14, 0.9)
        label(ax, x + 10, yy + 3.6, s, fs=4.2, color=P["rose"] if "failed" in s else P["muted"])
        if "%" in s:
            ax.add_patch(Rectangle((x + 10, yy + 4.6), 26, 0.6, fc=P["sunken"], ec="none", zorder=3))
            ax.add_patch(Rectangle((x + 10, yy + 4.6), 16.6, 0.6, fc=P["ink"], ec="none", zorder=3))
    ax.add_patch(Rectangle((x, y + 50), 40, 36, fc=P["raised"], ec=P["ink"], lw=0.8, zorder=3.5))
    ax.add_line(Line2D([x + 15, x + 25], [y + 51.5, y + 51.5], color=P["border"], lw=1.4, zorder=4))
    label(ax, x + 3, y + 56, "Done. Want to find photos of you?", fs=5.6, weight="bold")
    label(ax, x + 3, y + 60, "Enter your name and we'll show you every", fs=4.2, color=P["muted"])
    label(ax, x + 3, y + 62.5, "photo you're in. Optional, event-only.", fs=4.2, color=P["muted"])
    ax.add_patch(Rectangle((x + 3, y + 66), 34, 5, fc="none", ec=P["ink"], lw=0.7, zorder=4))
    label(ax, x + 4.5, y + 68.5, "Your name", fs=4.6, color=P["muted"])
    btn(ax, x + 3, y + 73.5, 34, "Find photos of me")
    label(ax, x + 20, y + 81.5, "Not now, see photos", fs=4.8, color=P["gold"], ha="center")
    return f


def wire_gallery(ax, x, y):
    f = phone(ax, x, y)
    label(ax, x + 3, y + 5, "Anna's 30th", fs=7.5, weight="bold")
    label(ax, x + 3, y + 8.6, "128 photos · 3 videos · still finding faces 96/128", fs=3.9, color=P["muted"])
    chip(ax, x + 29, y + 3.2, 8, "ME · 23", gold=True)
    for i, (s, w, a) in enumerate([("All", 6, True), ("Best", 7, False), ("Videos", 9, False), ("Mine", 7, False)]):
        chip(ax, x + 3 + sum(v[1] + 1 for v in [("All", 6), ("Best", 7), ("Videos", 9), ("Mine", 7)][:i]), y + 11.5, w, s, active=a)
    label(ax, x + 3, y + 18, "Saturday night", fs=5.8)
    yy = grid3(ax, x + 1, y + 20.5, 38, 3, marks={(0, 1), (1, 2)})
    label(ax, x + 3, yy + 2.6, "Dinner", fs=5.8)
    grid3(ax, x + 1, yy + 5, 38, 1)
    ax.add_patch(Rectangle((x + 3, y + 64), 34, 5, fc=P["raised"], ec=P["ink"], lw=0.8, zorder=4))
    label(ax, x + 5, y + 66.5, "Ask for anything", fs=5, color=P["muted"])
    ax.add_patch(Rectangle((x + 32, y + 64), 5, 5, fc=P["ink"], ec=P["ink"], zorder=4))
    bottombar(ax, f, "Add photos", "Select")
    return f


def wire_lightbox(ax, x, y):
    f = phone(ax, x, y)
    ax.add_patch(Rectangle((x, y), 40, 86, fc="#121212", ec=P["ink"], lw=1.3, zorder=2.5))
    label(ax, x + 3, y + 4, "✕", fs=6, color="#ffffff")
    label(ax, x + 20, y + 4, "37 of 128", fs=4.6, color="#ffffff", ha="center")
    img(ax, x, y + 10, 40, 50, tone="#2a2623")
    label(ax, x + 3, y + 64, "Uploaded by Mert · Sat 23:14", fs=4.2, color="#bdb6ad")
    for i, s in enumerate(["Anna Berg", "YOU", "Mert"]):
        ax.add_patch(Circle((x + 5 + i * 11, y + 69), 1.6, fc="#4a4440", ec=P["gold"] if s == "YOU" else "#777", lw=0.6, zorder=4))
        label(ax, x + 7.5 + i * 11, y + 69, s, fs=3.9, color=P["gold"] if s == "YOU" else "#ffffff")
    for i, s in enumerate(["♥ 12", "Save", "Share"]):
        label(ax, x + 7 + i * 13, y + 78, s, fs=5, color=P["rose"] if i == 0 else "#ffffff", ha="center")
    return f


def wire_people(ax, x, y):
    f = phone(ax, x, y)
    label(ax, x + 3, y + 4.5, "‹  People", fs=7.5, weight="bold")
    label(ax, x + 3, y + 9, "We group faces so you can find yourself.", fs=4, color=P["muted"])
    label(ax, x + 3, y + 11.5, "Names are optional, event-only. Face settings", fs=4, color=P["muted"])
    ax.add_patch(Rectangle((x + 3, y + 14.5), 34, 15, fc=P["raised"], ec=P["border"], lw=0.7, zorder=3))
    ax.add_patch(Circle((x + 8, y + 19.5), 3, fc=P["ph"], ec=P["gold"], lw=0.8, zorder=4))
    label(ax, x + 13, y + 18.5, "Is this you?", fs=5.6, weight="bold")
    label(ax, x + 13, y + 21.5, "23 photos match the name you entered", fs=3.9, color=P["muted"])
    btn(ax, x + 5, y + 24.3, 14, "Not me", primary=False, h=3.6)
    btn(ax, x + 21, y + 24.3, 14, "This is me", h=3.6)
    label(ax, x + 3, y + 34, "Everyone at Anna's 30th", fs=5.6)
    names = [("Anna Berg", "42"), ("YOU", "23"), ("Mert", "18"), ("Lea K.", "15"), ("Unnamed", "9"), ("Unnamed", "7")]
    for i, (n, c) in enumerate(names):
        cx, cy = x + 8.5 + (i % 3) * 11.5, y + 42 + (i // 3) * 15
        dashed = n == "Unnamed"
        ax.add_patch(Circle((cx, cy), 4.2, fc=P["ph"] if not dashed else P["sunken"], ec=P["strong"] if dashed else P["gold"], lw=0.8, ls=(0, (2, 2)) if dashed else "-", zorder=4))
        label(ax, cx, cy + 6, n, fs=4.2, ha="center", color=P["gold"] if n == "YOU" else (P["muted"] if dashed else P["ink"]), weight="bold" if n == "YOU" else "normal")
        label(ax, cx, cy + 8.4, c + " photos", fs=3.7, ha="center", color=P["muted"])
    bottombar(ax, f, "Photos", "Photos of me")
    return f


def wire_search(ax, x, y):
    f = phone(ax, x, y)
    label(ax, x + 3, y + 4.5, "‹  Anna's 30th", fs=6, weight="bold")
    ax.add_patch(Rectangle((x + 3, y + 8), 34, 5, fc=P["raised"], ec=P["ink"], lw=0.8, zorder=3))
    label(ax, x + 5, y + 10.5, "photos of me and Anna", fs=5)
    label(ax, x + 3, y + 16, "Showing you and Anna Berg together · 14 photos, 1 video", fs=3.8, color=P["gold"])
    label(ax, x + 3, y + 21, "You and Anna, together", fs=5.8)
    label(ax, x + 37, y + 21, "Save as chip", fs=4.2, color=P["gold"], ha="right")
    yy = grid3(ax, x + 1, y + 24, 38, 3, marks={(r, c) for r in range(3) for c in range(3)})
    label(ax, x + 3, yy + 3, "Refine", fs=4.4, color=P["muted"])
    chip(ax, x + 3, yy + 5, 11, "Only the best")
    chip(ax, x + 15, yy + 5, 11, "Saturday night")
    chip(ax, x + 27, yy + 5, 9, "Add Mert")
    bottombar(ax, f, "All events", "Download 15")
    return f


def wire_home(ax, x, y):
    f = phone(ax, x, y)
    label(ax, x + 3, y + 4, "YEARBOOK · 2026", fs=4.2, color=P["muted"])
    ax.add_patch(Circle((x + 7, y + 11.5), 3.6, fc=P["ph"], ec=P["gold"], lw=0.9, zorder=4))
    label(ax, x + 13, y + 10, "Hakan", fs=9, weight="bold")
    label(ax, x + 13, y + 14, "in 71 moments this year", fs=4.4, color=P["muted"])
    ax.add_line(Line2D([x + 3, x + 37], [y + 18, y + 18], color=P["ink"], lw=0.7, zorder=3))
    label(ax, x + 3, y + 21.5, "ALBUMS YOU'RE IN", fs=4, color=P["muted"])
    for i, (t, of, meta) in enumerate([("Anna's 30th", "23 OF YOU", "14 June · 128 photos"), ("Lea & Tom", "8 OF YOU", "2 Aug · 412 · analyzing"), ("Lisbon", "40 OF YOU", "April · 240 photos")]):
        yy = y + 25 + i * 17
        for k in (2, 1, 0):
            img(ax, x + 3 + k * 1.6, yy + k * 0.6, 12, 14, tone=[P["ph"], "#c6beb0", "#e8e3da"][k])
        label(ax, x + 20, yy + 3, of, fs=3.9, color=P["gold"], weight="bold")
        label(ax, x + 20, yy + 7, t, fs=6, weight="bold")
        label(ax, x + 20, yy + 10.5, meta, fs=3.9, color=P["muted"])
    bottombar(ax, f, "People", "New event")
    return f


def wire_year(ax, x, y):
    f = phone(ax, x, y)
    img(ax, x, y, 40, 46, tone="#8a7f74")
    label(ax, x + 3, y + 4, "‹", fs=6, color="#ffffff")
    label(ax, x + 37, y + 4, "2026 · VOL. 1", fs=4, color="#ffffff", ha="right")
    label(ax, x + 3, y + 33, "YOUR YEAR SO FAR", fs=3.9, color="#e3cfa6")
    label(ax, x + 3, y + 38.5, "Hakan", fs=11, color="#ffffff", weight="bold")
    label(ax, x + 3, y + 43, "In 71 moments · 3 events · most often with Anna", fs=3.7, color="#ffffff")
    label(ax, x + 3, y + 51, "Your best shots", fs=5.8)
    label(ax, x + 37, y + 51, "ALL 71", fs=3.9, color=P["gold"], ha="right")
    ax.add_line(Line2D([x + 3, x + 37], [y + 53.5, y + 53.5], color=P["ink"], lw=0.7, zorder=3))
    grid3(ax, x + 1, y + 55, 38, 1, marks={(0, 0), (0, 1), (0, 2)})
    for i, (n, c) in enumerate([("Anna Berg", "61"), ("Mert", "38"), ("Lea K.", "24")]):
        chip(ax, x + 3 + i * 11.5, y + 70, 11, f"{n} · {c}")
    bottombar(ax, f, "Share my year", "Save all")
    return f


def wireframes():
    fig, ax = canvas(204, 206, "Yearbook · core screens, low fidelity",
                     "Structure only. Visual design lives on the Claude Design canvas (Final row). Gold marks anything about the viewer.")
    screens = [
        ("1  Event landing  /e/{slug}", wire_landing), ("2  Upload  /e/{slug}/upload", wire_upload),
        ("3  Gallery  /e/{slug}/photos", wire_gallery), ("4  Lightbox  /photos/{id}", wire_lightbox),
        ("5  People  /e/{slug}/people", wire_people), ("6  Search results  /search?q=", wire_search),
        ("7  Home  /", wire_home), ("8  Your year  /year/2026", wire_year),
    ]
    for i, (name, fn) in enumerate(screens):
        x = 6 + (i % 4) * 49
        y = 14 + (i // 4) * 97
        fn(ax, x, y)
        ax.text(x, y + 89.5, name, fontsize=7.5, weight="bold", color=P["ink"], va="top")
    save(fig, "wireframes")


if __name__ == "__main__":
    c4()
    er()
    flows()
    seq_upload()
    seq_agent()
    seq_claim()
    ingest()
    wireframes()
