"""Tests for the user's taxonomy overlay.

Two things matter here and the rest is bookkeeping: the file has to be *sparse*
(so improving the shipped tables isn't blocked by a stale copy of them), and a
hand-edited file has to be survivable (so one typo costs that line, not the app).

Every test redirects ``taxonomy.path`` at a tmp file -- the real one lives beside
settings.ini in the repo root, and a test that wrote there would quietly change
how the developer's own library classifies.
"""

import json

import pytest

from conftest import seed_track
from vibenative import taxonomy


@pytest.fixture(autouse=True)
def tmp_overlay(tmp_path, monkeypatch):
    """The scratch overlay for this test.

    Driven by the env var rather than by patching ``taxonomy.path``: the client
    fixture re-imports the whole package, so a patched attribute would sit on a
    module object the app is no longer using -- which is exactly how the route
    test first went green against the developer's real file.
    """
    f = tmp_path / "taxonomy.json"
    monkeypatch.setenv("VIBE_TAXONOMY", str(f))
    taxonomy.load(force=True)
    yield f
    taxonomy.load(force=True)


def write(f, obj):
    f.write_text(json.dumps(obj), encoding="utf-8")
    taxonomy.load(force=True)


# --- the file itself ----------------------------------------------------------
def test_no_file_means_no_opinions():
    """The overlay is additive; its absence must be indistinguishable from a
    build that never had the feature."""
    assert taxonomy.load() == {
        "aliases": {},
        "archgenre": {},
        "family": {},
        "colors": {},
        "hidden": [],
        "order": [],
        "palette": "",
    }


def test_only_departures_are_written():
    """Sparse, not a copy: a full dump of the tables would freeze today's
    defaults and silently shadow every later fix to them."""
    f = taxonomy.path()
    taxonomy.save({"archgenre": {"Halftime": "Drum n Bass"}})
    body = json.loads(f.read_text(encoding="utf-8"))
    assert body == {"version": taxonomy.VERSION, "archgenre": {"Halftime": "Drum n Bass"}}


def test_saved_keys_are_sorted_so_diffs_stay_readable():
    taxonomy.save({"colors": {"Techno": "#0f0", "Ambient": "#00f", "House": "#f00"}})
    body = json.loads(taxonomy.path().read_text(encoding="utf-8"))
    assert list(body["colors"]) == ["Ambient", "House", "Techno"]


def test_edits_on_disk_are_picked_up_without_a_restart():
    """Hand-editing is a supported way to use this, so it has to re-read."""
    f = taxonomy.path()
    write(f, {"family": {"Industrial": "Bass"}})
    assert taxonomy.family_override("Industrial") == "Bass"
    write(f, {"family": {"Industrial": "Chill"}})
    assert taxonomy.family_override("Industrial") == "Chill"


def test_a_pinned_block_holds_one_overlay_for_its_whole_length():
    """A whole-library build classifies every track against the same file --
    and does not stat() it once per lookup to find that out."""
    f = taxonomy.path()
    write(f, {"family": {"Industrial": "Bass"}})
    with taxonomy.pinned():
        assert taxonomy.family_override("Industrial") == "Bass"
        f.write_text(json.dumps({"family": {"Industrial": "Chill"}}), encoding="utf-8")
        assert taxonomy.family_override("Industrial") == "Bass"  # held
    assert taxonomy.family_override("Industrial") == "Chill"  # released


# --- surviving a hand-edited file ---------------------------------------------
def test_a_broken_file_falls_back_instead_of_crashing():
    f = taxonomy.path()
    f.write_text("{ not json at all", encoding="utf-8")
    taxonomy.load(force=True)
    assert taxonomy.load()["aliases"] == {}


def test_junk_costs_only_the_line_it_is_on():
    """One bad entry must not discard the entries around it."""
    f = taxonomy.path()
    write(f, {"aliases": {"riddim": "Dubstep", "": "Techno", "  ": ""}, "nonsense": 5})
    assert taxonomy.load()["aliases"] == {"riddim": "Dubstep"}


def test_a_file_of_the_wrong_shape_is_survivable():
    f = taxonomy.path()
    write(f, ["not", "an", "object"])
    assert taxonomy.load()["aliases"] == {}


def test_unknown_keys_are_ignored_not_rejected():
    """A newer build's key must not make the file unloadable by an older one."""
    f = taxonomy.path()
    write(f, {"aliases": {"riddim": "Dubstep"}, "future_thing": {"a": 1}})
    assert taxonomy.alias_of("riddim") == "Dubstep"


def test_aliases_match_regardless_of_typed_case():
    f = taxonomy.path()
    write(f, {"aliases": {"Colour Bass": "Dubstep"}})
    assert taxonomy.alias_of("colour bass") == "Dubstep"
    assert taxonomy.alias_of("COLOUR BASS") == "Dubstep"


# --- patching -----------------------------------------------------------------
def test_patch_merges_rather_than_replacing():
    taxonomy.patch({"colors": {"House": "#f00"}})
    taxonomy.patch({"colors": {"Techno": "#0f0"}})
    assert taxonomy.load()["colors"] == {"House": "#f00", "Techno": "#0f0"}


def test_null_clears_an_entry_back_to_the_built_in_default():
    """Distinct from setting it to nothing -- "use the default" has to be
    expressible or an edit could never be taken back."""
    taxonomy.patch({"family": {"Industrial": "Bass"}})
    taxonomy.patch({"family": {"Industrial": None}})
    assert taxonomy.family_override("Industrial") is None


def test_lists_are_replaced_wholesale():
    taxonomy.patch({"hidden": ["Disco"]})
    taxonomy.patch({"hidden": ["Electro"]})
    assert taxonomy.hidden() == {"Electro"}


def test_reset_keeps_a_backup():
    """A mis-click on reset must be recoverable -- the same stance snapshots takes."""
    taxonomy.patch({"colors": {"House": "#f00"}})
    out = taxonomy.reset()
    assert taxonomy.load()["colors"] == {}
    assert out["backup"] and json.loads(open(out["backup"], encoding="utf-8").read())["colors"]


# --- what the overlay actually changes ----------------------------------------
def test_an_alias_outranks_the_built_in_tables():
    from vibenative import keystone as K

    assert K.keystone_of("juke") == "House"  # the shipped table
    write(taxonomy.path(), {"aliases": {"juke": "Drum n Bass"}})
    assert K.keystone_of("juke") == "Drum n Bass"


def test_an_alias_does_not_steal_a_name_from_another_parent():
    """Electronic---Hardcore is gabber, Rock---Hardcore is Black Flag. An overlay
    entry applying parent-blind would re-break exactly that."""
    from vibenative import keystone as K

    before = K.keystone_of("Rock---Hardcore")
    write(taxonomy.path(), {"aliases": {"hardcore": "Hard Dance"}})
    assert K.keystone_of("Rock---Hardcore") == before
    assert K.keystone_of("Electronic---Hardcore") == "Hard Dance"


def test_an_archgenre_can_be_reassigned():
    from vibenative import keystone as K

    assert K.archgenre_of("Halftime") == "Bass"
    write(taxonomy.path(), {"archgenre": {"Halftime": "Drum n Bass"}})
    assert K.archgenre_of("Halftime") == "Drum n Bass"


def test_a_keystone_can_be_promoted_to_stand_alone():
    """Empty string means "top of its own tree", which is a different statement
    from "no opinion" -- without the distinction nothing could be promoted."""
    from vibenative import keystone as K

    write(taxonomy.path(), {"archgenre": {"Dubstep": ""}})
    assert K.archgenre_of("Dubstep") == "Dubstep"


def test_a_family_can_be_reassigned():
    from vibenative import keystone as K

    assert K.family_of("Industrial") == "Experimental"
    write(taxonomy.path(), {"family": {"Industrial": "Bass"}})
    assert K.family_of("Industrial") == "Bass"


def test_a_colour_can_be_claimed_for_a_genre_the_solver_left_grey():
    """Only eight keystones won a hue; the rest are neutral. Claiming one for a
    genre that matters to you has to be allowed -- the separation guarantees
    palette.py solves for only bind those eight slots."""
    from vibenative import palette as P

    assert P.keystone_color("Trap", "dark") == P.NEUTRAL["dark"]
    write(taxonomy.path(), {"colors": {"Trap": "#ff00aa"}})
    assert P.keystone_color("Trap", "dark") == "#ff00aa"


def test_a_partial_ordering_leaves_the_rest_in_place():
    """ "I only care that Dubstep is first" has to be a writable thing."""
    from vibenative import keystone as K

    write(taxonomy.path(), {"order": ["Dubstep"]})
    got = K.archgenre_order()
    assert got[0] == "Dubstep"
    assert "House" in got and "Techno" in got
    assert len(got) == len(set(got))  # nothing duplicated by being named


# --- the HTTP surface ---------------------------------------------------------
def test_routes_round_trip(client):
    body = client.get("/taxonomy/overlay").get_json()
    assert body["overlay"]["archgenre"] == {}
    assert body["path"].endswith("taxonomy.json")  # hand-editing needs the location
    assert "House" in body["archgenres"]

    client.post("/taxonomy/overlay", json={"archgenre": {"Halftime": "Drum n Bass"}})
    assert client.get("/taxonomy/overlay").get_json()["overlay"]["archgenre"] == {
        "Halftime": "Drum n Bass"
    }

    assert client.post("/taxonomy/overlay", json=[]).status_code == 400
    assert client.post("/taxonomy/overlay/reset", json={}).status_code == 400  # needs the word
    assert client.post("/taxonomy/overlay/reset", json={"confirm": "RESET"}).status_code == 200
    assert client.get("/taxonomy/overlay").get_json()["overlay"]["archgenre"] == {}


def test_an_invented_archgenre_gets_a_place_in_the_order():
    """Moving a keystone under another keystone makes that one an archgenre. If
    the order doesn't know about it the group has nowhere to go -- and the first
    version of this dropped every track in it off the Genres tab."""
    from vibenative import keystone as K

    write(taxonomy.path(), {"archgenre": {"Halftime": "Drum n Bass"}})
    assert "Drum n Bass" in K.archgenre_order()


def test_no_group_can_fall_off_the_genres_tab(client):
    """The route must list every group it built, not only the ones the built-in
    order anticipated. Losing tracks silently is the worst failure here."""

    for h, style in (("t1", "Halftime"), ("t2", "Techno")):
        seed_track(h, {"salience": [{"style": style, "score": 1.0}]})

    def listed():
        body = client.get("/genres?by=archgenre&top=0").get_json()
        return {k["keystone"] for g in body for k in g["keystones"]}

    assert "Halftime" in listed()
    client.post("/taxonomy/overlay", json={"archgenre": {"Halftime": "Drum n Bass"}})
    assert "Halftime" in listed()
