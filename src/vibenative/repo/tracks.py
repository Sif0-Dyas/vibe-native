"""The ``tracks`` table, its per-track side tables (``segment_overrides``,
``lookup_cache``) and the library revision."""

import json
import time
from pathlib import Path

import numpy as np

from .. import db as _db
from ..artists import artist_tag
from ..style import dominant_style
from . import NotFound, reading, writing


def library_rev() -> int:
    """The current library revision (see db._migration_7)."""
    with reading() as c:
        row = c.execute("SELECT rev FROM library_rev WHERE id = 1").fetchone()
    return int(row[0]) if row else 0


def map_rows():
    """(hash, title, filename, filepath, payload, embedding) for every track."""
    with reading() as c:
        return c.execute(
            "SELECT hash, title, filename, filepath, payload, embedding FROM tracks"
        ).fetchall()


def export_rows(hashes):
    """(hash, title, filename, filepath, payload) for each hash, in the order given
    (a hash listed twice comes back twice); hashes not in the library are skipped."""
    out = []
    with reading() as c:
        for h in hashes:
            t = c.execute(
                "SELECT hash, title, filename, filepath, payload FROM tracks WHERE hash=?", (h,)
            ).fetchone()
            if t:
                out.append(t)
    return out


def exists(h) -> bool:
    with reading() as c:
        return c.execute("SELECT hash FROM tracks WHERE hash=?", (h,)).fetchone() is not None


def file_info(h):
    """(filepath, filename) for track ``h``, or None if it isn't in the library.
    filepath is empty (or None) for a track analysed from a browser drop."""
    with reading() as c:
        return c.execute("SELECT filepath, filename FROM tracks WHERE hash=?", (h,)).fetchone()


def backfill_filepath(h, path):
    """Record ``path`` for track ``h`` if its stored path is blank or no longer
    exists (the file moved; the content hash says it is the same track). A stored
    path that still resolves is left alone. Read and write under one lock."""
    with writing() as c:
        row = c.execute("SELECT filepath FROM tracks WHERE hash=?", (h,)).fetchone()
        if row is None:
            return
        current = row[0] or ""
        if not current or not Path(current).is_file():  # blank, or stale (moved away)
            c.execute("UPDATE tracks SET filepath=? WHERE hash=?", (path, h))


def segment_overrides(h):
    """[(rowid, start_s, end_s, genre)] for track ``h``, earliest span first."""
    with reading() as c:
        return c.execute(
            "SELECT rowid, start_s, end_s, genre FROM segment_overrides WHERE hash=? "
            "ORDER BY start_s",
            (h,),
        ).fetchall()


def embedding_rows():
    """(hash, title, filename, payload, embedding) for every track."""
    with reading() as c:
        return c.execute("SELECT hash, title, filename, payload, embedding FROM tracks").fetchall()


def payload_rows():
    """(hash, title, filename, filepath, payload) for every track."""
    with reading() as c:
        return c.execute("SELECT hash, title, filename, filepath, payload FROM tracks").fetchall()


# --- the library listing and the track's own payload ---------------------------
def listing():
    """The Library tab's columns for every track, newest first (migration 9's
    denormalised columns -- no payload)."""
    with reading() as c:
        return c.execute(
            "SELECT hash, filename, title, filepath, created, style, bpm, key, scale, "
            "camelot, duration, tag_artist FROM tracks ORDER BY created DESC"
        ).fetchall()


def count() -> int:
    with reading() as c:
        return c.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]


def payload(h):
    """Track ``h``'s stored payload JSON, as stored (a str, or None); raises
    NotFound if the track isn't in the library."""
    with reading() as c:
        row = c.execute("SELECT payload FROM tracks WHERE hash=?", (h,)).fetchone()
    if not row:
        raise NotFound(h)
    return row[0]


def file_and_payload(h):
    """(filepath, payload JSON) for track ``h``, or None."""
    with reading() as c:
        return c.execute("SELECT filepath, payload FROM tracks WHERE hash=?", (h,)).fetchone()


def update_payload(h, change):
    """Rewrite track ``h``'s payload as ``change(stored JSON)`` -- a dict -- with the
    read and the write under one lock, so no other writer's change is lost in
    between. ``change`` gets the stored JSON rather than a parsed dict because
    callers differ on a corrupt one (fail, or start from {}).

    The ``style`` column is recomputed from the new payload in the same write,
    so /library (which reads the column) shows what every other view does.

    Returns (filepath, the new payload); raises NotFound if the track isn't in the
    library. Keep ``change`` to in-memory work: it runs under the write lock."""
    with writing() as c:
        row = c.execute("SELECT filepath, payload FROM tracks WHERE hash=?", (h,)).fetchone()
        if not row:
            raise NotFound(h)
        p = change(row[1])
        c.execute(
            "UPDATE tracks SET payload=?, style=? WHERE hash=?",
            (json.dumps(p), dominant_style(p), h),
        )
    return row[0], p


def similar_candidates(h):
    """(hash, title, filename, filepath, tag_artist, style, bpm, camelot, embedding)
    for every track with an embedding except ``h`` -- columns only, no payload."""
    with reading() as c:
        return c.execute(
            "SELECT hash, title, filename, filepath, tag_artist, style, bpm, camelot, embedding "
            "FROM tracks WHERE embedding IS NOT NULL AND hash != ?",
            (h,),
        ).fetchall()


# --- segment overrides ----------------------------------------------------------
def add_segment(h, start, end, genre) -> int:
    """Record that ``start``..``end`` seconds of track ``h`` are ``genre``; the
    new override's id."""
    with writing() as c:
        return c.execute(
            "INSERT INTO segment_overrides(hash, start_s, end_s, genre, created) VALUES(?,?,?,?,?)",
            (h, start, end, genre, time.time()),
        ).lastrowid


def pop_segment(oid):
    """Delete segment override ``oid`` and return it as (hash, start_s, end_s,
    genre), read and deleted under one lock; None if there is no such override."""
    with writing() as c:
        row = c.execute(
            "SELECT hash, start_s, end_s, genre FROM segment_overrides WHERE rowid=?", (oid,)
        ).fetchone()
        if row:
            c.execute("DELETE FROM segment_overrides WHERE rowid=?", (oid,))
    return row


# --- external metadata lookups ---------------------------------------------------
def lookup_fields(h):
    """(title, filename, payload JSON) for track ``h`` -- what a metadata lookup
    searches by -- or None."""
    with reading() as c:
        return c.execute(
            "SELECT title, filename, payload FROM tracks WHERE hash=?", (h,)
        ).fetchone()


def lookups_cached(h) -> dict:
    """{source: parsed response} for every lookup cached for track ``h``."""
    with reading() as c:
        return {
            r[0]: json.loads(r[1])
            for r in c.execute("SELECT source, response_json FROM lookup_cache WHERE hash=?", (h,))
        }


def cache_lookup(h, source, parsed):
    """Keep ``source``'s parsed answer for track ``h`` permanently."""
    with writing() as c:
        c.execute(
            "INSERT OR REPLACE INTO lookup_cache(hash, source, response_json, fetched) "
            "VALUES(?,?,?,?)",
            (h, source, json.dumps(parsed), time.time()),
        )


# --- embeddings --------------------------------------------------------------------
def embeddings_for(hashes) -> dict:
    """{hash: embedding blob} for each of ``hashes`` that has one; one query per 500."""
    out = {}
    with reading() as c:
        for i in range(0, len(hashes), 500):
            chunk = hashes[i : i + 500]
            q = ",".join("?" * len(chunk))
            for h, blob in c.execute(
                f"SELECT hash, embedding FROM tracks WHERE hash IN ({q})",  # nosec B608
                chunk,
            ):
                if blob is not None:
                    out[h] = blob
    return out


def embedded_rows(limit=None):
    """(hash, title, filename, payload, embedding) for every track with an
    embedding (the first ``limit`` of them, if given)."""
    q = "SELECT hash, title, filename, payload, embedding FROM tracks WHERE embedding IS NOT NULL"
    if limit:
        q += f" LIMIT {int(limit)}"
    with reading() as c:
        return c.execute(q).fetchall()


# --- the analysis cache ----------------------------------------------------------
def track_columns(payload: dict) -> tuple:
    """db.TRACK_COLUMNS' values for one payload. ``style`` is the track's identity
    (style.dominant_style, as db._migration_11 backfilled it); the rest are what
    db._migration_9's UPDATE computes."""
    return (
        dominant_style(payload),
        payload.get("bpm"),
        payload.get("key"),
        payload.get("scale"),
        payload.get("camelot"),
        payload.get("duration"),
        artist_tag(payload),
    )


def cache_get(h: str):
    with reading() as c:
        row = c.execute("SELECT payload FROM tracks WHERE hash=?", (h,)).fetchone()
    return json.loads(row[0]) if row else None


def cache_put(h: str, filename, filepath, title, payload: dict, emb):
    blob = np.asarray(emb, dtype=np.float32).tobytes() if emb is not None else None
    with writing() as c:
        c.execute(
            "INSERT OR REPLACE INTO tracks(hash, filename, filepath, title, payload, embedding, "
            "created, style, bpm, key, scale, camelot, duration, tag_artist) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (h, filename, filepath or "", title, json.dumps(payload), blob, time.time())
            + track_columns(payload),
        )


def forget_track(h: str) -> int:
    """Delete everything stored about one track, in one transaction. Returns how
    many `tracks` rows went (0 or 1). The tracks/track_tags triggers bump
    library_rev, so the map cache rebuilds. The audio file is never touched."""
    with writing() as c:
        deleted = c.execute("DELETE FROM tracks WHERE hash=?", (h,)).rowcount
        for t in _db.TRACK_TABLES[1:]:
            c.execute(f"DELETE FROM {t} WHERE hash=?", (h,))  # nosec B608  # t from TRACK_TABLES
    return deleted


def waveform_cache_get(h: str):
    with reading() as c:
        row = c.execute("SELECT data_json FROM waveform_cache WHERE hash=?", (h,)).fetchone()
    return json.loads(row[0]) if row else None


def waveform_cache_put(h: str, data: dict):
    with writing() as c:
        c.execute(
            "INSERT OR REPLACE INTO waveform_cache(hash, data_json, created) VALUES(?,?,?)",
            (h, json.dumps(data), time.time()),
        )


# --- file paths ----------------------------------------------------------------------
def is_library_filepath(path: str) -> bool:
    """True if ``path`` is exactly the server-side path of a track in the library.

    Routes that act on a caller-named server file (/save_training's copy) accept
    only these, so the request can't name an arbitrary file on disk."""
    with reading() as c:
        row = c.execute("SELECT 1 FROM tracks WHERE filepath=? LIMIT 1", (path,)).fetchone()
    return row is not None


def path_rows():
    """(hash, title, filename, filepath) for every track."""
    with reading() as c:
        return c.execute("SELECT hash, title, filename, filepath FROM tracks").fetchall()


def hash_filepaths():
    """(hash, filepath) for every track."""
    with reading() as c:
        return c.execute("SELECT hash, filepath FROM tracks").fetchall()


def set_filepaths(pairs):
    """Record each (filepath, hash) in ``pairs``, in one transaction."""
    with writing() as c:
        c.executemany("UPDATE tracks SET filepath=? WHERE hash=?", pairs)


# --- payloads, whole-library -----------------------------------------------------------
def hash_payloads():
    """(hash, payload JSON) for every track."""
    with reading() as c:
        return c.execute("SELECT hash, payload FROM tracks").fetchall()


def summary_rows():
    """(hash, title, filename, payload JSON) for every track."""
    with reading() as c:
        return c.execute("SELECT hash, title, filename, payload FROM tracks").fetchall()


def style_embeddings():
    """(hash, style column, embedding) for every track with an embedding."""
    with reading() as c:
        return c.execute(
            "SELECT hash, style, embedding FROM tracks WHERE embedding IS NOT NULL"
        ).fetchall()


def audit_rows():
    """(hash, title, payload JSON, embedding) for every track with an embedding."""
    with reading() as c:
        return c.execute(
            "SELECT hash, title, payload, embedding FROM tracks WHERE embedding IS NOT NULL"
        ).fetchall()


# --- one embedding, and comparing two ---------------------------------------------------
def track_embedding(h: str):
    with reading() as c:
        row = c.execute("SELECT embedding FROM tracks WHERE hash=?", (h,)).fetchone()
    if not row or row[0] is None:
        return None
    return np.frombuffer(row[0], dtype=np.float32)


def cosine(a, b):
    """Cosine similarity of two embeddings (maths, not SQL -- kept beside the
    readers whose vectors it compares); 0.0 if either is all zeros."""
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))
