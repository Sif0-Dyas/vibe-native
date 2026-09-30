"""Saved, named playlists (``playlists``). The track list is stored as JSON; the
callers parse it, since what to do with a corrupt one is theirs to decide."""

import json
import time

from . import reading, writing


def listing():
    """[(id, name, tracks JSON, updated)] for every playlist, newest first."""
    with reading() as c:
        return c.execute(
            "SELECT id, name, tracks, updated FROM playlists ORDER BY updated DESC"
        ).fetchall()


def save(name, tracks) -> int:
    """Create the playlist ``name``, or overwrite its tracks if it exists; its id."""
    blob = json.dumps(tracks)
    now = time.time()
    with writing() as c:
        c.execute(
            "INSERT INTO playlists(name, tracks, created, updated) VALUES(?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET tracks=excluded.tracks, updated=excluded.updated",
            (name, blob, now, now),
        )
        return c.execute("SELECT id FROM playlists WHERE name=?", (name,)).fetchone()[0]


def get(pid):
    """(name, tracks JSON) for playlist ``pid``, or None."""
    with reading() as c:
        return c.execute("SELECT name, tracks FROM playlists WHERE id=?", (pid,)).fetchone()


def delete(pid) -> bool:
    """Delete playlist ``pid``; True if there was one."""
    with writing() as c:
        return bool(c.execute("DELETE FROM playlists WHERE id=?", (pid,)).rowcount)
