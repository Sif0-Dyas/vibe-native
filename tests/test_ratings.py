"""Tests for ratings and the Rekordbox export.

The export encoding is the part that fails silently: a wrong Rating value or a
malformed Location imports into Rekordbox as "no stars" or "file missing" with no
error anywhere. So the XML is asserted structurally here rather than eyeballed.

Storage tests run against a scratch database; the XML builder is pure and needs
no database at all.
"""

import importlib
import sqlite3
from xml.etree import ElementTree as ET

import pytest

from vibenative import ratings

SCHEMA = """
CREATE TABLE tracks(hash TEXT PRIMARY KEY, filename TEXT, filepath TEXT, title TEXT,
                    payload TEXT, embedding BLOB, created REAL);
CREATE TABLE ratings(hash TEXT PRIMARY KEY, stars INTEGER DEFAULT 0,
                     grade TEXT DEFAULT '', note TEXT DEFAULT '', updated REAL);
"""


@pytest.fixture
def rt(tmp_path, monkeypatch):
    """ratings module bound to a scratch database."""
    dbfile = tmp_path / "lib.db"
    con = sqlite3.connect(dbfile)
    con.executescript(SCHEMA)
    con.commit()
    con.close()
    monkeypatch.setenv("GENRE_DB", str(dbfile))
    from vibenative import db as dbmod

    # Only db is reloaded: reload() updates the module's dict in place, so the
    # new DB_PATH is visible to db(), which reads it at call time. Reloading
    # ratings as well is not just redundant -- it fails outright once another
    # test has dropped modules from sys.modules, which reload() requires.
    importlib.reload(dbmod)
    monkeypatch.setattr(ratings, "db", dbmod.db)
    monkeypatch.setattr(ratings, "_db_lock", dbmod._db_lock)
    return ratings


# --- storage ------------------------------------------------------------------
def test_unrated_track_reads_as_empty_not_missing(rt):
    r = rt.get("nope")
    assert r == {"hash": "nope", "stars": 0, "grade": "", "note": ""}


def test_round_trip(rt):
    rt.put("h1", stars=4, grade="a", note="peak time")
    r = rt.get("h1")
    assert r["stars"] == 4
    assert r["grade"] == "A"  # normalised to upper
    assert r["note"] == "peak time"


def test_partial_update_leaves_other_fields_alone(rt):
    """The map sets stars, the library view sets the note -- neither may wipe the
    other, or ratings quietly disappear depending on where you edit them."""
    rt.put("h1", stars=5, grade="A", note="keep me")
    rt.put("h1", stars=3)
    r = rt.get("h1")
    assert r["stars"] == 3 and r["grade"] == "A" and r["note"] == "keep me"


@pytest.mark.parametrize("given,expect", [(-4, 0), (0, 0), (5, 5), (9, 5), ("3", 3), (None, 0)])
def test_stars_are_clamped(rt, given, expect):
    rt.put("h1", stars=given)
    assert rt.get("h1")["stars"] == expect


def test_junk_stars_do_not_raise(rt):
    rt.put("h1", stars="banana")
    assert rt.get("h1")["stars"] == 0


def test_note_is_length_capped(rt):
    rt.put("h1", note="x" * 5000)
    assert len(rt.get("h1")["note"]) == rt.MAX_NOTE


def test_get_many_is_keyed_by_hash_and_skips_unrated(rt):
    rt.put("a", stars=1)
    rt.put("b", stars=2)
    out = rt.get_many(["a", "b", "never-rated"])
    assert set(out) == {"a", "b"}
    assert out["b"]["stars"] == 2


def test_get_many_handles_more_than_the_sqlite_variable_limit(rt):
    for i in range(1200):
        rt.put(f"h{i}", stars=1)
    assert len(rt.get_many([f"h{i}" for i in range(1200)])) == 1200


def test_get_many_empty(rt):
    assert rt.get_many([]) == {}


# --- the comment field --------------------------------------------------------
@pytest.mark.parametrize(
    "grade,note,expect",
    [
        ("A", "big room", "A - big room"),
        ("A", "", "A"),
        ("", "just a note", "just a note"),
        ("", "", ""),
        ("B", "   spaced   ", "B - spaced"),
    ],
)
def test_comment_never_leaves_a_dangling_separator(grade, note, expect):
    assert ratings.comment_for({"grade": grade, "note": note}) == expect


# --- Rekordbox XML ------------------------------------------------------------
def _xml(tracks, rmap=None, name="Set"):
    return ET.fromstring(ratings.playlist_xml(name, tracks, rmap or {}))


TRACK = {
    "hash": "h1",
    "title": "Leaders",
    "artist": "Someone",
    "filepath": r"C:\Music\Leaders.mp3",
    "bpm": 174.0,
    "key": "Am",
    "duration": 312.4,
}


def test_xml_is_well_formed_and_has_both_required_sections():
    """A playlist node without a COLLECTION imports as empty."""
    root = _xml([TRACK])
    assert root.tag == "DJ_PLAYLISTS"
    assert root.find("COLLECTION") is not None
    assert root.find("PLAYLISTS") is not None


@pytest.mark.parametrize(
    "stars,rb", [(0, "0"), (1, "51"), (2, "102"), (3, "153"), (4, "204"), (5, "255")]
)
def test_stars_map_onto_rekordbox_51_point_steps(stars, rb):
    """Rekordbox ignores Rating values off this ladder -- 1-5 would import as
    unrated, which looks like the export simply didn't carry ratings."""
    root = _xml([TRACK], {"h1": {"stars": stars, "grade": "", "note": ""}})
    assert root.find("COLLECTION/TRACK").get("Rating") == rb


def test_grade_and_note_land_in_comments():
    root = _xml([TRACK], {"h1": {"stars": 4, "grade": "A", "note": "peak time"}})
    assert root.find("COLLECTION/TRACK").get("Comments") == "A - peak time"


def test_no_comments_attribute_when_there_is_nothing_to_say():
    root = _xml([TRACK], {"h1": {"stars": 3, "grade": "", "note": ""}})
    assert root.find("COLLECTION/TRACK").get("Comments") is None


def test_unrated_track_still_exports_with_zero_rating():
    root = _xml([TRACK])
    assert root.find("COLLECTION/TRACK").get("Rating") == "0"


def test_location_is_a_file_url_rekordbox_accepts():
    """Backslashes and a missing host make Rekordbox treat the track as missing."""
    loc = _xml([TRACK]).find("COLLECTION/TRACK").get("Location")
    assert loc.startswith("file://localhost/")
    assert "\\" not in loc
    assert loc.endswith("/C:/Music/Leaders.mp3")


def test_location_percent_encodes_spaces_and_specials():
    t = dict(TRACK, filepath=r"C:\My Music\track #1 & more.mp3")
    loc = _xml([t]).find("COLLECTION/TRACK").get("Location")
    assert " " not in loc and "%20" in loc
    assert "#" not in loc and "&" not in loc


def test_quotes_in_metadata_do_not_break_the_document():
    """A title with a quote must escape, not truncate the attribute."""
    t = dict(TRACK, title='He said "hi" & <left>')
    root = _xml([t])
    assert root.find("COLLECTION/TRACK").get("Name") == 'He said "hi" & <left>'


def test_playlist_references_every_collection_track():
    tracks = [dict(TRACK, hash=f"h{i}", title=f"T{i}") for i in range(4)]
    root = _xml(tracks)
    ids = [t.get("TrackID") for t in root.findall("COLLECTION/TRACK")]
    keys = [t.get("Key") for t in root.findall("PLAYLISTS/NODE/NODE/TRACK")]
    assert ids == keys == ["1", "2", "3", "4"]
    assert root.find("COLLECTION").get("Entries") == "4"


def test_empty_playlist_is_still_valid_xml():
    root = _xml([])
    assert root.find("COLLECTION").get("Entries") == "0"


def test_optional_fields_are_omitted_not_blank():
    """A track with no BPM shouldn't export AverageBpm="" -- Rekordbox reads that
    as a zero tempo rather than 'unknown'."""
    t = {"hash": "h1", "title": "x", "artist": "", "filepath": "C:/a.mp3"}
    tr = _xml([t]).find("COLLECTION/TRACK")
    assert tr.get("AverageBpm") is None
    assert tr.get("Tonality") is None
    assert tr.get("TotalTime") is None


def test_tracks_without_a_filepath_are_skipped_not_exported_broken():
    """Rekordbox locates audio by path. A row with no Location imports as a
    permanently missing file, which reads as a successful import -- worse than
    an honest omission. 81% of this library has no stored path."""
    tracks = [TRACK, {"hash": "h2", "title": "No Path", "artist": "", "filepath": ""}]
    root = _xml(tracks)
    names = [t.get("Name") for t in root.findall("COLLECTION/TRACK")]
    assert names == ["Leaders"]
    assert root.find("COLLECTION").get("Entries") == "1"


def test_skipped_count_is_recorded_in_the_document():
    tracks = [
        TRACK,
        {"hash": "h2", "title": "x", "filepath": ""},
        {"hash": "h3", "title": "y", "filepath": None},
    ]
    xml = ratings.playlist_xml("Set", tracks, {})
    assert "2 track(s) omitted" in xml


def test_no_skip_comment_when_everything_exports():
    assert "omitted" not in ratings.playlist_xml("Set", [TRACK], {})


def test_ids_stay_contiguous_after_skipping():
    """TrackID/Key must still line up, or the playlist references dangle."""
    tracks = [
        TRACK,
        {"hash": "h2", "title": "skip", "filepath": ""},
        dict(TRACK, hash="h3", title="Third"),
    ]
    root = _xml(tracks)
    ids = [t.get("TrackID") for t in root.findall("COLLECTION/TRACK")]
    keys = [t.get("Key") for t in root.findall("PLAYLISTS/NODE/NODE/TRACK")]
    assert ids == keys == ["1", "2"]
