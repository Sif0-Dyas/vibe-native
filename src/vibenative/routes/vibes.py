"""Vibe routes: CRUD, weighted membership (Rocchio relevance feedback), JSON
export/import, and similarity (match a track / rank the library) over the cached
1280-d track embeddings."""

import json
import sqlite3
from contextlib import closing

from flask import jsonify, request

from ..db import _db_lock, cosine, db, track_embedding, vibe_centroid
from ._shared import bp


@bp.get("/vibes")
def vibes_list():
    with _db_lock, closing(db()) as conn, conn as c:
        rows = c.execute(
            "SELECT v.id, v.name, COUNT(t.hash), COALESCE(v.description, '') FROM vibes v "
            "LEFT JOIN vibe_tracks t ON t.vibe_id = v.id "
            "GROUP BY v.id ORDER BY v.name"
        ).fetchall()
    return jsonify([{"id": r[0], "name": r[1], "count": r[2], "description": r[3]} for r in rows])


@bp.post("/vibes")
def vibes_create():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    try:
        with _db_lock, closing(db()) as conn, conn as c:
            cur = c.execute("INSERT INTO vibes(name) VALUES(?)", (name,))
            vid = cur.lastrowid
        return jsonify({"id": vid, "name": name})
    except sqlite3.IntegrityError:
        return jsonify({"error": "a vibe with that name already exists"}), 409


def _upsert_vibe_weight(vid, h, weight):
    """Insert or update a track's weight within a vibe (shared by add + weight)."""
    with _db_lock, closing(db()) as conn, conn as c:
        c.execute(
            "INSERT INTO vibe_tracks(vibe_id, hash, weight) VALUES(?,?,?) "
            "ON CONFLICT(vibe_id, hash) DO UPDATE SET weight=excluded.weight",
            (vid, h, weight),
        )


@bp.post("/vibes/add")
def vibes_add():
    data = request.get_json(silent=True) or {}
    vid, h = data.get("vibe_id"), data.get("hash")
    if not vid or not h:
        return jsonify({"error": "vibe_id and hash required"}), 400
    weight = max(-1.0, min(1.0, float(data.get("weight", 1.0))))
    _upsert_vibe_weight(vid, h, weight)
    return jsonify({"added": True, "weight": weight})


@bp.post("/vibes/weight")
def vibes_weight():
    """Set a track's weight within a vibe (Rocchio feedback). Positive pulls the
    vibe toward the track, negative pushes it away, 0 is a neutral member. This is
    what the per-song 👍/👎 and the slider editor both call. Upserts the link."""
    data = request.get_json(silent=True) or {}
    vid, h = data.get("vibe_id"), data.get("hash")
    if not vid or not h:
        return jsonify({"error": "vibe_id and hash required"}), 400
    try:
        weight = float(data.get("weight", 1.0))
    except (TypeError, ValueError):
        return jsonify({"error": "weight must be a number"}), 400
    weight = max(-1.0, min(1.0, weight))
    _upsert_vibe_weight(vid, h, weight)
    return jsonify({"vibe_id": vid, "hash": h, "weight": weight})


@bp.post("/vibes/remove")
def vibes_remove():
    """Remove a track from a vibe entirely (drop the membership link)."""
    data = request.get_json(silent=True) or {}
    vid, h = data.get("vibe_id"), data.get("hash")
    if not vid or not h:
        return jsonify({"error": "vibe_id and hash required"}), 400
    with _db_lock, closing(db()) as conn, conn as c:
        c.execute("DELETE FROM vibe_tracks WHERE vibe_id=? AND hash=?", (vid, h))
    return jsonify({"removed": True})


@bp.post("/vibes/rename")
def vibes_rename():
    """Rename a vibe."""
    data = request.get_json(silent=True) or {}
    vid = data.get("vibe_id")
    name = (data.get("name") or "").strip()
    if not vid or not name:
        return jsonify({"error": "vibe_id and name required"}), 400
    try:
        with _db_lock, closing(db()) as conn, conn as c:
            n = c.execute("UPDATE vibes SET name=? WHERE id=?", (name, vid)).rowcount
    except sqlite3.IntegrityError:
        return jsonify({"error": "a vibe with that name already exists"}), 409
    if not n:
        return jsonify({"error": "vibe not found"}), 404
    return jsonify({"id": vid, "name": name})


@bp.post("/vibes/reset")
def vibes_reset():
    """Reset every member track's weight in a vibe back to the default 1.0 (keeps the
    members; just undoes any Rocchio +/- tuning)."""
    data = request.get_json(silent=True) or {}
    vid = data.get("vibe_id")
    if not vid:
        return jsonify({"error": "vibe_id required"}), 400
    with _db_lock, closing(db()) as conn, conn as c:
        n = c.execute("UPDATE vibe_tracks SET weight=1.0 WHERE vibe_id=?", (vid,)).rowcount
    return jsonify({"reset": True, "tracks": n})


@bp.post("/vibes/clear")
def vibes_clear():
    """Remove ALL tracks from a vibe (keeps the empty vibe itself)."""
    data = request.get_json(silent=True) or {}
    vid = data.get("vibe_id")
    if not vid:
        return jsonify({"error": "vibe_id required"}), 400
    with _db_lock, closing(db()) as conn, conn as c:
        n = c.execute("DELETE FROM vibe_tracks WHERE vibe_id=?", (vid,)).rowcount
    return jsonify({"cleared": True, "removed": n})


@bp.post("/vibes/delete")
def vibes_delete():
    """Delete a vibe entirely, along with all of its membership links."""
    data = request.get_json(silent=True) or {}
    vid = data.get("vibe_id")
    if not vid:
        return jsonify({"error": "vibe_id required"}), 400
    with _db_lock, closing(db()) as conn, conn as c:
        c.execute("DELETE FROM vibe_tracks WHERE vibe_id=?", (vid,))
        n = c.execute("DELETE FROM vibes WHERE id=?", (vid,)).rowcount
    return jsonify({"deleted": bool(n)})


@bp.get("/vibes/export")
def vibes_export():
    """Export every vibe + its member tracks (content hash + weight) as JSON, for
    backup, sharing, or moving to another machine."""
    with _db_lock, closing(db()) as conn, conn as c:
        vibes = c.execute("SELECT id, name FROM vibes ORDER BY name").fetchall()
        out = []
        for vid, name in vibes:
            members = c.execute(
                "SELECT hash, weight FROM vibe_tracks WHERE vibe_id=?", (vid,)
            ).fetchall()
            out.append(
                {
                    "name": name,
                    "tracks": [{"hash": h, "weight": 1.0 if w is None else w} for h, w in members],
                }
            )
    return jsonify({"kind": "vibenative-vibes", "version": 1, "vibes": out})


@bp.post("/vibes/import")
def vibes_import():
    """Import vibes from a /vibes/export file. Each vibe is created if new, or merged
    into an existing same-named vibe; member tracks (by hash + weight) are upserted.
    Memberships referencing tracks not yet in this DB are still stored — they start
    contributing once those tracks are analyzed here."""
    data = request.get_json(silent=True) or {}
    vibes = data.get("vibes")
    if not isinstance(vibes, list):
        return jsonify({"error": "expected a vibenative vibes export (a 'vibes' list)"}), 400
    created = merged = links = 0
    with _db_lock, closing(db()) as conn, conn as c:
        for v in vibes:
            name = (v.get("name") or "").strip() if isinstance(v, dict) else ""
            if not name:
                continue
            row = c.execute("SELECT id FROM vibes WHERE name=?", (name,)).fetchone()
            if row:
                vid = row[0]
                merged += 1
            else:
                vid = c.execute("INSERT INTO vibes(name) VALUES(?)", (name,)).lastrowid
                created += 1
            for t in v.get("tracks") or []:
                h = t.get("hash") if isinstance(t, dict) else None
                if not h:
                    continue
                try:
                    w = max(-1.0, min(1.0, float(t.get("weight", 1.0))))
                except (TypeError, ValueError):
                    w = 1.0
                c.execute(
                    "INSERT INTO vibe_tracks(vibe_id, hash, weight) VALUES(?,?,?) "
                    "ON CONFLICT(vibe_id, hash) DO UPDATE SET weight=excluded.weight",
                    (vid, h, w),
                )
                links += 1
    return jsonify({"ok": True, "created": created, "merged": merged, "tracks": links})


@bp.get("/vibes/<int:vid>/members")
def vibes_members(vid):
    """Member tracks of a vibe with their current weights, for the weight editor.
    Ordered strongest-pull first."""
    with _db_lock, closing(db()) as conn, conn as c:
        rows = c.execute(
            "SELECT vt.hash, vt.weight, t.title, t.filename FROM vibe_tracks vt "
            "LEFT JOIN tracks t ON t.hash=vt.hash WHERE vt.vibe_id=? "
            "ORDER BY vt.weight DESC",
            (vid,),
        ).fetchall()
    return jsonify(
        [
            {
                "hash": r[0],
                "weight": 1.0 if r[1] is None else round(float(r[1]), 3),
                "title": r[2],
                "filename": r[3],
            }
            for r in rows
        ]
    )


@bp.get("/vibes/membership")
def vibes_membership():
    """Every vibe with the hashes of its member tracks, in one request.

    The map's Universe view can cluster by vibe, which means it needs the whole
    membership table before it can lay out a single frame. Walking
    ``/vibes/<id>/members`` per vibe would be one request per vibe on every map
    open; this is one query total.

    Returns hashes only -- no titles, no weights. The map already holds every
    track it draws and looks them up by hash, so anything more would be payload
    it throws away.
    """
    with _db_lock, closing(db()) as conn, conn as c:
        rows = c.execute(
            "SELECT v.id, v.name, vt.hash FROM vibes v "
            "LEFT JOIN vibe_tracks vt ON vt.vibe_id = v.id ORDER BY v.name"
        ).fetchall()
    out, order = {}, []
    for vid, name, h in rows:
        if vid not in out:
            out[vid] = {"id": vid, "name": name, "hashes": []}
            order.append(vid)
        if h:
            out[vid]["hashes"].append(h)
    return jsonify([out[v] for v in order])


@bp.get("/vibes/match/<h>")
def vibes_match(h):
    """Similarity of one track against every vibe's centroid."""
    emb = track_embedding(h)
    if emb is None:
        return jsonify({"error": "track not in database"}), 404
    with _db_lock, closing(db()) as conn, conn as c:
        vibes = c.execute("SELECT id, name FROM vibes").fetchall()
    out = []
    for vid, name in vibes:
        cen = vibe_centroid(vid)
        if cen is None:
            continue
        out.append({"id": vid, "name": name, "sim": round(cosine(emb, cen), 4)})
    out.sort(key=lambda x: -x["sim"])
    return jsonify(out)


@bp.get("/vibes/<int:vid>/playlist")
def vibes_playlist(vid):
    """All cached tracks ranked by similarity to this vibe's centroid."""
    cen = vibe_centroid(vid)
    if cen is None:
        return jsonify({"error": "vibe has no member tracks yet"}), 404
    threshold = float(request.args.get("threshold", 0.60))
    import numpy as np

    with _db_lock, closing(db()) as conn, conn as c:
        rows = c.execute(
            "SELECT hash, title, filename, payload, embedding FROM tracks "
            "WHERE embedding IS NOT NULL"
        ).fetchall()
        members = {
            r[0]
            for r in c.execute("SELECT hash FROM vibe_tracks WHERE vibe_id=?", (vid,)).fetchall()
        }
    out = []
    for h, title, filename, payload, blob in rows:
        emb = np.frombuffer(blob, dtype=np.float32)
        sim = cosine(emb, cen)
        if sim < threshold:
            continue
        p = json.loads(payload)
        out.append(
            {
                "hash": h,
                "title": title,
                "filename": filename,
                "sim": round(sim, 4),
                "member": h in members,
                "bpm": p.get("bpm"),
                "camelot": p.get("camelot"),
                "duration": p.get("duration"),
            }
        )
    out.sort(key=lambda x: -x["sim"])
    return jsonify(out)


@bp.post("/vibes/<int:vid>/description")
def vibes_description(vid):
    """Set a vibe's description.

    Free-form and unbounded: a vibe is your own category, and the notes about
    what belongs in it are worth as much room as they need. Stored verbatim
    apart from stripping surrounding whitespace -- no length cap, no
    reformatting, so paragraphs and line breaks survive a round trip.
    """
    data = request.get_json(silent=True) or {}
    if "description" not in data:
        return jsonify({"error": "description required"}), 400
    text = str(data.get("description") or "").strip()
    with _db_lock, closing(db()) as conn, conn as c:
        n = c.execute("UPDATE vibes SET description=? WHERE id=?", (text, vid)).rowcount
    if not n:
        return jsonify({"error": "vibe not found"}), 404
    return jsonify({"ok": True, "id": vid, "description": text, "length": len(text)})
