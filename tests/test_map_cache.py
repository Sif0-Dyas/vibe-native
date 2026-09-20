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

from conftest import seed_track
from vibenative import weights as W

REAL = [
    {"style": "Techno", "score": 0.7},
    {"style": "House", "score": 0.3},
]


def seed(client, h="mc1", payload=None):
    return seed_track(h, payload or {"salience": REAL})


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


# --- the stamp: "is the map I am holding still the current one?" --------------
def test_the_stamp_matches_the_map_it_was_built_with(client):
    seed(client)
    _, body = build(client)
    assert body["stamp"] == client.get("/map/stamp").get_json()["stamp"]


def test_the_stamp_answers_the_same_on_a_cache_hit(client):
    """A hit serves the stored bytes, so the stamp inside them has to be the key
    that entry is filed under -- otherwise a cached map would report itself as
    something the stamp endpoint has never heard of, and the client would rebuild
    on every visit."""
    seed(client)
    build(client)
    hit, body = build(client)
    assert hit is True
    assert body["stamp"] == client.get("/map/stamp").get_json()["stamp"]


def test_the_stamp_moves_when_the_library_does(client):
    h = seed(client)
    before = client.get("/map/stamp").get_json()["stamp"]
    client.post(f"/override/{h}", json={"genre": "Trance"})
    assert client.get("/map/stamp").get_json()["stamp"] != before


def test_a_rating_leaves_the_stamp_alone(client):
    """The reason the endpoint exists. A rating writes to the library, so the
    client marks its map stale -- but ratings arrive as an overlay and no node is
    built from one, so the map it is holding is still exactly right. The stamp is
    what lets it find that out for a quarter of a second instead of a rebuild."""
    h = seed(client)
    before = client.get("/map/stamp").get_json()["stamp"]
    assert client.post(f"/ratings/{h}", json={"stars": 5}).status_code == 200
    assert client.get("/map/stamp").get_json()["stamp"] == before


def test_the_stamp_never_reads_a_track(client, monkeypatch):
    """The stamp is the library revision, not a digest of the rows: asking "is
    my map current" must cost the same on six thousand tracks as on six."""
    from vibenative.routes import map as M

    seed(client)
    calls = []
    real = M._map_fingerprint
    monkeypatch.setattr(M, "_map_fingerprint", lambda rev, mode: calls.append(rev) or real(rev, mode))
    assert client.get("/map/stamp").status_code == 200
    assert calls and isinstance(calls[0], int)


def test_the_node_carries_all_three_genre_tiers(client):
    """The popup names a track subgenre-first and widens from there, so every
    tier has to travel. Only the server has the taxonomy the wider two come out
    of -- the client cannot derive them."""
    h = seed(client, payload={"salience": [{"style": "Neurofunk", "score": 0.9}]})
    _, body = build(client)
    node = next(n for n in body["nodes"] if n["hash"] == h)
    assert node["ksub"] == "Neurofunk"
    assert node["klabel"] == "Drum n Bass"
    assert node["karch"] == "Bass"


def test_a_standalone_archgenre_repeats_rather_than_inventing_a_tier(client):
    """House is the top of its own tree. The node says so by naming House at both
    tiers; the popup drops the repeat. What it must not do is manufacture some
    wider grouping to fill the slot."""
    h = seed(client, payload={"salience": [{"style": "House", "score": 0.9}]})
    _, body = build(client)
    node = next(n for n in body["nodes"] if n["hash"] == h)
    assert node["ksub"] == node["klabel"] == node["karch"] == "House"


def test_a_track_the_taxonomy_cannot_place_still_carries_every_tier(client):
    """The client reads fields, not fallback chains, so every node has the whole
    shape. A style with no keystone is filed under itself, the way a standalone
    archgenre repeats its own name; a track with no read at all is "Other"."""
    h1 = seed(client, h="np1", payload={"salience": [{"style": "Spoken Word", "score": 0.9}]})
    h2 = seed(client, h="np2", payload={"styles": []})
    _, body = build(client)
    n1 = next(n for n in body["nodes"] if n["hash"] == h1)
    assert n1["keystones"] == ["Spoken Word"]
    assert n1["ksub"] == n1["klabel"] == n1["kkey"] == n1["karch"] == "Spoken Word"
    assert n1["family"] == "Other" and n1["rings"] == [] and n1["kfusion"] is False
    n2 = next(n for n in body["nodes"] if n["hash"] == h2)
    assert n2["keystones"] == ["Other"] and n2["klabel"] == "Other" and n2["ksub"] is None
    # ...and the shape is the same one a placed track carries.
    h3 = seed(client, h="np3")
    _, body = build(client)
    placed = next(n for n in body["nodes"] if n["hash"] == h3)
    assert placed["klabel"] == "Techno"
    assert set(placed) == set(n1) == set(n2)


def test_a_genre_is_not_a_subgenre_of_itself(client):
    """Plain-House tracks are counted on the keystone (self_count), not listed
    as a "House" subgenre of House -- every screen that consumed the list used
    to have to strip that row before "House > House" reached the user."""
    seed(client, h="sg1", payload={"salience": [{"style": "House", "score": 0.9}]})
    seed(client, h="sg2", payload={"salience": [{"style": "Progressive House", "score": 0.9}]})
    body = client.get("/genres?flat=1&top=0").get_json()
    house = next(g for g in body if g["keystone"] == "House")
    assert house["self_count"] == 1
    assert [s["style"] for s in house["subgenres"]] == ["Progressive House"]


def test_playable_means_the_file_is_actually_there(client, tmp_path):
    """A recorded path is not enough: an unplugged drive leaves thousands of
    tracks with a path and no file, and the "only tracks with audio" filter
    then hid nothing while every popup offered a play button that failed."""
    from vibenative.db import cache_put

    real = tmp_path / "real.wav"
    real.write_bytes(b"RIFF")
    cache_put("pa1", "real.wav", str(real), "real", {"salience": REAL}, None)
    cache_put("pa2", "gone.wav", str(tmp_path / "gone.wav"), "gone", {"salience": REAL}, None)
    cache_put("pa3", "drop.wav", "", "dropped", {"salience": REAL}, None)
    _, body = build(client)
    a = {n["hash"]: n["a"] for n in body["nodes"]}
    assert (a["pa1"], a["pa2"], a["pa3"]) == (1, 0, 0)
