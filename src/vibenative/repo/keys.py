"""Corrected keys (``key_labels``): a person's fix for the detector's key, kept
out of the payload so it outlives re-analysis (see db._migration_8)."""

import time

from . import reading, writing


def key_label_get(h: str):
    """The corrected (key, scale) for a track, or None."""
    with reading() as c:
        row = c.execute("SELECT key, scale FROM key_labels WHERE hash=?", (h,)).fetchone()
    return (row[0], row[1]) if row else None


def key_label_put(h: str, key: str, scale: str, source: str = "manual"):
    with writing() as c:
        c.execute(
            "INSERT OR REPLACE INTO key_labels(hash, key, scale, source, created) VALUES(?,?,?,?,?)",
            (h, key, scale, source, time.time()),
        )


def key_label_delete(h: str):
    """Drop a correction; the detector's own answer stands again."""
    with writing() as c:
        c.execute("DELETE FROM key_labels WHERE hash=?", (h,))


def key_labels_map():
    """{hash: (key, scale)} for every correction -- one query for a whole listing."""
    with reading() as c:
        return {r[0]: (r[1], r[2]) for r in c.execute("SELECT hash, key, scale FROM key_labels")}


def key_labels_all():
    """[(hash, filepath, key, scale)] for every corrected track that still has a
    file on disk recorded -- the training set tools/eval_key.py reads."""
    with reading() as c:
        return c.execute(
            "SELECT l.hash, t.filepath, l.key, l.scale FROM key_labels l "
            "JOIN tracks t ON t.hash = l.hash WHERE t.filepath != ''"
        ).fetchall()
