"""SQLite persistence: analysis cache, embeddings, and vibe centroids."""

import configparser
import hashlib
import json
import os
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path


def _resolve_db_path() -> Path:
    """Where the library database lives, in priority order:

    1. ``GENRE_DB`` env var — always wins (power users, dev, the test suite).
    2. ``[vibenative] db_path`` in ``settings.ini`` (``paths.settings_ini_for_read``):
       the per-user copy in ``%APPDATA%\\Vibe Identify``, which a packaged build seeds
       once from the installer's DB-location page (written beside the exe) and the
       Options tab updates; the exe-adjacent file is read only if that copy is
       missing. Env vars in the value (e.g. ``%USERPROFILE%``) are expanded at
       runtime so a machine-wide setting still resolves per-user.
    3. Default: ``%USERPROFILE%\\genre_v2.db``.
    """
    env = os.environ.get("GENRE_DB")
    if env:
        return Path(os.path.expandvars(env))
    try:
        from .paths import settings_ini_for_read

        ini = settings_ini_for_read()
        if ini.is_file():
            # interpolation=None so a literal "%USERPROFILE%" in the value isn't parsed
            # as configparser interpolation; os.path.expandvars expands it below.
            cp = configparser.ConfigParser(interpolation=None)
            cp.read(ini, encoding="utf-8")
            val = cp.get("vibenative", "db_path", fallback="").strip()
            if val:
                return Path(os.path.expandvars(val))
    except Exception:  # nosec B110  # a malformed settings.ini must never block startup -> fall through
        pass
    return Path.home() / "genre_v2.db"


DB_PATH = _resolve_db_path()
_db_lock = threading.Lock()


def db():
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


# --- schema migrations -------------------------------------------------------
# The schema is versioned. A `schema_version` table holds the highest applied
# migration number; init_db() runs every migration whose number exceeds it, in
# order, inside init_db's transaction, then records the new version. A database
# with no `schema_version` row (a fresh file, or a legacy DB from before this
# machinery) counts as version 0 and is upgraded in place.
#
# To evolve the schema: APPEND a new (version, fn) entry to MIGRATIONS with the
# next integer and a function taking an open cursor. Never edit or renumber an
# already-shipped migration — a populated database has already run it; only add
# new ones. Keep migrations re-run-safe (CREATE TABLE IF NOT EXISTS, guarded
# ALTERs) so an interrupted upgrade recovers on the next start.


def _migration_1(c):
    """v1 — the full baseline schema (everything that predates versioning).

    Moved verbatim from the pre-migration init_db, including the weight-column
    patch for older `vibe_tracks`. On a legacy DB whose tables already exist the
    CREATE ... IF NOT EXISTS calls no-op and the guarded ALTER is skipped, so it
    converges to the exact same schema a fresh DB gets — no data touched."""
    c.execute("""CREATE TABLE IF NOT EXISTS tracks(
        hash TEXT PRIMARY KEY, filename TEXT, filepath TEXT, title TEXT,
        payload TEXT, embedding BLOB, created REAL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS vibes(
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)""")
    c.execute("""CREATE TABLE IF NOT EXISTS vibe_tracks(
        vibe_id INTEGER, hash TEXT, UNIQUE(vibe_id, hash))""")
    c.execute("""CREATE TABLE IF NOT EXISTS tags(
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)""")
    c.execute("""CREATE TABLE IF NOT EXISTS track_tags(
        tag_id INTEGER, hash TEXT, UNIQUE(tag_id, hash))""")
    # labeling accelerator: confirmed genre labels (source records HOW a label
    # was made -- 'propagation' from the queue, room for 'override' etc.) and
    # per-genre rejects so a rejected track never resurfaces in that queue.
    c.execute("""CREATE TABLE IF NOT EXISTS training_labels(
        hash TEXT, genre TEXT, source TEXT, created REAL,
        UNIQUE(hash, genre))""")
    c.execute("""CREATE TABLE IF NOT EXISTS training_rejects(
        hash TEXT, genre TEXT, UNIQUE(hash, genre))""")
    # segment-level manual overrides: a time range of a track labelled a genre
    # (drag-selected on the waveform). Shipped with the payload on cache hits so
    # the waveform repaints the span; also drives ffmpeg clip extraction.
    c.execute("""CREATE TABLE IF NOT EXISTS segment_overrides(
        hash TEXT, start_s REAL, end_s REAL, genre TEXT, created REAL)""")
    # external metadata-lookup cache: one row per (track, source). External
    # hits are cached permanently so a repeat click never re-queries the API.
    c.execute("""CREATE TABLE IF NOT EXISTS lookup_cache(
        hash TEXT, source TEXT, response_json TEXT, fetched REAL,
        UNIQUE(hash, source))""")
    # high-resolution min/max/rms waveform (DAW-style rendering). Computed once
    # per track -- pre-filled at analysis time, or on demand from the audio file
    # -- and cached permanently so it's never recomputed.
    c.execute("""CREATE TABLE IF NOT EXISTS waveform_cache(
        hash TEXT PRIMARY KEY, data_json TEXT, created REAL)""")
    # weighted vibe membership (Rocchio relevance feedback).
    # Older DBs have vibe_tracks(vibe_id, hash) only; add the weight column.
    cols = {r[1] for r in c.execute("PRAGMA table_info(vibe_tracks)")}
    if "weight" not in cols:
        c.execute("ALTER TABLE vibe_tracks ADD COLUMN weight REAL DEFAULT 1.0")


def _migration_2(c):
    """v2 — translate legacy WSL mount filepaths to native Windows drive-letter
    paths (Phase-4 port / addendum §5).

    The WSL app stored server-side paths as ``/mnt/<drive>/...``; on Windows those
    don't resolve, so audio preview, on-demand waveforms, and segment extraction
    would break for inherited rows. Rewrite only the mnt-prefixed ``tracks.filepath``
    values via the same ``legacy.wsl_to_windows`` helper the routes use
    (``/mnt/c/Users/x`` -> ``C:\\Users\\x``). ``tracks.filepath`` is the only stored
    filesystem path in the schema. Idempotent: a translated path no longer matches
    the ``/mnt/%`` filter, so a re-run touches nothing."""
    from .legacy import wsl_to_windows

    rows = c.execute("SELECT rowid, filepath FROM tracks WHERE filepath LIKE '/mnt/%'").fetchall()
    for rowid, fp in rows:
        c.execute("UPDATE tracks SET filepath=? WHERE rowid=?", (wsl_to_windows(fp), rowid))


def _migration_3(c):
    """v3 — named saved playlists (the save/load feature). Each row is a named
    snapshot of a playlist: its track list stored as JSON. The live working playlist
    still lives client-side; this is for durable, named ones."""
    c.execute("""CREATE TABLE IF NOT EXISTS playlists(
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE,
        tracks TEXT, created REAL, updated REAL)""")


def _migration_4(c):
    """v4 — per-track ratings: stars, a letter grade, and a free-text note.

    Kept in their own table rather than inside ``tracks.payload``: the payload is
    analysis output, rewritten wholesale whenever a track is re-analysed, and a
    rating is the user's own judgement that must outlive that. One row per track,
    created on first rating.

    ``stars`` is 0-5 as shown in the UI; the Rekordbox 0/51/.../255 encoding is
    applied at export, not stored, so the number here stays the one the user set.
    """
    c.execute("""CREATE TABLE IF NOT EXISTS ratings(
        hash TEXT PRIMARY KEY, stars INTEGER DEFAULT 0,
        grade TEXT DEFAULT '', note TEXT DEFAULT '', updated REAL)""")


def _migration_5(c):
    """v5 -- a description on each vibe.

    A vibe is the user's own category, so what it means lives only in their
    head unless there is somewhere to write it down. Deliberately unbounded
    TEXT with no length cap: this is notes about what belongs in a set, and a
    field that truncates at some arbitrary limit would be worse than none.
    """
    cols = {r[1] for r in c.execute("PRAGMA table_info(vibes)")}
    if "description" not in cols:
        c.execute("ALTER TABLE vibes ADD COLUMN description TEXT DEFAULT ''")


def _migration_6(c):
    """v6 -- per-ARTIST ratings, alongside the per-track ones from v4.

    A track rating and an artist rating answer different questions: "is this
    record good" versus "is this producer worth my time". Neither implies the
    other -- a favourite artist still puts out a weak track -- so they are
    separate rows rather than one derived from the average of the other.

    Keyed on a NORMALISED artist name (casefolded, whitespace collapsed) because
    tags are not consistent: "Skrillex", "skrillex" and "SKRILLEX " are one
    artist and must not become three ratings. ``display`` keeps the spelling the
    user actually saw when they rated, so the UI can show it back to them
    unchanged.

    Deliberately NOT a foreign key to tracks: an artist is a string on a track,
    not a row anywhere, and a rating should survive every track by that artist
    being removed and re-added under a different filename.
    """
    c.execute("""CREATE TABLE IF NOT EXISTS artist_ratings(
        artist_key TEXT PRIMARY KEY, display TEXT DEFAULT '',
        stars INTEGER DEFAULT 0, grade TEXT DEFAULT '',
        note TEXT DEFAULT '', updated REAL)""")


# The tables the map is built from. A write to any of them bumps library_rev.
_LIBRARY_TABLES = ("tracks", "tags", "track_tags")


def _migration_7(c):
    """v7 -- a library revision, bumped by trigger on every write to a table the
    map is built from.

    The map cache used to be keyed on a digest of every track row, which meant
    that even asking "is my map still current" read and hashed the whole
    payload column -- a quarter of a gigabyte and half a second on a large
    library, paid on every visit to the Map tab. A counter the database itself
    maintains answers the same question in microseconds, and cannot be bypassed
    by a write path that forgot to bump it: the triggers fire for every INSERT,
    UPDATE and DELETE, including snapshot restores and bulk deletes.

    Ratings, vibes, playlists and the waveform cache are deliberately not
    covered -- they are overlays the map fetches separately, and a write to
    them must not invalidate a map that is still exactly right.
    """
    c.execute("""CREATE TABLE IF NOT EXISTS library_rev(
        id INTEGER PRIMARY KEY CHECK (id = 1), rev INTEGER NOT NULL)""")
    c.execute("INSERT OR IGNORE INTO library_rev(id, rev) VALUES (1, 0)")
    for t in _LIBRARY_TABLES:
        for op in ("INSERT", "UPDATE", "DELETE"):
            c.execute(
                f"CREATE TRIGGER IF NOT EXISTS {t}_rev_{op.lower()} AFTER {op} ON {t} "  # nosec B608
                "BEGIN UPDATE library_rev SET rev = rev + 1 WHERE id = 1; END"
            )


def _migration_8(c):
    """v8 -- corrected keys.

    The key detector (`tonality.py`) is a trained model, and the training data
    that matters most is this library's own music: public EDM key sets disagree
    with each other by ~6 points, so a model fitted to one of them is
    mis-calibrated for anyone else's collection. Every key a person corrects
    here is one labelled example from the distribution that actually matters,
    which `tools/eval_key.py --dataset library` reads back and
    `tools/train_key_templates.py` trains on.

    Kept out of the payload deliberately: the payload is the analyser's output
    and gets overwritten on re-analysis, whereas a human judgement must outlive
    that. Routes read the label and present it in place of the detected key.
    """
    c.execute("""CREATE TABLE IF NOT EXISTS key_labels(
        hash TEXT PRIMARY KEY, key TEXT NOT NULL, scale TEXT NOT NULL,
        source TEXT, created REAL)""")


# Ordered, append-only list of (version, migration_fn).
MIGRATIONS = [
    (1, _migration_1),
    (2, _migration_2),
    (3, _migration_3),
    (4, _migration_4),
    (5, _migration_5),
    (6, _migration_6),
    (7, _migration_7),
    (8, _migration_8),
]


def init_db():
    """Bring the database up to the latest schema version.

    Applies every migration numbered above the DB's recorded version, in order,
    within init_db's transaction, then records the new version. Idempotent: an
    already-current DB runs no migrations and just re-affirms its version."""
    with _db_lock, closing(db()) as conn, conn as c:
        c.execute("CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL)")
        row = c.execute("SELECT version FROM schema_version").fetchone()
        current = row[0] if row else 0
        for version, migrate in MIGRATIONS:
            if version > current:
                migrate(c)
                current = version
        if row is None:
            c.execute("INSERT INTO schema_version(version) VALUES(?)", (current,))
        else:
            c.execute("UPDATE schema_version SET version=?", (current,))


def library_rev(c) -> int:
    """The current library revision (see _migration_7), on an open cursor."""
    row = c.execute("SELECT rev FROM library_rev WHERE id = 1").fetchone()
    return int(row[0]) if row else 0


def file_hash(path) -> str:
    """Content hash: same song caches regardless of filename or location."""
    h = hashlib.sha1()  # nosec B324  # content cache key (dedupe by audio), not security
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cache_get(h: str):
    with _db_lock, closing(db()) as conn, conn as c:
        row = c.execute("SELECT payload FROM tracks WHERE hash=?", (h,)).fetchone()
    return json.loads(row[0]) if row else None


def cache_put(h: str, filename, filepath, title, payload: dict, emb):
    import numpy as np

    blob = np.asarray(emb, dtype=np.float32).tobytes() if emb is not None else None
    with _db_lock, closing(db()) as conn, conn as c:
        c.execute(
            "INSERT OR REPLACE INTO tracks(hash, filename, filepath, title, payload, embedding, created) "
            "VALUES(?,?,?,?,?,?,?)",
            (h, filename, filepath or "", title, json.dumps(payload), blob, time.time()),
        )


def key_label_get(h: str):
    """The corrected (key, scale) for a track, or None."""
    with _db_lock, closing(db()) as conn, conn as c:
        row = c.execute("SELECT key, scale FROM key_labels WHERE hash=?", (h,)).fetchone()
    return (row[0], row[1]) if row else None


def key_label_put(h: str, key: str, scale: str, source: str = "manual"):
    with _db_lock, closing(db()) as conn, conn as c:
        c.execute(
            "INSERT OR REPLACE INTO key_labels(hash, key, scale, source, created) VALUES(?,?,?,?,?)",
            (h, key, scale, source, time.time()),
        )


def key_label_delete(h: str):
    """Drop a correction; the detector's own answer stands again."""
    with _db_lock, closing(db()) as conn, conn as c:
        c.execute("DELETE FROM key_labels WHERE hash=?", (h,))


# Every table holding per-track rows, keyed by the content hash in a `hash`
# column. forget_track deletes from all of them; test_db checks this list against
# the live schema, so a new per-track table cannot be silently left behind.
TRACK_TABLES = (
    "tracks",
    "track_tags",
    "vibe_tracks",
    "segment_overrides",
    "lookup_cache",
    "waveform_cache",
    "ratings",
    "training_labels",
    "training_rejects",
    "key_labels",
)


def forget_track(h: str) -> int:
    """Delete everything stored about one track, in one transaction. Returns how
    many `tracks` rows went (0 or 1). The tracks/track_tags triggers bump
    library_rev, so the map cache rebuilds. The audio file is never touched."""
    with _db_lock, closing(db()) as conn, conn as c:
        deleted = c.execute("DELETE FROM tracks WHERE hash=?", (h,)).rowcount
        for t in TRACK_TABLES[1:]:
            c.execute(f"DELETE FROM {t} WHERE hash=?", (h,))  # nosec B608  # t from TRACK_TABLES
    return deleted


def key_labels_map():
    """{hash: (key, scale)} for every correction -- one query for a whole listing."""
    with _db_lock, closing(db()) as conn, conn as c:
        return {r[0]: (r[1], r[2]) for r in c.execute("SELECT hash, key, scale FROM key_labels")}


def key_labels_all():
    """[(hash, filepath, key, scale)] for every corrected track that still has a
    file on disk recorded -- the training set tools/eval_key.py reads."""
    with _db_lock, closing(db()) as conn, conn as c:
        return c.execute(
            "SELECT l.hash, t.filepath, l.key, l.scale FROM key_labels l "
            "JOIN tracks t ON t.hash = l.hash WHERE t.filepath != ''"
        ).fetchall()


def waveform_cache_get(h: str):
    with _db_lock, closing(db()) as conn, conn as c:
        row = c.execute("SELECT data_json FROM waveform_cache WHERE hash=?", (h,)).fetchone()
    return json.loads(row[0]) if row else None


def waveform_cache_put(h: str, data: dict):
    with _db_lock, closing(db()) as conn, conn as c:
        c.execute(
            "INSERT OR REPLACE INTO waveform_cache(hash, data_json, created) VALUES(?,?,?)",
            (h, json.dumps(data), time.time()),
        )


def track_embedding(h: str):
    import numpy as np

    with _db_lock, closing(db()) as conn, conn as c:
        row = c.execute("SELECT embedding FROM tracks WHERE hash=?", (h,)).fetchone()
    if not row or row[0] is None:
        return None
    return np.frombuffer(row[0], dtype=np.float32)


def cosine(a, b):
    import numpy as np

    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def vibe_centroid(vibe_id: int):
    """Preference-weighted center of a vibe (Rocchio relevance feedback):

        center = Σ (weightᵢ · embeddingᵢ) / Σ |weightᵢ|

    Positive-weight (liked) tracks pull the center toward them; negative-weight
    (disliked) tracks push it away. Cosine ranking is scale-invariant, so the
    normalization just keeps magnitudes tame. With all weights = 1 this reduces
    to the old plain mean. Returns None if the vibe has no usable members."""
    import numpy as np

    with _db_lock, closing(db()) as conn, conn as c:
        rows = c.execute(
            "SELECT t.embedding, v.weight FROM vibe_tracks v JOIN tracks t "
            "ON t.hash=v.hash WHERE v.vibe_id=? AND t.embedding IS NOT NULL",
            (vibe_id,),
        ).fetchall()
    acc, wsum = None, 0.0
    for blob, w in rows:
        if not blob:
            continue
        w = 1.0 if w is None else float(w)
        emb = np.frombuffer(blob, dtype=np.float32) * w
        acc = emb if acc is None else acc + emb
        wsum += abs(w)
    if acc is None or wsum == 0:
        return None
    return acc / wsum
