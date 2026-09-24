"""Tests for genre-state snapshots and the non-destructive reset.

Every test runs against a throwaway SQLite file and a temp snapshot directory,
so nothing here can touch the real library. The load-bearing property -- reset
loses nothing -- is tested by round-tripping: capture state, reset, restore,
assert the state came back byte-for-byte.
"""

import importlib
import json
import sqlite3

import pytest

SCHEMA = """
CREATE TABLE tracks(hash TEXT PRIMARY KEY, filename TEXT, filepath TEXT, title TEXT,
                    payload TEXT, embedding BLOB, created REAL);
CREATE TABLE training_labels(hash TEXT, genre TEXT, source TEXT, created REAL,
                             UNIQUE(hash, genre));
CREATE TABLE training_rejects(hash TEXT, genre TEXT, UNIQUE(hash, genre));
CREATE TABLE segment_overrides(hash TEXT, start_s REAL, end_s REAL, genre TEXT, created REAL);
"""


@pytest.fixture
def snap(tmp_path, monkeypatch):
    """A snapshots module bound to a scratch DB, head path and snapshot dir."""
    dbfile = tmp_path / "lib.db"
    con = sqlite3.connect(dbfile)
    con.executescript(SCHEMA)
    con.execute(
        "INSERT INTO tracks(hash,title,payload) VALUES (?,?,?)",
        ("h1", "Track One", json.dumps({"bpm": 174, "override": "Techno"})),
    )
    con.execute(
        "INSERT INTO tracks(hash,title,payload) VALUES (?,?,?)",
        ("h2", "Track Two", json.dumps({"bpm": 128, "salience": [{"style": "House", "score": 1}]})),
    )
    con.execute("INSERT INTO training_labels VALUES (?,?,?,?)", ("h2", "House", "manual", 1.0))
    con.execute("INSERT INTO training_rejects VALUES (?,?)", ("h1", "House"))
    con.commit()
    con.close()

    monkeypatch.setenv("GENRE_DB", str(dbfile))
    monkeypatch.setenv("VIBE_SNAPSHOTS", str(tmp_path / "snaps"))
    from vibenative import db as dbmod

    importlib.reload(dbmod)
    from vibenative import snapshots as S

    importlib.reload(S)
    monkeypatch.setattr(S, "CUSTOM_HEAD_PATH", tmp_path / "custom_head.npz")
    return S


def _state(S):
    return S._capture()


# --- the guard ----------------------------------------------------------------
@pytest.mark.parametrize("bad", ["", "reset", "Reset", "RESET ", None, "yes"])
def test_reset_refuses_without_the_exact_word(snap, bad):
    with pytest.raises(snap.ConfirmationRequired):
        snap.reset(bad)


def test_refused_reset_changes_nothing(snap):
    before = _state(snap)
    with pytest.raises(snap.ConfirmationRequired):
        snap.reset("nope")
    assert _state(snap) == before
    assert snap.list_all() == []


# --- snapshot -----------------------------------------------------------------
def test_create_records_what_it_captured(snap):
    meta = snap.create("checkpoint")
    assert meta["overrides"] == 1
    assert meta["rows"]["training_labels"] == 1
    assert meta["rows"]["training_rejects"] == 1
    assert meta["custom_head"] is False


def test_create_is_side_effect_free(snap):
    before = _state(snap)
    snap.create("checkpoint")
    assert _state(snap) == before


def test_list_is_newest_first_and_survives_a_corrupt_entry(snap):
    a = snap.create("first")
    b = snap.create("second")
    bad = snap.SNAPSHOT_DIR / "20200101-000000-broken"
    bad.mkdir(parents=True)
    (bad / "meta.json").write_text("{not json", encoding="utf-8")
    ids = [m["id"] for m in snap.list_all()]
    assert ids[0] == b["id"] and a["id"] in ids
    assert "20200101-000000-broken" not in ids


# --- reset --------------------------------------------------------------------
def test_reset_clears_live_state(snap):
    snap.reset("RESET")
    after = _state(snap)
    assert after["overrides"] == {}
    assert all(not v["rows"] for v in after["tables"].values())


def test_reset_leaves_the_tracks_themselves_alone(snap):
    """Analysis is not learned state -- resetting must not cost a re-scan."""
    snap.reset("RESET")
    with sqlite3.connect(snap.DB_PATH) as c:
        rows = dict(c.execute("SELECT hash, payload FROM tracks").fetchall())
    assert set(rows) == {"h1", "h2"}
    assert json.loads(rows["h1"])["bpm"] == 174  # analysis intact
    assert "override" not in json.loads(rows["h1"])  # only the learned bit went


def test_reset_snapshots_before_clearing(snap):
    res = snap.reset("RESET")
    assert res["snapshot"]["overrides"] == 1
    assert res["snapshot"]["id"] in [m["id"] for m in snap.list_all()]


def test_reset_moves_a_trained_head_aside_rather_than_deleting_it(snap):
    snap.CUSTOM_HEAD_PATH.write_bytes(b"weights")
    res = snap.reset("RESET")
    assert not snap.CUSTOM_HEAD_PATH.exists()
    moved = res["custom_head_moved_to"]
    assert moved and open(moved, "rb").read() == b"weights"


# --- the round trip -----------------------------------------------------------
def test_reset_then_restore_returns_everything(snap):
    before = _state(snap)
    res = snap.reset("RESET")
    assert _state(snap) != before
    snap.restore(res["snapshot"]["id"])
    assert _state(snap) == before


def test_restore_brings_back_a_trained_head(snap):
    snap.CUSTOM_HEAD_PATH.write_bytes(b"weights")
    res = snap.reset("RESET")
    snap.restore(res["snapshot"]["id"])
    assert snap.CUSTOM_HEAD_PATH.read_bytes() == b"weights"


def test_restore_is_itself_undoable(snap):
    """Restoring snapshots the current state first, so you're never stranded."""
    first = snap.create("original")
    snap.reset("RESET")
    mid = _state(snap)
    out = snap.restore(first["id"])
    assert _state(snap) != mid
    snap.restore(out["previous_state_saved_as"])
    assert _state(snap) == mid


def test_restore_skips_an_override_whose_track_is_gone(snap):
    snap_id = snap.create("has-h1")["id"]
    with sqlite3.connect(snap.DB_PATH) as c:
        c.execute("DELETE FROM tracks WHERE hash='h1'")
    snap.restore(snap_id)  # must not raise
    assert _state(snap)["overrides"] == {}


def test_restore_rejects_an_unknown_id(snap):
    with pytest.raises(FileNotFoundError):
        snap.restore("20990101-000000-nope")


def test_same_tick_snapshots_still_list_newest_first(snap, monkeypatch):
    """Windows' wall clock ticks every 15.6 ms, so two snapshots taken back to
    back record an identical `created` -- and a sort on that alone falls back to
    the filesystem's alphabetical order, putting "...-first" ahead of the newer
    "...-second". Freeze the clock so the tie is certain rather than 84% likely.
    """
    monkeypatch.setattr(snap.time, "time", lambda: 1_700_000_000.0)
    a = snap.create("first")
    b = snap.create("second")
    assert a["created"] == b["created"], "the clock was meant to be frozen"

    ids = [m["id"] for m in snap.list_all()]
    assert ids[:2] == [b["id"], a["id"]]


def test_snapshots_from_older_versions_still_list(snap):
    """Snapshots written before `seq` existed carry no such key; they must still
    sort (against each other and against new ones) instead of raising."""
    new = snap.create("new")
    old = snap.SNAPSHOT_DIR / "20200101-000000-legacy"
    old.mkdir(parents=True)
    (old / "meta.json").write_text(
        json.dumps({"id": old.name, "label": "legacy", "created": 1.0}), encoding="utf-8"
    )
    ids = [m["id"] for m in snap.list_all()]
    assert ids[0] == new["id"] and old.name in ids
