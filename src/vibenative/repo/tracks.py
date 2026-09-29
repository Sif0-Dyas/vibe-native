"""The ``tracks`` table, its per-track side tables (``segment_overrides``,
``lookup_cache``) and the library revision."""

from pathlib import Path

from .. import db as _db
from . import reading, writing


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
