"""The ``tracks`` table, its per-track side tables (``segment_overrides``,
``lookup_cache``) and the library revision."""

from .. import db as _db
from . import reading


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
