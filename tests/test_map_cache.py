"""Tests for the /map response cache.

Building the map parses every payload in the library and classifies every track,
which on a real collection is seconds -- and it ran on every request, so opening
the app, switching to the Map tab and jumping to the playing track all waited for
the same answer to be recomputed.

The cache is keyed by a digest of everything the map is derived from, so these
tests are almost entirely about *invalidation*: a cache that is merely fast is
easy, and a map that quietly disagrees with the library is worse than a slow one.
Each test changes one input and asserts the map both rebuilds and comes back
different. The speed itself is not asserted -- it isn't a property of the code so
much as of the machine -- only that the second request is served from the store.
"""

import json

from vibenative import weights as W

REAL = [
    {"style": "Techno", "score": 0.7},
    {"style": "House", "score": 0.3},
]


def seed(client, h="mc1", payload=None):
    from vibenative.db import cache_put

    cache_put(h, f"{h}.mp3", "", h, payload or {"salience": REAL}, None)
    return h


def build(client):
    """One /map request: (was it a cache hit, the parsed body)."""
    r = client.get("/map")
    assert r.status_code == 200
    return r.headers.get("X-Map-Cache") == "hit", r.get_json()


def style_of(body, h):
    return next((n["style"] for n in body["nodes"] if n["hash"] == h), None)


# --- the cache itself ---------------------------------------------------------
def test_the_second_request_is_served_from_the_store(client):
    seed(client)
    hit1, first = build(client)
    hit2, second = build(client)
    assert hit1 is False        # nothing stored yet: this one built it
    assert hit2 is True
    assert first == second      # and a hit is the same map, not a similar one


def test_an_empty_library_still_answers(client):
    hit, body = build(client)
    assert hit is False
    assert body["nodes"] == []


# --- invalidation: every input that can change the map ------------------------
def test_a_new_track_rebuilds_the_map(client):
    seed(client, "mc1")
    build(client)
    assert build(client)[0] is True          # cached
    seed(client, "mc2")
    hit, body = build(client)
    assert hit is False
    assert {n["hash"] for n in body["nodes"]} == {"mc1", "mc2"}


def test_an_override_rebuilds_the_map(client):
    h = seed(client)
    build(client)
    client.post(f"/override/{h}", json={"genre": "Trance"})
    hit, body = build(client)
    assert hit is False
    assert style_of(body, h) == "Trance"


def test_a_weight_adjustment_rebuilds_the_map(client):
    h = seed(client)
    _, before = build(client)
    assert style_of(before, h) == "Techno"
    client.post(f"/weights/{h}", json={"steps": {"House": W.MAX_STEP}})
    hit, after = build(client)
    assert hit is False
    assert style_of(after, h) == "House"


def test_removing_a_genre_rebuilds_the_map(client):
    h = seed(client)
    build(client)
    client.post(f"/weights/{h}", json={"drops": ["Techno"]})
    hit, body = build(client)
    assert hit is False
    assert style_of(body, h) == "House"


def test_a_tag_change_rebuilds_the_map(client):
    """Tags ride on the node and drive the map's filters, so they are part of
    what the map is, not decoration on top of it. They also live in their own
    table, which is exactly the kind of input a fingerprint forgets."""
    h = seed(client)
    build(client)
    tag_id = client.post("/tags", json={"name": "peak time"}).get_json()["id"]
    assert client.post("/tags/toggle", json={"tag_id": tag_id, "hash": h}).status_code == 200

    hit, body = build(client)
    assert hit is False
    assert "peak time" in next(n for n in body["nodes"] if n["hash"] == h)["tags"]

    # Removing it again restores the library to exactly the state the first
    # build was made from, so this is a legitimate *hit* on that earlier entry --
    # the key describes the library, not the sequence of edits that led to it.
    # What matters is that the map it serves is the untagged one.
    client.post("/tags/toggle", json={"tag_id": tag_id, "hash": h})
    _, body = build(client)
    assert next(n for n in body["nodes"] if n["hash"] == h)["tags"] == []


def test_forgetting_a_track_rebuilds_the_map(client):
    seed(client, "mc1")
    seed(client, "mc2")
    build(client)
    client.post("/forget/mc2")
    hit, body = build(client)
    assert hit is False
    assert {n["hash"] for n in body["nodes"]} == {"mc1"}


def test_the_taxonomy_overlay_is_part_of_the_key(client):
    """The overlay decides how every genre resolves -- and carries the palette
    and the per-genre colours with it. Hand-editing the file has to reach the
    map, or the cache would make editing it look broken."""
    from vibenative.taxonomy import path as taxonomy_path

    seed(client)
    build(client)
    assert build(client)[0] is True

    overlay = taxonomy_path()          # the scratch path conftest points us at
    overlay.parent.mkdir(parents=True, exist_ok=True)
    overlay.write_text(json.dumps({"palette": "ember"}), encoding="utf-8")
    assert build(client)[0] is False


def test_the_two_render_modes_do_not_share_an_entry(client):
    """Light and dark differ in the palette steps they bake into every node."""
    seed(client)
    assert client.get("/map").headers.get("X-Map-Cache") == "miss"
    assert client.get("/map").headers.get("X-Map-Cache") == "hit"
    assert client.get("/map?mode=light").headers.get("X-Map-Cache") == "miss"
    assert client.get("/map?mode=light").headers.get("X-Map-Cache") == "hit"


# --- the cache must never be the reason the map fails -------------------------
def test_an_unreadable_cache_is_a_miss_not_a_failure(client, monkeypatch):
    """Losing the store costs speed. It must never cost the map."""
    from vibenative.routes import map as map_routes

    seed(client)
    build(client)
    monkeypatch.setattr(map_routes, "_map_cache_read", lambda fp: None)
    hit, body = build(client)
    assert hit is False
    assert len(body["nodes"]) == 1


def test_a_cache_that_cannot_be_written_still_serves_the_map(client, monkeypatch):
    from vibenative.routes import map as map_routes

    def boom(*a, **k):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(map_routes, "_map_cache_dir", boom)
    seed(client)
    r = client.get("/map")
    assert r.status_code == 200
    assert len(r.get_json()["nodes"]) == 1


def test_a_truncated_entry_is_rebuilt_rather_than_served(client):
    """The rename means this process cannot leave a half-written entry. Something
    else can -- a full disk, a crash mid-copy, a sync client -- and half a map is
    not a map. The byte length rides in the filename so that is detectable."""
    from vibenative.routes import map as map_routes

    h = seed(client)
    build(client)
    # The cache directory sits beside the database, and every test in this file
    # gets its own temp database in the same temp folder -- so pick out the entry
    # this test just wrote rather than assuming it is the only one there.
    stored = max(map_routes._map_cache_dir().glob("*.json"), key=lambda f: f.stat().st_mtime)
    stored.write_bytes(b'{"nodes": [')               # truncate it

    hit, body = build(client)
    assert hit is False                              # rejected, not served
    assert style_of(body, h) == "Techno"             # and rebuilt correctly
    assert build(client)[0] is True                  # the good entry replaced it
