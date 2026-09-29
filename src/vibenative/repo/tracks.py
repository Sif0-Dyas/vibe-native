"""The ``tracks`` table, its per-track side tables (``segment_overrides``,
``lookup_cache``) and the library revision."""

import json
import time
from pathlib import Path

from .. import db as _db
from ..style import dominant_style
from . import NotFound, reading, writing


def library_rev() -> int:
    """The current library revision (see db._migration_7)."""
    with reading() as c:
        return _db.library_rev(c)


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


def embedded_rows():
    """(hash, title, filename, payload, embedding) for every track with an embedding."""
    with reading() as c:
        return c.execute(
            "SELECT hash, title, filename, payload, embedding FROM tracks "
            "WHERE embedding IS NOT NULL"
        ).fetchall()
