"""Vibe management + export/import — the vibe admin surface from the QOL sprint.

rename / reset / clear / delete and the export->import round-trip. These operate
on the vibe_tracks membership table by vibe_id and don't read embeddings, so they
use synthetic hashes (no audio needed) and assert the DB state after each op, not
just the HTTP code. FAKE mode, throwaway DB (see conftest.py).
"""

from contextlib import closing


def _members(vid):
    """{hash: weight} straight from the DB — assert stored state, not just HTTP."""
    from vibenative.db import _db_lock, db

    with _db_lock, closing(db()) as conn, conn as c:
        rows = c.execute("SELECT hash, weight FROM vibe_tracks WHERE vibe_id=?", (vid,)).fetchall()
    return {h: w for h, w in rows}


def _make_vibe(client, name, members=()):
    """Create a vibe and add (hash, weight) members via the real /vibes/add route."""
    vid = client.post("/vibes", json={"name": name}).get_json()["id"]
    for h, w in members:
        r = client.post("/vibes/add", json={"vibe_id": vid, "hash": h, "weight": w})
        assert r.status_code == 200
    return vid


# --- rename ------------------------------------------------------------------
def test_vibe_rename_success(client):
    vid = _make_vibe(client, "Old")
    r = client.post("/vibes/rename", json={"vibe_id": vid, "name": "New"})
    assert r.status_code == 200 and r.get_json()["name"] == "New"
    names = [v["name"] for v in client.get("/vibes").get_json()]
    assert "New" in names and "Old" not in names


def test_vibe_rename_collision_409(client):
    _make_vibe(client, "Alpha")
    vb = _make_vibe(client, "Beta")
    # renaming Beta onto the existing name Alpha collides (name is UNIQUE)
    r = client.post("/vibes/rename", json={"vibe_id": vb, "name": "Alpha"})
    assert r.status_code == 409
    # and Beta keeps its name (the failed UPDATE changed nothing)
    assert "Beta" in [v["name"] for v in client.get("/vibes").get_json()]


def test_vibe_rename_not_found_and_validation(client):
    assert client.post("/vibes/rename", json={"vibe_id": 999999, "name": "X"}).status_code == 404
    assert client.post("/vibes/rename", json={"name": "X"}).status_code == 400  # no id
    assert client.post("/vibes/rename", json={"vibe_id": 1}).status_code == 400  # no name
    assert client.post("/vibes/rename", json={"vibe_id": 1, "name": " "}).status_code == 400


# --- reset (weights back to 1.0) --------------------------------------------
def test_vibe_reset_restores_default_weights(client):
    vid = _make_vibe(client, "Tuned", [("h1", 0.5), ("h2", -0.3), ("h3", 1.0)])
    assert _members(vid) == {"h1": 0.5, "h2": -0.3, "h3": 1.0}

    r = client.post("/vibes/reset", json={"vibe_id": vid})
    assert r.status_code == 200 and r.get_json()["tracks"] == 3
    # every member kept, every weight back to 1.0
    assert _members(vid) == {"h1": 1.0, "h2": 1.0, "h3": 1.0}


def test_vibe_reset_validation(client):
    assert client.post("/vibes/reset", json={}).status_code == 400


# --- clear (drop members, keep the vibe) ------------------------------------
def test_vibe_clear_empties_membership_keeps_vibe(client):
    vid = _make_vibe(client, "Full", [("a", 1.0), ("b", 0.2)])
    r = client.post("/vibes/clear", json={"vibe_id": vid})
    assert r.status_code == 200 and r.get_json()["removed"] == 2
    # membership gone...
    assert _members(vid) == {}
    # ...but the vibe itself survives (now shows count 0)
    row = next(v for v in client.get("/vibes").get_json() if v["id"] == vid)
    assert row["count"] == 0


def test_vibe_clear_validation(client):
    assert client.post("/vibes/clear", json={}).status_code == 400


# --- delete (cascade to vibe_tracks, no orphans) ----------------------------
def test_vibe_delete_cascades_no_orphans(client):
    keep = _make_vibe(client, "Keep", [("k1", 1.0)])
    victim = _make_vibe(client, "Victim", [("v1", 1.0), ("v2", 0.4)])

    r = client.post("/vibes/delete", json={"vibe_id": victim})
    assert r.status_code == 200 and r.get_json()["deleted"] is True

    # the vibe is gone from the listing
    assert victim not in [v["id"] for v in client.get("/vibes").get_json()]
    # and it left NO orphan membership rows behind
    from vibenative.db import _db_lock, db

    with _db_lock, closing(db()) as conn, conn as c:
        orphans = c.execute(
            "SELECT COUNT(*) FROM vibe_tracks WHERE vibe_id=?", (victim,)
        ).fetchone()[0]
    assert orphans == 0
    # the other vibe's membership is untouched
    assert _members(keep) == {"k1": 1.0}


def test_vibe_delete_missing_is_soft(client):
    r = client.post("/vibes/delete", json={"vibe_id": 999999})
    assert r.status_code == 200 and r.get_json()["deleted"] is False


def test_vibe_delete_validation(client):
    assert client.post("/vibes/delete", json={}).status_code == 400


# --- export / import round-trip ---------------------------------------------
def _export(client):
    r = client.get("/vibes/export")
    assert r.status_code == 200
    return r.get_json()


def _normalize(export):
    """{vibe_name: {hash: weight}} for order-insensitive comparison."""
    return {v["name"]: {t["hash"]: t["weight"] for t in v["tracks"]} for v in export["vibes"]}


def test_vibe_export_shape(client):
    _make_vibe(client, "Peak", [("h1", 0.5), ("h2", -0.3)])
    exp = _export(client)
    assert exp["kind"] == "vibenative-vibes" and exp["version"] == 1
    assert _normalize(exp) == {"Peak": {"h1": 0.5, "h2": -0.3}}


def test_vibe_export_import_round_trip(client):
    # build two vibes with distinct weighted memberships
    _make_vibe(client, "Peak", [("h1", 0.5), ("h2", -0.3)])
    _make_vibe(client, "Chill", [("h3", 1.0)])
    before = _normalize(_export(client))

    exported = _export(client)
    # wipe every vibe (simulating a fresh DB) ...
    for v in client.get("/vibes").get_json():
        client.post("/vibes/delete", json={"vibe_id": v["id"]})
    assert client.get("/vibes").get_json() == []

    # ... then import the export back in
    r = client.post("/vibes/import", json=exported)
    assert r.status_code == 200
    body = r.get_json()
    assert body["created"] == 2 and body["merged"] == 0 and body["tracks"] == 3

    # membership + weights reconstructed exactly
    assert _normalize(_export(client)) == before


def test_vibe_import_merges_by_name(client):
    vid = _make_vibe(client, "M", [("h1", 1.0)])
    # importing a same-named vibe merges into it and upserts members
    payload = {"vibes": [{"name": "M", "tracks": [{"hash": "h2", "weight": 0.5}]}]}
    body = client.post("/vibes/import", json=payload).get_json()
    assert body["created"] == 0 and body["merged"] == 1 and body["tracks"] == 1
    assert _members(vid) == {"h1": 1.0, "h2": 0.5}


def test_vibe_import_clamps_and_defaults_weights(client):
    payload = {
        "vibes": [
            {
                "name": "W",
                "tracks": [
                    {"hash": "hi", "weight": 5},  # clamps to 1.0
                    {"hash": "lo", "weight": -9},  # clamps to -1.0
                    {"hash": "bad", "weight": "abc"},  # non-numeric -> default 1.0
                    {"hash": "def"},  # missing weight -> default 1.0
                ],
            }
        ]
    }
    assert client.post("/vibes/import", json=payload).status_code == 200
    vid = next(v["id"] for v in client.get("/vibes").get_json() if v["name"] == "W")
    assert _members(vid) == {"hi": 1.0, "lo": -1.0, "bad": 1.0, "def": 1.0}


def test_vibe_import_validates_shape(client):
    # top-level must be a 'vibes' LIST
    assert client.post("/vibes/import", json={}).status_code == 400
    assert client.post("/vibes/import", json={"vibes": "nope"}).status_code == 400
    assert client.post("/vibes/import", json={"vibes": {"name": "x"}}).status_code == 400


def test_vibe_import_skips_malformed_entries(client):
    # non-dict vibes, nameless vibes, non-dict tracks, and hash-less tracks are all
    # skipped gracefully rather than crashing or inserting junk.
    payload = {
        "vibes": [
            "not a dict",
            {"tracks": [{"hash": "orphan", "weight": 1.0}]},  # no name -> whole vibe skipped
            {"name": "  ", "tracks": []},  # blank name -> skipped
            {"name": "Good", "tracks": ["not a dict", {"weight": 1.0}, {"hash": "keep"}]},
        ]
    }
    body = client.post("/vibes/import", json=payload).get_json()
    assert body["created"] == 1 and body["tracks"] == 1  # only "Good" with its one valid track
    vid = next(v["id"] for v in client.get("/vibes").get_json() if v["name"] == "Good")
    assert _members(vid) == {"keep": 1.0}
    # the nameless vibe's "orphan" track was never stored
    from vibenative.db import _db_lock, db

    with _db_lock, closing(db()) as conn, conn as c:
        assert c.execute("SELECT COUNT(*) FROM vibe_tracks WHERE hash='orphan'").fetchone()[0] == 0
