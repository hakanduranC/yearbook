"""Round 2: import archives, library, albums, shares, yearbook recap."""
import io
import zipfile

import pytest
import requests

from conftest import BASE_URL, FIXTURES, make_jpeg, upload, wait_for

pytestmark = [pytest.mark.round2]


def _archive() -> bytes:
    """A tiny Takeout-shaped zip with two photos, one sidecar with a people name."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Takeout/Google Photos/Sommer/IMG_1.jpg", make_jpeg(seed=101))
        zf.writestr("Takeout/Google Photos/Sommer/IMG_1.jpg.json", '{"photoTakenTime":{"timestamp":"1718380800"},"people":[{"name":"Anna Berg"}],"geoData":{"latitude":52.52,"longitude":13.405}}')
        zf.writestr("Takeout/Google Photos/Sommer/IMG_2.jpg", make_jpeg(seed=102))
    return buf.getvalue()


def test_takeout_import_lands_in_library_and_matches_event(host):
    data = _archive()
    r = host.post("/imports", json={"kind": "takeout", "filename": "takeout.zip", "size": len(data)})
    assert r.status_code == 201, r.text
    imp = r.json()
    up = imp["upload"]
    if up["mode"] == "single":
        requests.put(up["url"], data=data, headers=up.get("headers", {}), timeout=120)
        done = host.post(f"/imports/{imp['id']}/complete")
    else:
        etags = []
        ps = up["part_size"]
        for part in up["parts"]:
            chunk = data[(part["part_number"] - 1) * ps : part["part_number"] * ps]
            if not chunk:
                break
            pr = requests.put(part["url"], data=chunk, timeout=120)
            etags.append({"part_number": part["part_number"], "etag": pr.headers["ETag"]})
        done = host.post(f"/imports/{imp['id']}/complete", json={"parts": etags})
    assert done.status_code == 200, done.text
    final = wait_for(lambda: (lambda j: j if j["state"] in ("done", "failed") else None)(host.get(f"/imports/{imp['id']}").json()), timeout=180, every=2, what="import")
    assert final["state"] == "done", final
    assert final["stats"]["found"] == 2 and final["stats"]["imported"] == 2
    lib = host.get("/me/library").json()
    assert len(lib["items"]) >= 2
    sidecar_item = next(i for i in lib["items"] if i["captured_src"] == "sidecar")
    assert sidecar_item["captured_at"].startswith("2024-06-14")


def test_albums_and_public_share(event, host, guest):
    slug = event["slug"]
    items = [upload(guest, slug, f"alb{i}.jpg", make_jpeg(seed=200 + i)) for i in range(2)]
    for it in items:
        wait_for(lambda it=it: guest.get(f"/media/{it['id']}").json()["state"] == "ready", what="ready")
    alb = host.post("/albums", json={"event_slug": slug, "title": "Highlights", "media_ids": [i["id"] for i in items]}).json()
    assert alb["count"] == 2
    share = host.post(f"/albums/{alb['id']}/share", json={"allow_download": False}).json()
    public = requests.get(f"{BASE_URL}/api/v1/s/{share['share_id']}", timeout=30).json()
    assert public["title"] == "Highlights" and len(public["items"]) == 2 and public["allow_download"] is False
    html = requests.get(f"{BASE_URL}/s/{share['share_id']}", timeout=30).text
    assert "Highlights" in html and 'og:title' in html
    assert host.patch(f"/albums/{alb['id']}", json={"remove": [items[0]["id"]]}).json()["count"] == 1
    assert host.delete(f"/albums/{alb['id']}").status_code == 204


def test_years_and_recap(host, event):
    years = host.get("/me/years").json()["years"]
    assert isinstance(years, list)
    if years:
        recap = host.get(f"/me/years/{years[0]['year']}").json()
        assert set(recap) >= {"year", "moments", "events", "best_of_you", "top_people"}
