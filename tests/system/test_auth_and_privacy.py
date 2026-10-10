"""Sign-in, cookies, CSRF and visibility rules."""
import uuid

import requests

from conftest import API, Client, magic_link_for


def test_magic_link_is_single_use_and_logout_clears_session():
    email = f"once-{uuid.uuid4().hex[:6]}@system.test"
    token = magic_link_for(email, locale="en")
    c = Client()
    assert c.post("/auth/verify", json={"token": token}).status_code == 200
    assert c.post("/auth/verify", json={"token": token}).status_code == 400
    assert c.get("/me").json()["authenticated"] is True
    assert c.post("/auth/logout").status_code == 204
    assert c.get("/me").json()["authenticated"] is False


def test_mutations_without_origin_are_rejected(event):
    r = requests.post(f"{API}/events/{event['slug']}/guests", timeout=30)  # no Origin header
    assert r.status_code == 403


def test_guest_view_off_hides_media_from_anonymous(event, host, guest):
    slug = event["slug"]
    assert host.patch(f"/events/{slug}", json={"guest_view": False}).status_code == 200
    anon = requests.get(f"{API}/events/{slug}/media", timeout=30)
    assert anon.status_code in (401, 403)
    assert host.get(f"/events/{slug}/media").status_code == 200
    host.patch(f"/events/{slug}", json={"guest_view": True})


def test_turkish_magic_mail_exists():
    email = f"tr-{uuid.uuid4().hex[:6]}@system.test"
    assert magic_link_for(email, locale="tr")
