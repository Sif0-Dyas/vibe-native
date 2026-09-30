"""The repository layer: the SQL the routes need, behind plain functions.

Routes call these and never see a connection or the write lock. A read uses this
thread's connection (``db.db()``); a write also holds ``db._db_lock`` for its
whole block, so a read-modify-write inside one function is atomic against every
other writer.

One module per group of tables: ``tracks`` (tracks and its per-track side tables),
``tags``, ``vibes``, ``playlists``, ``training`` (labels and rejects).
"""

from contextlib import closing, contextmanager

from ..db import _db_lock, db


class NotFound(LookupError):
    """The row a write needs (a track, an override...) isn't there."""


@contextmanager
def reading():
    """A cursor for reads: no lock (WAL lets reads run beside a writer)."""
    with closing(db()) as conn, conn as c:
        yield c


@contextmanager
def writing():
    """A cursor holding the write lock, in one transaction: commit on success,
    rollback on an exception. Never hold it across disk, network or subprocess
    I/O -- do that before or after."""
    with _db_lock, closing(db()) as conn, conn as c:
        yield c
