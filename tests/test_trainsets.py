"""Tests for per-genre training sets.

Training goes wrong locally -- one genre gets fed the wrong tracks and starts
skewing while the rest are fine -- so the property that matters most is that
every operation is scoped to ONE genre and cannot touch another's work. That
gets the most tests here.

Real files on disk, because export hashes actual bytes.
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
"""

INSERT_TRACK = (
    "INSERT INTO tracks(hash,filename,filepath,title,payload,embedding,created)"
    " VALUES(?,?,?,?,'{}',NULL,0)"
)


@pytest.fixture
def ts(tmp_path, monkeypatch):
    dbfile = tmp_path / "lib.db"
    con = sqlite3.connect(dbfile)
    con.executescript(SCHEMA)
    con.commit()
    con.close()
    monkeypatch.setenv("GENRE_DB", str(dbfile))
    from vibenative import db as dbmod

    importlib.reload(dbmod)
    from vibenative import trainsets

    monkeypatch.setattr(trainsets, "db", dbmod.db)
    monkeypatch.setattr(trainsets, "_db_lock", dbmod._db_lock)
    monkeypatch.setattr(trainsets, "ROOT", tmp_path / "genre_training")
    monkeypatch.setattr(trainsets, "ARCHIVE", tmp_path / "genre_training" / "_archive")
    trainsets._DB = dbfile
    return trainsets


def put_file(ts, genre, name, content):
    d = ts.folder(genre)
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(content)
    return d / name


def add_track(ts, h, path="", title="t"):
    with sqlite3.connect(ts._DB) as c:
        c.execute(INSERT_TRACK, (h, title + ".mp3", path, title))


def label(ts, h, genre):
    with sqlite3.connect(ts._DB) as c:
        c.execute("INSERT INTO training_labels VALUES(?,?,?,0)", (h, genre, "manual"))


# --- scoping: the property that matters ---------------------------------------
def test_reset_touches_only_the_named_genre(ts):
    put_file(ts, "Dubstep", "a.mp3", b"aa")
    put_file(ts, "Techno", "b.mp3", b"bb")
    label(ts, "h1", "Dubstep")
    label(ts, "h2", "Techno")
    ts.reset("Dubstep")
    assert not ts.folder("Dubstep").exists()
    assert ts.folder("Techno").exists()  # untouched
    with sqlite3.connect(ts._DB) as c:
        left = [r[0] for r in c.execute("SELECT genre FROM training_labels")]
    assert left == ["Techno"]


def test_reset_archives_rather_than_deletes(ts):
    from pathlib import Path

    f = put_file(ts, "Dubstep", "keep.mp3", b"precious")
    out = ts.reset("Dubstep")
    assert out["archived_to"]
    archived = Path(out["archived_to"]) / "keep.mp3"
    assert archived.is_file() and archived.read_bytes() == b"precious"
    assert not f.exists()


def test_reset_of_an_empty_genre_is_harmless(ts):
    out = ts.reset("Never Trained")
    assert out["archived_to"] is None
    assert out["labels_cleared"] == 0


def test_reset_rejects_a_nonsense_name(ts):
    with pytest.raises(ValueError):
        ts.reset("///")


# --- export -------------------------------------------------------------------
def test_export_hashes_the_folder_not_just_the_label_table(ts):
    """/override copies audio into the folder without writing a label row, so a
    genre trained purely by overriding has files and zero labels. Exporting from
    the table alone produced a manifest that restored nothing."""
    put_file(ts, "Dubstep", "a.mp3", b"unique-a")
    put_file(ts, "Dubstep", "b.mp3", b"unique-b")
    m = ts.export("Dubstep")
    assert len(m["labels"]) == 2
    assert all(e["hash"] for e in m["labels"])
    assert {e["source"] for e in m["labels"]} == {"folder"}


def test_export_merges_folder_and_table_without_duplicates(ts):
    from vibenative.db import file_hash

    f = put_file(ts, "Dubstep", "a.mp3", b"unique-a")
    label(ts, file_hash(f), "Dubstep")  # same track, reachable both ways
    label(ts, "table-only", "Dubstep")
    m = ts.export("Dubstep")
    hashes = [e["hash"] for e in m["labels"]]
    assert len(hashes) == len(set(hashes)) == 2


def test_export_skips_applesidecars(ts):
    put_file(ts, "Dubstep", "a.mp3", b"real")
    put_file(ts, "Dubstep", "._a.mp3", b"junk")
    assert len(ts.export("Dubstep")["labels"]) == 1


# --- import -------------------------------------------------------------------
def test_import_restores_labels_and_copies_audio(ts, tmp_path):
    from vibenative.db import file_hash

    src = tmp_path / "music" / "song.mp3"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"the-audio")
    h = file_hash(src)
    add_track(ts, h, str(src))
    out = ts.import_({"genre": "Dubstep", "labels": [{"hash": h}]})
    assert out["labels_added"] == 1
    assert out["audio_copied"] == 1
    assert out["trainable"] is True
    assert (ts.folder("Dubstep") / "song.mp3").read_bytes() == b"the-audio"


def test_import_flags_labels_it_cannot_make_trainable(ts):
    """train_head.py reads the folders. A track with no stored path can be
    labelled but not copied, so the import looks fine and teaches nothing."""
    add_track(ts, "h1", "")  # analysed by drag-and-drop
    out = ts.import_({"genre": "Dubstep", "labels": [{"hash": "h1"}]})
    assert out["labels_added"] == 1
    assert out["audio_copied"] == 0
    assert out["known_but_no_audio"] == 1
    assert out["trainable"] is False


def test_import_reports_tracks_the_library_does_not_have(ts):
    out = ts.import_({"genre": "Dubstep", "labels": [{"hash": "nope"}]})
    assert out["missing_from_library"] == 1
    assert out["labels_added"] == 0


def test_import_merges_and_is_idempotent(ts, tmp_path):
    from vibenative.db import file_hash

    src = tmp_path / "s.mp3"
    src.write_bytes(b"x")
    h = file_hash(src)
    add_track(ts, h, str(src))
    man = {"genre": "Dubstep", "labels": [{"hash": h}]}
    ts.import_(man)
    ts.import_(man)  # twice must not duplicate
    with sqlite3.connect(ts._DB) as c:
        assert c.execute("SELECT COUNT(*) FROM training_labels").fetchone()[0] == 1


def test_import_can_retarget_a_manifest_to_another_genre(ts, tmp_path):
    from vibenative.db import file_hash

    src = tmp_path / "s.mp3"
    src.write_bytes(b"x")
    h = file_hash(src)
    add_track(ts, h, str(src))
    ts.import_({"genre": "Dubstep", "labels": [{"hash": h}]}, genre="Riddim")
    with sqlite3.connect(ts._DB) as c:
        assert c.execute("SELECT genre FROM training_labels").fetchone()[0] == "Riddim"


def test_import_rejects_junk(ts):
    with pytest.raises(ValueError):
        ts.import_("not a manifest")
    with pytest.raises(ValueError):
        ts.import_({"labels": []})  # no genre anywhere


# --- round trip ---------------------------------------------------------------
def test_export_import_round_trip_survives_a_reset(ts, tmp_path):
    from vibenative.db import file_hash

    src = tmp_path / "music" / "song.mp3"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"audio-bytes")
    h = file_hash(src)
    add_track(ts, h, str(src))
    put_file(ts, "Dubstep", "song.mp3", b"audio-bytes")

    manifest = json.loads(json.dumps(ts.export("Dubstep")))  # as it would be saved
    ts.reset("Dubstep")
    assert ts.detail("Dubstep")["files"] == 0

    ts.import_(manifest)
    assert ts.detail("Dubstep")["files"] == 1
