"""Saved (named) playlist routes: durable, named snapshots of a playlist's track
list (the live working playlist stays client-side). Backed by the playlists table."""

import json
import time
from contextlib import closing

from flask import jsonify, request

from ..db import _db_lock, db
from ._shared import bp


@bp.get("/playlists")
def playlists_list():
    """List saved playlists (id, name, track count, last-updated), newest first."""
    with _db_lock, closing(db()) as conn, conn as c:
        rows = c.execute(
            "SELECT id, name, tracks, updated FROM playlists ORDER BY updated DESC"
        ).fetchall()
    out = []
    for pid, name, tracks, updated in rows:
        try:
            n = len(json.loads(tracks)) if tracks else 0
        except ValueError:
            n = 0
        out.append({"id": pid, "name": name, "count": n, "updated": updated})
    return jsonify(out)


@bp.post("/playlists")
def playlists_save():
    """Save (or overwrite by name) a named playlist. Body: {name, tracks:[...]}."""
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    tracks = data.get("tracks")
    if not name or not isinstance(tracks, list):
        return jsonify({"error": "name and a tracks list are required"}), 400
    blob = json.dumps(tracks)
    now = time.time()
    with _db_lock, closing(db()) as conn, conn as c:
        c.execute(
            "INSERT INTO playlists(name, tracks, created, updated) VALUES(?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET tracks=excluded.tracks, updated=excluded.updated",
            (name, blob, now, now),
        )
        pid = c.execute("SELECT id FROM playlists WHERE name=?", (name,)).fetchone()[0]
    return jsonify({"id": pid, "name": name, "count": len(tracks)})


@bp.get("/playlists/<int:pid>")
def playlists_get(pid):
    """Return a saved playlist's track list."""
    with _db_lock, closing(db()) as conn, conn as c:
        row = c.execute("SELECT name, tracks FROM playlists WHERE id=?", (pid,)).fetchone()
    if not row:
        return jsonify({"error": "playlist not found"}), 404
    try:
        tracks = json.loads(row[1]) if row[1] else []
    except ValueError:
        tracks = []
    return jsonify({"id": pid, "name": row[0], "tracks": tracks})


@bp.post("/playlists/<int:pid>/delete")
def playlists_delete(pid):
    """Delete a saved playlist."""
    with _db_lock, closing(db()) as conn, conn as c:
        n = c.execute("DELETE FROM playlists WHERE id=?", (pid,)).rowcount
    return jsonify({"deleted": bool(n)})
