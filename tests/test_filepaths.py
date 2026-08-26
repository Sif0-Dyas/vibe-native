"""Tests for the file-path audit and repair.

Repair reconnects analysed tracks to audio by content hash. The risky part is
what it's allowed to *overwrite*: pointed at a folder of duplicates it must not
silently repoint a healthy library at the copies. That property gets the most
tests here.

Real files on disk (tiny ones) rather than mocks, because the whole point is
hashing actual bytes.
"""

import importlib
import sqlite3

import pytest

SCHEMA = """
CREATE TABLE tracks(hash TEXT PRIMARY KEY, filename TEXT, filepath TEXT, title TEXT,
                    payload TEXT, embedding BLOB, created REAL);
"""


@pytest.fixture
def fp(tmp_path, monkeypatch):
    dbfile = tmp_path / "lib.db"
    con = sqlite3.connect(dbfile)
    con.executescript(SCHEMA)
    con.commit()
    con.close()
    monkeypatch.setenv("GENRE_DB", str(dbfile))
    from vibenative import db as dbmod

    importlib.reload(dbmod)
    from vibenative import filepaths

    monkeypatch.setattr(filepaths, "db", dbmod.db)
    monkeypatch.setattr(filepaths, "_db_lock", dbmod._db_lock)
    monkeypatch.setattr(filepaths, "file_hash", dbmod.file_hash)
    filepaths._DB = dbfile
    return filepaths


def make_audio(folder, name, content=b"ID3fake-audio-bytes"):
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    p.write_bytes(content)
    return p


def add_track(fp, h, path="", title="t"):
    with sqlite3.connect(fp._DB) as c:
        c.execute(
            "INSERT INTO tracks(hash,filename,filepath,title,payload,embedding,created)"
            " VALUES(?,?,?,?,'{}',NULL,0)",
            (h, f"{title}.mp3", path, title),
        )


def path_of(fp, h):
    with sqlite3.connect(fp._DB) as c:
        return c.execute("SELECT filepath FROM tracks WHERE hash=?", (h,)).fetchone()[0]


# --- audit --------------------------------------------------------------------
def test_audit_separates_missing_broken_and_ok(fp, tmp_path):
    real = make_audio(tmp_path / "music", "a.mp3")
    add_track(fp, "h_ok", str(real), "OK")
    add_track(fp, "h_broken", str(tmp_path / "gone" / "x.mp3"), "Broken")
    add_track(fp, "h_missing", "", "NoPath")
    a = fp.audit()
    assert (a["total"], a["ok"], a["broken"], a["missing"]) == (3, 1, 1, 1)
    assert a["broken_examples"][0]["title"] == "Broken"
    assert a["missing_examples"][0]["title"] == "NoPath"


def test_audit_can_skip_the_existence_check(fp, tmp_path):
    """On a detached drive, stat()ing every track stalls and reports everything
    broken -- the caller needs to be able to opt out."""
    add_track(fp, "h1", str(tmp_path / "nowhere" / "x.mp3"))
    assert fp.audit(check_exists=True)["broken"] == 1
    assert fp.audit(check_exists=False)["broken"] == 0


# --- scanning -----------------------------------------------------------------
def test_scan_skips_non_audio_and_applesidecars(fp, tmp_path):
    d = tmp_path / "m"
    make_audio(d, "real.mp3")
    make_audio(d, "._real.mp3")  # AppleDouble stub
    make_audio(d, "notes.txt")
    out = fp.scan_folder(d)
    assert out["scanned"] == 1
    assert len(out["found"]) == 1


def test_scan_rejects_a_non_directory(fp, tmp_path):
    with pytest.raises(NotADirectoryError):
        fp.scan_folder(tmp_path / "does-not-exist")


# --- repair -------------------------------------------------------------------
def test_repair_fills_a_missing_path(fp, tmp_path):
    f = make_audio(tmp_path / "m", "song.mp3", b"unique-bytes-1")
    h = fp.file_hash(f)
    add_track(fp, h, "")
    out = fp.repair(tmp_path / "m", dry_run=False)
    assert out["filled"] == 1
    assert path_of(fp, h) == str(f)


def test_dry_run_writes_nothing(fp, tmp_path):
    f = make_audio(tmp_path / "m", "song.mp3", b"unique-bytes-2")
    h = fp.file_hash(f)
    add_track(fp, h, "")
    out = fp.repair(tmp_path / "m", dry_run=True)
    assert out["filled"] == 1  # reports what it *would* do
    assert path_of(fp, h) == ""  # ...but changed nothing


def test_repair_repoints_a_broken_path(fp, tmp_path):
    f = make_audio(tmp_path / "new", "moved.mp3", b"unique-bytes-3")
    h = fp.file_hash(f)
    add_track(fp, h, str(tmp_path / "old" / "moved.mp3"))  # file no longer there
    out = fp.repair(tmp_path / "new", dry_run=False)
    assert out["repointed"] == 1
    assert path_of(fp, h) == str(f)


def test_repair_never_repoints_a_healthy_path(fp, tmp_path):
    """Pointed at a folder of duplicates, a working library must not be moved
    onto the copies."""
    original = make_audio(tmp_path / "library", "song.mp3", b"same-bytes")
    duplicate = make_audio(tmp_path / "backup", "song.mp3", b"same-bytes")
    h = fp.file_hash(original)
    add_track(fp, h, str(original))
    out = fp.repair(tmp_path / "backup", dry_run=False)
    assert out["filled"] == 0 and out["repointed"] == 0
    assert out["already_ok"] == 1
    assert path_of(fp, h) == str(original)  # untouched
    assert path_of(fp, h) != str(duplicate)


def test_repair_ignores_files_that_are_not_in_the_library(fp, tmp_path):
    make_audio(tmp_path / "m", "unknown.mp3", b"never-analysed")
    out = fp.repair(tmp_path / "m", dry_run=False)
    assert out["filled"] == 0
    assert out["unanalysed_files"] == 1


def test_repair_matches_a_renamed_file(fp, tmp_path):
    """Matching is by content hash, so the filename is irrelevant."""
    f = make_audio(tmp_path / "m", "totally-different-name.mp3", b"unique-bytes-4")
    h = fp.file_hash(f)
    add_track(fp, h, "", title="Original Name")
    out = fp.repair(tmp_path / "m", dry_run=False)
    assert out["filled"] == 1
    assert path_of(fp, h) == str(f)


def test_repair_reports_counts_that_add_up(fp, tmp_path):
    d = tmp_path / "m"
    a = make_audio(d, "a.mp3", b"aaa")
    b = make_audio(d, "b.mp3", b"bbb")
    make_audio(d, "c.mp3", b"ccc")  # not in the library
    add_track(fp, fp.file_hash(a), "")  # needs filling
    add_track(fp, fp.file_hash(b), str(b))  # already fine
    out = fp.repair(d, dry_run=True)
    assert out["audio_files_scanned"] == 3
    assert out["filled"] + out["repointed"] + out["already_ok"] == out["matched_tracks"] == 2
    assert out["unanalysed_files"] == 1
