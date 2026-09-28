"""Schema-migration tests for vibenative.db.

Covers the versioned-migration machinery: a fresh database and a legacy
database (built here from the pre-versioning schema, WITHOUT the weight column
or a schema_version table — i.e. what the oldest real DBs contain) must both
upgrade to the same schema version with a structurally identical schema, and
existing rows must survive the upgrade untouched.
"""

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from vibenative import db

_ROOT = Path(__file__).resolve().parent.parent
_BACKUP = _ROOT / "genre_v2.db.backup"  # local-only (gitignored); the WSL app's real DB
_ORACLE_INDEX = _ROOT / "oracle" / "index.json"

# The schema an old build produced, written out independently of MIGRATIONS so
# this test genuinely catches a future divergence in migration 1 (e.g. someone
# inlining the weight column). vibe_tracks intentionally has NO weight column and
# there is NO schema_version table: the migration must add both in place.
LEGACY_SCHEMA = [
    "CREATE TABLE IF NOT EXISTS tracks(hash TEXT PRIMARY KEY, filename TEXT, "
    "filepath TEXT, title TEXT, payload TEXT, embedding BLOB, created REAL)",
    "CREATE TABLE IF NOT EXISTS vibes(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)",
    "CREATE TABLE IF NOT EXISTS vibe_tracks(vibe_id INTEGER, hash TEXT, UNIQUE(vibe_id, hash))",
    "CREATE TABLE IF NOT EXISTS tags(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)",
    "CREATE TABLE IF NOT EXISTS track_tags(tag_id INTEGER, hash TEXT, UNIQUE(tag_id, hash))",
    "CREATE TABLE IF NOT EXISTS training_labels(hash TEXT, genre TEXT, source TEXT, "
    "created REAL, UNIQUE(hash, genre))",
    "CREATE TABLE IF NOT EXISTS training_rejects(hash TEXT, genre TEXT, UNIQUE(hash, genre))",
    "CREATE TABLE IF NOT EXISTS segment_overrides(hash TEXT, start_s REAL, end_s REAL, "
    "genre TEXT, created REAL)",
    "CREATE TABLE IF NOT EXISTS lookup_cache(hash TEXT, source TEXT, response_json TEXT, "
    "fetched REAL, UNIQUE(hash, source))",
    "CREATE TABLE IF NOT EXISTS waveform_cache(hash TEXT PRIMARY KEY, data_json TEXT, created REAL)",
]


def _norm(sql):
    """Compare stored CREATE text by non-whitespace structure only: SQLite keeps
    the original formatting, and moving the schema into a function re-indented it,
    so whitespace differences are incidental while any column/constraint change is
    still caught (every non-whitespace character is preserved)."""
    return "".join(sql.split()) if sql else sql


def _schema(path):
    """Normalized (type, name, sql) for every non-internal object in the DB."""
    con = sqlite3.connect(path)
    try:
        rows = con.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
    finally:
        con.close()
    return [(t, n, _norm(s)) for t, n, s in rows]


def _version(path):
    con = sqlite3.connect(path)
    try:
        return con.execute("SELECT version FROM schema_version").fetchone()[0]
    finally:
        con.close()


def _make_legacy(path):
    """A populated pre-versioning database: old schema + a couple of rows."""
    con = sqlite3.connect(path)
    try:
        for stmt in LEGACY_SCHEMA:
            con.execute(stmt)
        con.execute(
            "INSERT INTO tracks(hash, filename, title) VALUES(?,?,?)",
            ("h1", "song.mp3", "Song"),
        )
        con.execute("INSERT INTO vibes(name) VALUES(?)", ("night",))
        con.execute("INSERT INTO vibe_tracks(vibe_id, hash) VALUES(?,?)", (1, "h1"))
        con.commit()
    finally:
        con.close()


def test_fresh_and_legacy_converge(tmp_path, monkeypatch):
    fresh = tmp_path / "fresh.db"
    legacy = tmp_path / "legacy.db"

    # Fresh DB: init from nothing.
    monkeypatch.setattr(db, "DB_PATH", fresh)
    db.init_db()

    # Legacy DB: build the old schema by hand, populate it, then migrate.
    _make_legacy(legacy)
    monkeypatch.setattr(db, "DB_PATH", legacy)
    db.init_db()

    # Both land on the same (latest) version. Derived from MIGRATIONS rather than
    # hard-coded, so adding a migration doesn't fail a test about *convergence*.
    latest = max(v for v, _ in db.MIGRATIONS)
    assert _version(fresh) == latest
    assert _version(legacy) == latest

    # ...with a structurally identical schema (incl. schema_version + the weight
    # column the migration added to the legacy vibe_tracks in place).
    assert _schema(fresh) == _schema(legacy)
    legacy_cols = {r[1] for r in sqlite3.connect(legacy).execute("PRAGMA table_info(vibe_tracks)")}
    assert "weight" in legacy_cols

    # ...and the legacy rows survived, with the new column defaulted.
    con = sqlite3.connect(legacy)
    try:
        assert con.execute("SELECT title FROM tracks WHERE hash='h1'").fetchone()[0] == "Song"
        assert con.execute("SELECT name FROM vibes").fetchone()[0] == "night"
        assert con.execute("SELECT weight FROM vibe_tracks WHERE hash='h1'").fetchone()[0] == 1.0
    finally:
        con.close()


def test_init_db_is_idempotent(tmp_path, monkeypatch):
    path = tmp_path / "x.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()
    before = _schema(path)
    db.init_db()  # second run applies nothing
    assert _schema(path) == before
    assert _version(path) == max(v for v, _ in db.MIGRATIONS)
    # exactly one version row, not one appended per run
    con = sqlite3.connect(path)
    try:
        assert con.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 1
    finally:
        con.close()


def _seed_oracle_mnt_row(dbpath):
    """Insert a /mnt/c row pointing at an oracle track that EXISTS on this disk, so
    migration 2's translation can be proven to resolve to a real file. Returns the
    expected translated Windows Path, or None if no oracle file is available."""
    if not _ORACLE_INDEX.exists():
        return None
    from vibenative.legacy import wsl_to_windows

    idx = json.loads(_ORACLE_INDEX.read_text())
    for _h, m in idx.items():
        mnt = m["file"]
        if not str(mnt).startswith("/mnt/"):
            continue
        win = Path(wsl_to_windows(mnt))
        if win.is_file():
            con = sqlite3.connect(dbpath)
            try:
                con.execute(
                    "INSERT OR REPLACE INTO tracks(hash, filename, filepath, title, created) "
                    "VALUES(?,?,?,?,?)",
                    ("seed_oracle", win.name, mnt, "seed", 0.0),
                )
                con.commit()
            finally:
                con.close()
            return win
    return None


@pytest.mark.skipif(not _BACKUP.exists(), reason="genre_v2.db.backup not present (local-only)")
def test_migration_2_translates_mnt_paths(tmp_path, monkeypatch):
    """Migration 2 rewrites /mnt/<drive>/... filepaths to Windows drive-letter paths.
    Runs against a COPY of the real WSL-app DB (never the backup itself), idempotently,
    and proves a translated path resolves to a real file on disk."""
    dbcopy = tmp_path / "genre_v2_copy.db"
    shutil.copy2(_BACKUP, dbcopy)

    # a control row whose translated path we can resolve to a real file
    expected_win = _seed_oracle_mnt_row(dbcopy)

    monkeypatch.setattr(db, "DB_PATH", dbcopy)
    db.init_db()  # applies all migrations, including #2

    con = sqlite3.connect(dbcopy)
    try:
        # every mnt-prefixed path was rewritten -> none remain
        assert (
            con.execute("SELECT COUNT(*) FROM tracks WHERE filepath LIKE '/mnt/%'").fetchone()[0]
            == 0
        )
        # the seeded row now resolves to a REAL file at its drive-letter path
        if expected_win is not None:
            fp = con.execute("SELECT filepath FROM tracks WHERE hash='seed_oracle'").fetchone()[0]
            assert not fp.startswith("/mnt/")
            assert Path(fp) == expected_win
            assert Path(fp).is_file()  # the whole point: audio preview / clips resolve
    finally:
        con.close()

    # idempotent: a second run finds no /mnt rows and changes nothing
    db.init_db()
    con = sqlite3.connect(dbcopy)
    try:
        assert (
            con.execute("SELECT COUNT(*) FROM tracks WHERE filepath LIKE '/mnt/%'").fetchone()[0]
            == 0
        )
        assert _version(dbcopy) == 3
    finally:
        con.close()


def test_cache_put_round_trips(tmp_path, monkeypatch):
    # cache_put names its columns, so every value lands where cache_get /
    # track_embedding and the listing queries read it back by name.
    np = pytest.importorskip("numpy")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "rt.db")
    db.init_db()

    payload = {"styles": [{"style": "House", "score": 0.5}], "bpm": 124.0}
    emb = np.arange(1280, dtype=np.float32) / 1280
    db.cache_put("h" * 40, "song.mp3", None, "Song", payload, emb)

    assert db.cache_get("h" * 40) == payload
    assert np.array_equal(db.track_embedding("h" * 40), emb)
    conn = sqlite3.connect(db.DB_PATH)
    row = conn.execute(
        "SELECT hash, filename, filepath, title, created FROM tracks WHERE hash=?", ("h" * 40,)
    ).fetchone()
    conn.close()
    assert row[:4] == ("h" * 40, "song.mp3", "", "Song")  # None filepath is stored as ""
    assert isinstance(row[4], float) and row[4] > 0
    # the listing columns (migration 9) are written alongside
    conn = sqlite3.connect(db.DB_PATH)
    names = ", ".join(n for n, _ in db.TRACK_COLUMNS)
    cols = conn.execute(f"SELECT {names} FROM tracks WHERE hash=?", ("h" * 40,)).fetchone()  # nosec B608
    conn.close()
    assert cols == db._track_columns(payload) == ("House", 124.0, None, None, None, None, "")


def test_migration_9_backfills_the_listing_columns(tmp_path, monkeypatch):
    # An existing (v8) library: rows written before the columns existed. The one
    # UPDATE must give exactly what cache_put now writes for the same payload.
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "v8.db")
    conn = sqlite3.connect(db.DB_PATH)
    for version, migrate in db.MIGRATIONS:
        if version <= 8:
            migrate(conn)
    conn.execute("CREATE TABLE schema_version(version INTEGER NOT NULL)")
    conn.execute("INSERT INTO schema_version(version) VALUES(8)")
    payloads = {
        "a" * 40: {
            "styles": [{"style": "House", "score": 0.4}],
            "bpm": 124.5,
            "key": "A",
            "scale": "minor",
            "camelot": "8A",
            "duration": 301.2,
            "tags": {"tag": {"artist": " Floating Points ", "albumartist": "X"}},
        },
        "b" * 40: {"styles": [], "bpm": 128, "tags": {"tag": {"artist": "", "albumartist": "VA "}}},
        "c" * 40: {"styles": [{"style": "Techno"}], "tags": {"tag": {"artist": "   "}}},
        "d" * 40: {},
    }
    for h, p in payloads.items():
        conn.execute(
            "INSERT INTO tracks(hash, filename, filepath, title, payload, embedding, created) "
            "VALUES(?,?,?,?,?,?,?)",
            (h, f"{h[:4]}.mp3", "", "t", json.dumps(p), None, 0.0),
        )
    conn.commit()
    conn.close()

    db.init_db()  # runs migration 9

    conn = sqlite3.connect(db.DB_PATH)
    assert conn.execute("SELECT version FROM schema_version").fetchone()[0] >= 9
    names = ", ".join(n for n, _ in db.TRACK_COLUMNS)
    for h, p in payloads.items():
        row = conn.execute(f"SELECT {names} FROM tracks WHERE hash=?", (h,)).fetchone()  # nosec B608
        assert row == db._track_columns(p), h
    # a JSON integer stays an integer (no REAL affinity), so /library's JSON is unchanged
    assert conn.execute("SELECT typeof(bpm) FROM tracks WHERE hash=?", ("b" * 40,)).fetchone() == (
        "integer",
    )
    assert conn.execute("SELECT tag_artist FROM tracks WHERE hash=?", ("b" * 40,)).fetchone() == (
        "VA",
    )
    conn.close()
    db.init_db()  # idempotent: re-running leaves everything as it is


def test_migration_10_indexes_serve_the_per_track_lookups(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "idx.db")
    db.init_db()
    conn = sqlite3.connect(db.DB_PATH)

    def plan(q, *args):
        return " | ".join(r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + q, args))

    p = plan("SELECT rowid FROM segment_overrides WHERE hash=? ORDER BY start_s", "x")
    assert "idx_segment_overrides_hash" in p and "TEMP B-TREE" not in p  # no sort either
    assert "idx_track_tags_hash" in plan(
        "SELECT tag_id FROM track_tags WHERE hash IN (?,?)", "a", "b"
    )
    assert "idx_vibe_tracks_hash" in plan("DELETE FROM vibe_tracks WHERE hash=?", "x")
    assert "idx_tracks_style" in plan("SELECT hash FROM tracks WHERE style=?", "House")
    # the two not added were already indexed: no duplicate index was created
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert not any(
        n.startswith("idx_key_labels") or n.startswith("idx_training_labels") for n in names
    )
    conn.close()


def test_readers_and_writers_share_the_db_concurrently(tmp_path, monkeypatch):
    # Reads no longer take _db_lock and every thread has its own connection (WAL):
    # 4 readers and 2 writers for a few seconds, no "database is locked", no errors.
    import threading
    import time

    np = pytest.importorskip("numpy")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "conc.db")
    db.init_db()
    for i in range(50):
        db.cache_put(
            f"seed{i:036d}", "s.mp3", "", "s", {"styles": [{"style": "House"}]}, np.ones(8)
        )

    stop, errors, counts = threading.Event(), [], {"reads": 0, "writes": 0}
    written = [[], []]

    def reader():
        try:
            while not stop.is_set():
                assert db.cache_get(f"seed{7:036d}")["styles"][0]["style"] == "House"
                db.key_labels_map()
                assert db.track_embedding(f"seed{3:036d}") is not None
                with db.closing(db.db()) as conn, conn as c:
                    c.execute("SELECT COUNT(*), MAX(created) FROM tracks").fetchone()
                counts["reads"] += 1
        except Exception as e:  # surfaced below
            errors.append(e)

    def writer(w):
        try:
            i = 0
            while not stop.is_set():
                h = f"w{w}-{i:035d}"
                db.cache_put(
                    h, "w.mp3", "", "w", {"styles": [{"style": "Techno"}], "bpm": 128}, np.ones(8)
                )
                db.key_label_put(h, "A", "minor")
                written[w].append(h)
                counts["writes"] += 1
                i += 1
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=reader) for _ in range(4)]
    threads += [threading.Thread(target=writer, args=(w,)) for w in range(2)]
    for t in threads:
        t.start()
    time.sleep(3)
    stop.set()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads)
    assert errors == []
    assert counts["reads"] > 50 and counts["writes"] > 20
    everything = written[0] + written[1]
    assert all(db.cache_get(h) is not None for h in everything)  # every write committed
    assert set(db.key_labels_map()) >= set(everything)
    db.close_all()
