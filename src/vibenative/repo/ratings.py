"""Track and artist ratings (``ratings``, ``artist_ratings``). Rows only: what a
rating is -- the clamp, the grades, the note cap -- lives in vibenative.ratings."""

import time

from . import reading, writing


def get(hash_):
    """(stars, grade, note) for one track, or None."""
    with reading() as c:
        return c.execute("SELECT stars, grade, note FROM ratings WHERE hash=?", (hash_,)).fetchone()


def all_rows():
    """[(hash, stars, grade, note)] for every rated track."""
    with reading() as c:
        return c.execute("SELECT hash, stars, grade, note FROM ratings").fetchall()


def rows_for(hashes):
    """[(hash, stars, grade, note)] for the rated ones among ``hashes``; chunked so
    a huge library can't blow SQLite's variable limit (999)."""
    out = []
    with reading() as c:
        for i in range(0, len(hashes), 500):
            chunk = hashes[i : i + 500]
            q = ",".join("?" * len(chunk))
            out += c.execute(
                f"SELECT hash, stars, grade, note FROM ratings WHERE hash IN ({q})",  # nosec B608
                chunk,
            ).fetchall()
    return out


def update(hash_, merge):
    """Read one track's rating, ``merge`` it, write the result -- one locked
    transaction, so two partial updates at once (stars from the map, a note from
    the library) both land instead of the later one writing back a stale copy of
    the other's field.

    ``merge((stars, grade, note) or None)`` returns the new (stars, grade, note);
    it runs under the write lock, so keep it to in-memory work."""
    with writing() as c:
        row = c.execute("SELECT stars, grade, note FROM ratings WHERE hash=?", (hash_,)).fetchone()
        stars, grade, note = merge(row)
        c.execute(
            "INSERT INTO ratings(hash, stars, grade, note, updated) VALUES(?,?,?,?,?) "
            "ON CONFLICT(hash) DO UPDATE SET stars=excluded.stars, grade=excluded.grade, "
            "note=excluded.note, updated=excluded.updated",
            (hash_, stars, grade, note, time.time()),
        )
    return stars, grade, note


def artist_rows_for(keys):
    """[(artist_key, display, stars, grade, note)] for the rated ones among ``keys``,
    chunked exactly as :func:`rows_for` is."""
    out = []
    with reading() as c:
        for i in range(0, len(keys), 500):
            chunk = keys[i : i + 500]
            q = ",".join("?" * len(chunk))
            out += c.execute(
                f"SELECT artist_key, display, stars, grade, note FROM artist_ratings "  # nosec B608
                f"WHERE artist_key IN ({q})",
                chunk,
            ).fetchall()
    return out


def artist_update(key, merge):
    """:func:`update` for an artist: ``merge((display, stars, grade, note) or
    None)`` returns the new (display, stars, grade, note), read and written in
    one locked transaction."""
    with writing() as c:
        row = c.execute(
            "SELECT display, stars, grade, note FROM artist_ratings WHERE artist_key=?", (key,)
        ).fetchone()
        display, stars, grade, note = merge(row)
        c.execute(
            "INSERT INTO artist_ratings(artist_key, display, stars, grade, note, updated) "
            "VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(artist_key) DO UPDATE SET display=excluded.display, "
            "stars=excluded.stars, grade=excluded.grade, note=excluded.note, "
            "updated=excluded.updated",
            (key, display, stars, grade, note, time.time()),
        )
    return display, stars, grade, note


def artist_all_rows():
    """[(artist_key, display, stars, grade, note)], best first."""
    with reading() as c:
        return c.execute(
            "SELECT artist_key, display, stars, grade, note FROM artist_ratings "
            "ORDER BY stars DESC, display COLLATE NOCASE"
        ).fetchall()
