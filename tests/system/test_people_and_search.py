"""Round 2: faces, people, claim, search, highlights, agent fallback. Needs the ML worker."""
import time
from pathlib import Path

import pytest
import requests

from conftest import BASE_URL, FIXTURES, upload, wait_for

pytestmark = [pytest.mark.round2]

PORTRAITS = sorted((FIXTURES / "faces").glob("*.jpg")) if (FIXTURES / "faces").exists() else []


@pytest.fixture
def analyzed_event(event, guest):
    """Uploads the portrait fixtures and waits until the worker has analyzed and clustered them."""
    if len(PORTRAITS) < 4:
        pytest.skip("portrait fixtures missing (apps/worker/fixtures/faces)")
    slug = event["slug"]
    items = [upload(guest, slug, p.name, p.read_bytes()) for p in PORTRAITS]
    wait_for(lambda: guest.get(f"/events/{slug}").json()["counts"]["faces_done"] >= len(items), timeout=600, every=3, what="analysis")
    wait_for(lambda: guest.get(f"/events/{slug}").json().get("clustered_at"), timeout=240, every=3, what="clustering")
    return event, items


@pytest.mark.ml
def test_people_appear_and_can_be_named_and_claimed(analyzed_event, guest):
    event, items = analyzed_event
    slug = event["slug"]
    people = guest.get(f"/events/{slug}/people").json()
    assert people["persons"], "no persons after clustering"
    top = people["persons"][0]
    assert top["face_count"] >= 2 and top["crop_url"]
    crop = guest.get(top["crop_url"].replace("/api/v1", ""))
    assert crop.status_code == 200 and crop.headers["content-type"] == "image/jpeg"

    assert guest.patch(f"/people/{top['id']}", json={"display_name": "Anna"}).json()["display_name"] == "Anna"
    me = guest.post(f"/people/{top['id']}/claim").json()
    assert me["is_me"] is True
    mine = guest.get(f"/events/{slug}/media?filter=me").json()
    assert len(mine["items"]) >= 1 and all(i["me"] for i in mine["items"])
    ev = guest.get(f"/events/{slug}").json()
    assert ev["counts"]["of_you"] == len(mine["items"])
    faces = guest.get(f"/media/{mine['items'][0]['id']}/faces").json()["faces"]
    assert any(f.get("person_id") == top["id"] for f in faces)


@pytest.mark.ml
def test_merge_split_and_not_person_change_clusters(analyzed_event, host):
    event, _ = analyzed_event
    slug = event["slug"]
    persons = host.get(f"/events/{slug}/people").json()["persons"]
    if len(persons) < 2:
        pytest.skip("need two persons to merge")
    a, b = persons[0], persons[1]
    merged = host.post("/people/merge", json={"person_ids": [a["id"], b["id"]]}).json()
    assert merged["id"] == a["id"] and merged["face_count"] >= a["face_count"] + b["face_count"]
    item = host.get(f"/events/{slug}/media?filter=person:{a['id']}").json()["items"][0]
    face = next(f for f in host.get(f"/media/{item['id']}/faces").json()["faces"] if f.get("person_id") == a["id"])
    split = host.post(f"/people/{a['id']}/split", json={"face_ids": [face["id"]]}).json()
    assert split["id"] != a["id"] and split["face_count"] == 1
    assert host.post(f"/faces/{face['id']}/not-person").status_code == 204


@pytest.mark.ml
def test_text_search_and_highlights(analyzed_event, guest):
    event, items = analyzed_event
    slug = event["slug"]
    r = guest.get(f"/events/{slug}/search", params={"q": "portrait of a person"})
    assert r.status_code == 200 and r.json()["items"], "semantic search returned nothing"
    best = guest.get(f"/events/{slug}/best").json()["items"]
    assert best and all(i["score"] is not None for i in best)
    assert guest.get(f"/events/{slug}/media?filter=best").json()["items"]


def test_agent_degrades_without_key_or_answers(event, guest):
    r = guest.post("/agent/messages", json={"text": "photos of me", "event_slug": event["slug"]})
    if r.status_code == 503:
        assert r.json()["error"]["message"] == "agent_not_configured"
        return
    assert r.status_code == 200
    body = r.json()
    assert body["understood"] and body["result"]["kind"] in {"media", "people", "stat", "album", "clarify", "empty"}


def test_privacy_controls(host, event):
    me = host.patch("/me", json={"birthdate": "1990-05-01", "link_across": True, "hide_from_people": False}).json()
    assert me["birthdate"] == "1990-05-01" and me["link_across"] is True
    assert host.patch("/me", json={"clear_birthdate": True}).json().get("birthdate") is None
    assert host.delete("/me/face-data").status_code == 204
    assert host.patch(f"/events/{event['slug']}", json={"faces_enabled": False}).json()["faces_enabled"] is False
