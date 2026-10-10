"""The critical path: a guest uploads, the worker processes, everyone sees it live."""
import threading
import time

import requests

from conftest import API, BASE_URL, make_jpeg, sse_events, upload, wait_for


def test_landing_is_server_rendered_in_three_languages(event):
    for lang, needle in (("de", "lädt dich ein"), ("en", "invites you"), ("tr", None)):
        html = requests.get(f"{BASE_URL}/e/{event['slug']}", headers={"Accept-Language": lang}, timeout=30).text
        assert f'<html lang="{lang}"' in html or (lang == "tr" and '<html lang="' in html), lang
        assert event["title"] in html
        assert 'property="og:title"' in html
        if needle:
            assert needle in html, f"{lang} copy missing"


def test_guest_upload_is_processed_and_streamed(event, guest):
    slug = event["slug"]
    seen: list = []
    t = threading.Thread(target=lambda: seen.extend(sse_events(slug, 40)), daemon=True)
    t.start()
    time.sleep(1)

    item = upload(guest, slug, "party.jpg", make_jpeg(seed=1))
    assert item["state"] == "queued" and item["mine"] is True and item["processing"] is True

    ready = wait_for(lambda: (lambda r: r if r["state"] == "ready" else None)(guest.get(f"/media/{item['id']}").json()), what="media ready")
    assert set(ready["variants"]) == {"thumb", "small", "medium", "large"}
    for url in ready["variants"].values():
        head = requests.head(url, timeout=30)
        assert head.status_code == 200 and head.headers["content-type"] == "image/webp", url
    assert ready["width"] == 640 and ready["height"] == 480

    t.join(timeout=45)
    names = [n for n, _ in seen]
    assert "media.queued" in names and "media.ready" in names, names
    ready_payload = next(d for n, d in seen if n == "media.ready")
    assert ready_payload["id"] == item["id"]


def test_exact_duplicate_is_detected_on_second_upload(event, guest):
    data = make_jpeg(seed=2)
    first = upload(guest, event["slug"], "a.jpg", data)
    wait_for(lambda: guest.get(f"/media/{first['id']}").json()["state"] == "ready", what="first ready")
    import hashlib
    sha = hashlib.sha256(data).hexdigest()
    r = guest.post(f"/events/{event['slug']}/uploads", json={"files": [{"client_id": "x", "name": "b.jpg", "size": len(data), "type": "image/jpeg", "sha256": sha}]})
    init = r.json()["uploads"][0]
    assert init["mode"] == "duplicate" and init["duplicate_of"] == first["id"] and init["item"]["id"] == first["id"]


def test_likes_zip_and_delete(event, guest, host):
    slug = event["slug"]
    items = [upload(guest, slug, f"p{i}.jpg", make_jpeg(seed=10 + i)) for i in range(3)]
    for it in items:
        wait_for(lambda it=it: guest.get(f"/media/{it['id']}").json()["state"] == "ready", what="ready")

    r = guest.put(f"/media/{items[0]['id']}/like")
    assert r.status_code == 200 and r.json() == {"media_id": items[0]["id"], "like_count": 1, "liked": True}
    r = host.put(f"/media/{items[0]['id']}/like")
    assert r.json()["like_count"] == 2
    r = guest.delete(f"/media/{items[0]['id']}/like")
    assert r.json()["like_count"] == 1 and r.json()["liked"] is False

    page = guest.get(f"/events/{slug}/media?filter=mine").json()
    assert {i["id"] for i in page["items"]} >= {i["id"] for i in items}
    assert page["groups"] and all(g["count"] >= 1 for g in page["groups"])

    r = guest.post("/media/zip", json={"media_ids": [i["id"] for i in items]})
    assert r.status_code == 200
    ticket = r.json()
    z = requests.get(BASE_URL + ticket["url"] if ticket["url"].startswith("/") else ticket["url"], timeout=120)
    assert z.status_code == 200 and z.headers["content-type"].startswith("application/zip")
    import io, zipfile
    with zipfile.ZipFile(io.BytesIO(z.content)) as zf:
        assert zf.testzip() is None and len(zf.namelist()) == 3

    # uploader can delete own photo; host can delete anyone's
    assert guest.delete(f"/media/{items[1]['id']}").status_code == 204
    assert host.delete(f"/media/{items[2]['id']}").status_code == 204
    left = {i["id"] for i in guest.get(f"/events/{slug}/media").json()["items"]}
    assert items[1]["id"] not in left and items[2]["id"] not in left and items[0]["id"] in left


def test_host_review_and_status(event, guest, host):
    slug = event["slug"]
    it = upload(guest, slug, "review.jpg", make_jpeg(seed=42))
    guest.patch(f"/events/{slug}/guests/me", json={"display_name": "Mia"})
    wait_for(lambda: host.get(f"/events/{slug}/status").json()["ready"] >= 1, what="status ready")
    rev = host.get(f"/events/{slug}/uploads").json()
    mia = next(u for u in rev["uploaders"] if u["display_name"] == "Mia")
    assert mia["total"] >= 1 and any(i["id"] == it["id"] and i["name"] == "review.jpg" for i in mia["items"])
    assert guest.get(f"/events/{slug}/uploads").status_code in (401, 403)


def test_qr_and_share_page(event, host):
    svg = host.get(f"/events/{event['slug']}/qr.svg")
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml") and "<svg" in svg.text
