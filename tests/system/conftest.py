"""System tests: drive the whole stack (gateway, API, worker, S3, Mailpit) through real user flows.

Run against the Compose `app` profile (default http://localhost:8000) or the host dev stack:

    cd tests/system && uv run pytest -q                       # gateway on :8000
    BASE_URL=http://localhost:3000 uv run pytest -q           # host dev (web proxies /api)

Nothing is mocked. Tests create their own users and events and clean up what they can.
"""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import requests
from PIL import Image

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
API = f"{BASE_URL}/api/v1"
MAILPIT = os.environ.get("MAILPIT_URL", "http://localhost:8025").rstrip("/")
ORIGIN_HEADERS = {"Origin": BASE_URL}
REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "apps" / "worker" / "fixtures"


def _up(url: str) -> bool:
    try:
        return requests.get(url, timeout=3).status_code < 500
    except requests.RequestException:
        return False


@pytest.fixture(scope="session", autouse=True)
def stack_is_up():
    missing = [u for u in (f"{API}/health", f"{BASE_URL}/", f"{MAILPIT}/api/v1/info") if not _up(u)]
    if missing:
        pytest.exit(f"stack not reachable: {missing}. Start it with `docker compose -f infra/compose.yaml --profile app up -d`", returncode=2)


@dataclass
class Client:
    """A browser-like HTTP session with the Origin header the API's CSRF check wants."""

    s: requests.Session = field(default_factory=requests.Session)

    def __post_init__(self):
        self.s.headers.update(ORIGIN_HEADERS)

    def get(self, path, **kw):
        return self.s.get(API + path, timeout=30, **kw)

    def post(self, path, json=None, **kw):
        return self.s.post(API + path, json=json, timeout=30, **kw)

    def put(self, path, json=None, **kw):
        return self.s.put(API + path, json=json, timeout=30, **kw)

    def patch(self, path, json=None, **kw):
        return self.s.patch(API + path, json=json, timeout=30, **kw)

    def delete(self, path, **kw):
        return self.s.delete(API + path, timeout=30, **kw)


def magic_link_for(email: str, locale: str = "de") -> str:
    """Request a magic link and read it back from Mailpit."""
    r = requests.post(f"{API}/auth/magic", json={"email": email, "locale": locale}, headers=ORIGIN_HEADERS, timeout=30)
    assert r.status_code == 204, r.text
    deadline = time.time() + 20
    while time.time() < deadline:
        msgs = requests.get(f"{MAILPIT}/api/v1/search", params={"query": f"to:{email}"}, timeout=10).json().get("messages", [])
        if msgs:
            body = requests.get(f"{MAILPIT}/api/v1/message/{msgs[0]['ID']}", timeout=10).json()
            text = body.get("Text", "") + body.get("HTML", "")
            m = re.search(r"token=([A-Za-z0-9_-]+)", text)
            if m:
                return m.group(1)
        time.sleep(0.5)
    raise AssertionError(f"no magic link mail for {email}")


@pytest.fixture
def host() -> Client:
    """A signed-in user with a fresh email."""
    c = Client()
    email = f"host-{uuid.uuid4().hex[:8]}@system.test"
    token = magic_link_for(email)
    r = c.post("/auth/verify", json={"token": token})
    assert r.status_code == 200, r.text
    assert r.json()["me"]["email"] == email
    return c


@pytest.fixture
def event(host: Client) -> dict:
    r = host.post("/events", json={"title": f"System test {uuid.uuid4().hex[:4]}", "starts_at": "2026-06-14T16:00:00Z", "timezone": "Europe/Berlin", "location": "Berlin"})
    assert r.status_code == 201, r.text
    ev = r.json()
    yield ev
    host.delete(f"/events/{ev['slug']}")


@pytest.fixture
def guest(event: dict) -> Client:
    c = Client()
    r = c.post(f"/events/{event['slug']}/guests")
    assert r.status_code == 200, r.text
    return c


def make_jpeg(w: int = 640, h: int = 480, seed: int = 0) -> bytes:
    """A deterministic photo-like JPEG so uploads are unique per seed."""
    img = Image.new("RGB", (w, h), (30 + seed * 7 % 200, 90, 160))
    for i in range(6):
        x0 = (i * 97 + seed * 13) % (w - 80)
        y0 = (i * 61 + seed * 29) % (h - 80)
        Image.Image.paste(img, Image.new("RGB", (80, 80), ((i * 40) % 255, (seed * 50) % 255, 120)), (x0, y0))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def upload(client: Client, slug: str, name: str, data: bytes, mime: str = "image/jpeg") -> dict:
    """Full upload path: intent → presigned PUT → complete. Returns the GridItem."""
    r = client.post(f"/events/{slug}/uploads", json={"files": [{"client_id": "1", "name": name, "size": len(data), "type": mime}]})
    assert r.status_code == 200, r.text
    init = r.json()["uploads"][0]
    if init["mode"] == "duplicate":
        return init["item"]
    assert init["mode"] == "single", init
    put = requests.put(init["url"], data=data, headers=init.get("headers", {}), timeout=120)
    assert put.status_code in (200, 201), put.text
    r = client.post(f"/uploads/{init['media_id']}/complete")
    assert r.status_code == 200, r.text
    return r.json()


def wait_for(predicate, timeout: float = 90, every: float = 1.0, what: str = "condition"):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(every)
    raise AssertionError(f"timed out waiting for {what}; last={last!r}")


def sse_events(slug: str, seconds: float, cookies=None) -> list[tuple[str, dict]]:
    """Collect SSE events from the event stream for a fixed time window."""
    out: list[tuple[str, dict]] = []
    with requests.get(f"{API}/events/{slug}/events", stream=True, timeout=seconds + 5, cookies=cookies, headers={"Accept": "text/event-stream"}) as r:
        r.raise_for_status()
        start = time.time()
        name = None
        for raw in r.iter_lines(decode_unicode=True):
            if time.time() - start > seconds:
                break
            if raw is None:
                continue
            if raw.startswith("event:"):
                name = raw[6:].strip()
            elif raw.startswith("data:") and name:
                try:
                    out.append((name, json.loads(raw[5:].strip())))
                except json.JSONDecodeError:
                    out.append((name, {}))
                name = None
    return out


def compose(*args: str) -> str:
    """Run a docker compose command for the app profile; used only for operator tools like ybctl."""
    cmd = ["docker", "compose", "-f", str(REPO / "infra" / "compose.yaml"), "--profile", "app", *args]
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
