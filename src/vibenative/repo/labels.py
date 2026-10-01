"""Blind genre labels (``genre_labels``, db._migration_12): a genre a person chose
on the /label page without seeing the model's read -- the benchmark's ground
truth. Nothing here reads or returns the payload, on purpose: the page is blind
because its API never has the read to give away."""

import time

from . import reading, writing


def next_unlabelled(skip=()):
    """(hash, title, filename, tag_artist, filepath) of a random library track
    with a file path recorded and no blind label yet, not in ``skip`` -- or None.
    Whether the file is still there is the caller's check (disk I/O stays out of
    the repository).

    Random rather than in library order, so ~200 labels are a sample of the
    library and not of whatever was analysed first."""
    skip = [h for h in skip if h]
    marks = ",".join("?" * len(skip))
    not_skipped = f"AND t.hash NOT IN ({marks}) " if skip else ""
    with reading() as c:
        return c.execute(
            "SELECT t.hash, t.title, t.filename, t.tag_artist, t.filepath FROM tracks t "
            "LEFT JOIN genre_labels g ON g.hash = t.hash "
            f"WHERE g.hash IS NULL AND t.filepath != '' {not_skipped}"  # nosec B608  # only ? marks
            "ORDER BY random() LIMIT 1",
            skip,
        ).fetchone()


def put(h: str, genre: str, source: str = "blind") -> bool:
    """Record (or replace) track ``h``'s blind label. False if ``h`` isn't a
    library track -- a label for nothing would only surface as an orphan row."""
    with writing() as c:
        if not c.execute("SELECT 1 FROM tracks WHERE hash=?", (h,)).fetchone():
            return False
        c.execute(
            "INSERT OR REPLACE INTO genre_labels(hash, genre, source, created) VALUES(?,?,?,?)",
            (h, genre, source, time.time()),
        )
    return True


def delete(h: str) -> int:
    with writing() as c:
        return c.execute("DELETE FROM genre_labels WHERE hash=?", (h,)).rowcount


def count() -> int:
    with reading() as c:
        return c.execute("SELECT COUNT(*) FROM genre_labels").fetchone()[0]


def recent(limit: int = 20):
    """[(hash, title, filename, tag_artist, genre, created)], newest first."""
    with reading() as c:
        return c.execute(
            "SELECT g.hash, t.title, t.filename, t.tag_artist, g.genre, g.created "
            "FROM genre_labels g JOIN tracks t ON t.hash = g.hash "
            "ORDER BY g.created DESC LIMIT ?",
            (limit,),
        ).fetchall()
