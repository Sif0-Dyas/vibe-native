"""Tag routes — /tags create, list-with-counts, toggle on/off, and tags-for-track.

Tags attach to tracks by (tag_id, hash), so these need no audio: synthetic hashes
exercise the membership directly and assert the DB state after toggles. Closes the
coverage gap the routes/library.py split made visible (tags was the thinnest-tested
module). FAKE mode, throwaway DB (see conftest.py).
"""

from contextlib import closing


def _mktag(client, name):
    r = client.post("/tags", json={"name": name})
    assert r.status_code == 200
    return r.get_json()["id"]


def _link_count(tid, h):
    """track_tags rows for (tag, hash) straight from the DB — assert stored state."""
    from vibenative.db import _db_lock, db

    with _db_lock, closing(db()) as conn, conn as c:
        return c.execute(
            "SELECT COUNT(*) FROM track_tags WHERE tag_id=? AND hash=?", (tid, h)
        ).fetchone()[0]


# --- create ------------------------------------------------------------------
def test_tag_create_new(client):
    r = client.post("/tags", json={"name": "High Energy"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["name"] == "High Energy" and isinstance(body["id"], int)


def test_tag_create_duplicate_is_idempotent(client):
    first = _mktag(client, "Opener")
    # same name again returns the SAME id and adds no second row
    again = client.post("/tags", json={"name": "Opener"}).get_json()
    assert again["id"] == first
    assert len([t for t in client.get("/tags").get_json() if t["name"] == "Opener"]) == 1


def test_tag_create_validation(client):
    assert client.post("/tags", json={}).status_code == 400
    assert client.post("/tags", json={"name": "  "}).status_code == 400
    # surrounding whitespace on a real name is stripped
    assert client.post("/tags", json={"name": "  Closer  "}).get_json()["name"] == "Closer"


# --- toggle ------------------------------------------------------------------
def test_tag_toggle_on_then_off(client):
    tid = _mktag(client, "Peak")
    h = "trackhash1"
    on = client.post("/tags/toggle", json={"tag_id": tid, "hash": h})
    assert on.status_code == 200 and on.get_json()["tagged"] is True
    assert _link_count(tid, h) == 1  # attached
    off = client.post("/tags/toggle", json={"tag_id": tid, "hash": h})
    assert off.get_json()["tagged"] is False
    assert _link_count(tid, h) == 0  # removed


def test_tag_toggle_validation(client):
    assert client.post("/tags/toggle", json={}).status_code == 400
    assert client.post("/tags/toggle", json={"tag_id": 1}).status_code == 400  # no hash
    assert client.post("/tags/toggle", json={"hash": "x"}).status_code == 400  # no tag_id


# --- tags for a track --------------------------------------------------------
def test_tags_for_track_ordered(client):
    h = "trackhashA"
    zeta = _mktag(client, "Zeta")  # created out of alpha order on purpose
    alpha = _mktag(client, "Alpha")
    client.post("/tags/toggle", json={"tag_id": zeta, "hash": h})
    client.post("/tags/toggle", json={"tag_id": alpha, "hash": h})

    rows = client.get(f"/tags/for/{h}").get_json()
    assert [t["name"] for t in rows] == ["Alpha", "Zeta"]  # ORDER BY t.name
    assert {t["id"] for t in rows} == {zeta, alpha}


def test_tags_for_track_none(client):
    _mktag(client, "Unused")  # a tag exists but is attached to no track
    assert client.get("/tags/for/nobody").get_json() == []


# --- list with counts --------------------------------------------------------
def test_tags_list_counts_and_order(client):
    bass = _mktag(client, "Bass")  # 2 tracks
    _mktag(client, "Ambient")  # 0 tracks -> LEFT JOIN still lists it, count 0
    for h in ("h1", "h2"):
        client.post("/tags/toggle", json={"tag_id": bass, "hash": h})

    listed = client.get("/tags").get_json()
    by_name = {t["name"]: t for t in listed}
    assert by_name["Bass"]["count"] == 2
    assert by_name["Ambient"]["count"] == 0  # tag with no tracks still appears
    assert [t["name"] for t in listed] == sorted(t["name"] for t in listed)  # ORDER BY name
