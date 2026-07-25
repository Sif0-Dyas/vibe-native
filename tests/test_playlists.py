"""Saved (named) playlist CRUD — the /playlists surface added in the QOL sprint.

A playlist is just a name + a JSON list of tracks (the client decides what goes
in the list), so these need no audio: they exercise the DB-backed save/overwrite/
load/list/delete lifecycle and its edge cases directly. FAKE mode, throwaway DB
(see conftest.py).
"""

from contextlib import closing


def _rows(client):
    return client.get("/playlists").get_json()


def test_playlists_empty(client):
    r = client.get("/playlists")
    assert r.status_code == 200
    assert r.get_json() == []


def test_playlist_crud_lifecycle(client):
    # create -> the response echoes id/name/count
    r = client.post("/playlists", json={"name": "Warmup", "tracks": ["a", "b", "c"]})
    assert r.status_code == 200
    body = r.get_json()
    pid = body["id"]
    assert body["name"] == "Warmup" and body["count"] == 3

    # list -> one entry with the right count
    listed = _rows(client)
    assert len(listed) == 1
    assert listed[0]["id"] == pid and listed[0]["name"] == "Warmup" and listed[0]["count"] == 3

    # load -> the full track list comes back intact and in order
    got = client.get(f"/playlists/{pid}")
    assert got.status_code == 200
    assert got.get_json() == {"id": pid, "name": "Warmup", "tracks": ["a", "b", "c"]}

    # delete -> reported, and the row is gone
    d = client.post(f"/playlists/{pid}/delete")
    assert d.status_code == 200 and d.get_json()["deleted"] is True
    assert client.get(f"/playlists/{pid}").status_code == 404
    assert _rows(client) == []


def test_playlist_overwrite_by_name_keeps_one_row(client):
    # saving the same NAME again overwrites (ON CONFLICT(name)) rather than adding
    # a second row: same id, new track list, still exactly one playlist.
    first = client.post("/playlists", json={"name": "Set", "tracks": ["x"]}).get_json()
    second = client.post("/playlists", json={"name": "Set", "tracks": ["p", "q"]}).get_json()
    assert second["id"] == first["id"]  # same row, upserted
    assert second["count"] == 2

    listed = _rows(client)
    assert len(listed) == 1 and listed[0]["count"] == 2
    assert client.get(f"/playlists/{first['id']}").get_json()["tracks"] == ["p", "q"]


def test_playlist_save_validation(client):
    # name is required (missing, blank, or whitespace-only)
    assert client.post("/playlists", json={"tracks": []}).status_code == 400
    assert client.post("/playlists", json={"name": "  ", "tracks": []}).status_code == 400
    # tracks must be a list, not a string or a missing field
    assert client.post("/playlists", json={"name": "n"}).status_code == 400
    assert client.post("/playlists", json={"name": "n", "tracks": "nope"}).status_code == 400
    # an empty list IS valid -> a named-but-empty playlist (count 0)
    r = client.post("/playlists", json={"name": "Empty", "tracks": []})
    assert r.status_code == 200 and r.get_json()["count"] == 0


def test_playlist_get_not_found(client):
    assert client.get("/playlists/999999").status_code == 404


def test_playlist_delete_missing_is_soft(client):
    # deleting an id that doesn't exist is a harmless 200 with deleted=False
    # (the client treats it as already-gone), not a 404.
    r = client.post("/playlists/999999/delete")
    assert r.status_code == 200 and r.get_json()["deleted"] is False


def test_playlist_empty_count_survives_reload(client):
    # a 0-track playlist reads back as count 0 from the list endpoint too (the
    # count is derived from the stored JSON, which is an empty array).
    pid = client.post("/playlists", json={"name": "Z", "tracks": []}).get_json()["id"]
    from vibenative.db import _db_lock, db

    with _db_lock, closing(db()) as conn, conn as c:
        stored = c.execute("SELECT tracks FROM playlists WHERE id=?", (pid,)).fetchone()[0]
    assert stored == "[]"
    assert _rows(client)[0]["count"] == 0
