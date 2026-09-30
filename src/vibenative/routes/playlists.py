"""Saved (named) playlist routes: durable, named snapshots of a playlist's track
list (the live working playlist stays client-side). Backed by the playlists table."""

import json

from flask import jsonify, request

from ..config import log
from ..names import safe_name
from ..repo import playlists as playlists_repo
from ..repo import tracks as tracks_repo
from ._shared import bp


@bp.get("/playlists")
def playlists_list():
    """List saved playlists (id, name, track count, last-updated), newest first."""
    rows = playlists_repo.listing()
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
    pid = playlists_repo.save(name, tracks)
    return jsonify({"id": pid, "name": name, "count": len(tracks)})


@bp.get("/playlists/<int:pid>")
def playlists_get(pid):
    """Return a saved playlist's track list."""
    row = playlists_repo.get(pid)
    if not row:
        return jsonify({"error": "playlist not found"}), 404
    try:
        tracks = json.loads(row[1]) if row[1] else []
    except ValueError:
        tracks = []
    return jsonify({"id": pid, "name": row[0], "tracks": tracks})


@bp.delete("/playlists/<int:pid>")
def playlists_delete(pid):
    """Delete a saved playlist."""
    return jsonify({"deleted": playlists_repo.delete(pid)})


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


@bp.get("/ratings")
def ratings_all():
    """Every rated track, as {hash: rating} -- see ratings.all_tracks."""
    from .. import ratings

    return jsonify(ratings.all_tracks())


@bp.get("/artist-ratings")
def artist_ratings_all():
    """Every rated artist, best first.

    One request, not one per star: the map sizes thousands of points by their
    artist's rating, and a per-track lookup there would be a request storm.
    """
    from .. import ratings

    return jsonify(ratings.artist_all())


@bp.get("/artist-ratings/<path:name>")
def artist_rating_get(name):
    """One artist's rating (stars / grade / note).

    ``path:`` rather than the default string converter so names containing a
    slash -- "AC/DC", and every "A / B" collaboration credit -- resolve instead
    of 404ing.
    """
    from .. import ratings

    return jsonify(ratings.artist_get(name))


@bp.post("/artist-ratings/<path:name>")
def artist_rating_put(name):
    """Set an artist's rating. Only the fields present in the body change, so
    the map's star widget can't clobber a note written elsewhere."""
    from .. import ratings

    d = request.get_json(silent=True) or {}
    try:
        return jsonify(
            ratings.artist_put(
                name,
                stars=d.get("stars"),
                grade=d.get("grade"),
                note=d.get("note"),
            )
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


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

    row = playlists_repo.get(pid)
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
    # A hash dropped from the library since the playlist was saved is skipped.
    for t in tracks_repo.export_rows(hashes):
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
    safe = safe_name(name or "playlist")
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
