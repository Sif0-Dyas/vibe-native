"""Saved (named) playlist routes: durable, named snapshots of a playlist's track
list (the live working playlist stays client-side). Backed by the playlists table."""

import json
import time
from contextlib import closing

from flask import jsonify, request

from ..config import log
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


@bp.get("/ratings/<h>")
def rating_get(h):
    """One track's rating (stars / grade / note)."""
    from .. import ratings

    return jsonify(ratings.get(h))


@bp.post("/ratings/<h>")
def rating_put(h):
    """Set a track's rating. Only the fields present in the body change, so the
    map's star widget can't clobber a note written in the library view."""
    from .. import ratings

    d = request.get_json(silent=True) or {}
    return jsonify(
        ratings.put(
            h,
            stars=d.get("stars"),
            grade=d.get("grade"),
            note=d.get("note"),
        )
    )


@bp.get("/playlists/<int:pid>/rekordbox")
def playlist_rekordbox(pid):
    """Export a saved playlist as Rekordbox-importable collection XML.

    Ratings materialise here and nowhere else: stars become Rekordbox's 51-step
    Rating attribute and the grade + note become the Comments field. The audio
    files themselves are never touched.
    """
    from flask import Response

    from .. import ratings
    from ..routes._shared import _artist_of

    with _db_lock, closing(db()) as conn, conn as c:
        row = c.execute("SELECT name, tracks FROM playlists WHERE id=?", (pid,)).fetchone()
        if not row:
            return jsonify({"error": "playlist not found"}), 404
        name = row[0]
        try:
            entries = json.loads(row[1]) if row[1] else []
        except ValueError:
            entries = []
        hashes = [e if isinstance(e, str) else (e or {}).get("hash") for e in entries]
        hashes = [h for h in hashes if h]
        tracks = []
        for h in hashes:
            t = c.execute(
                "SELECT hash, title, filename, filepath, payload FROM tracks WHERE hash=?", (h,)
            ).fetchone()
            if not t:
                continue  # dropped from the library since the playlist was saved
            try:
                p = json.loads(t[4]) if t[4] else {}
            except ValueError:
                p = {}
            tracks.append(
                {
                    "hash": t[0],
                    "title": t[1] or t[2] or t[0][:8],
                    "artist": _artist_of(p, t[1], t[2]),
                    "filepath": t[3] or "",
                    "bpm": p.get("bpm"),
                    "key": p.get("key"),
                    "duration": p.get("duration"),
                }
            )

    xml = ratings.playlist_xml(name, tracks, ratings.get_many([t["hash"] for t in tracks]))
    exported = sum(1 for t in tracks if str(t.get("filepath") or "").strip())
    skipped = len(tracks) - exported
    if skipped:
        log.warning(
            "rekordbox export %r: %d of %d tracks omitted (no stored file path)",
            name,
            skipped,
            len(tracks),
        )
    safe = "".join(ch if ch.isalnum() or ch in " _-" else "_" for ch in (name or "playlist"))
    return Response(
        xml,
        mimetype="application/xml",
        headers={
            "Content-Disposition": f'attachment; filename="{safe.strip() or "playlist"}.xml"',
            # so the UI can warn instead of the user discovering it in Rekordbox
            "X-Exported": str(exported),
            "X-Skipped-No-Path": str(skipped),
        },
    )
