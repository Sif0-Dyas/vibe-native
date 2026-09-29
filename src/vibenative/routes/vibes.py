"""Vibe routes: CRUD, weighted membership (Rocchio relevance feedback), JSON
export/import, and similarity (match a track / rank the library) over the cached
1280-d track embeddings."""

import json

import numpy as np
from flask import jsonify, request

from ..repo import tracks as tracks_repo
from ..repo import vibes as vibes_repo
from ..repo.tracks import cosine, track_embedding
from ..repo.vibes import vibe_centroid
from ._shared import bp


@bp.get("/vibes")
def vibes_list():
    rows = vibes_repo.all_with_counts()
    return jsonify([{"id": r[0], "name": r[1], "count": r[2], "description": r[3]} for r in rows])


@bp.post("/vibes")
def vibes_create():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    try:
        vid = vibes_repo.create(name)
    except vibes_repo.NameTaken:
        return jsonify({"error": "a vibe with that name already exists"}), 409
    return jsonify({"id": vid, "name": name})


@bp.post("/vibes/add")
def vibes_add():
    data = request.get_json(silent=True) or {}
    vid, h = data.get("vibe_id"), data.get("hash")
    if not vid or not h:
        return jsonify({"error": "vibe_id and hash required"}), 400
    weight = max(-1.0, min(1.0, float(data.get("weight", 1.0))))
    vibes_repo.set_weight(vid, h, weight)
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
    vibes_repo.set_weight(vid, h, weight)
    return jsonify({"vibe_id": vid, "hash": h, "weight": weight})


@bp.post("/vibes/remove")
def vibes_remove():
    """Remove a track from a vibe entirely (drop the membership link)."""
    data = request.get_json(silent=True) or {}
    vid, h = data.get("vibe_id"), data.get("hash")
    if not vid or not h:
        return jsonify({"error": "vibe_id and hash required"}), 400
    vibes_repo.remove(vid, h)
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
        n = vibes_repo.rename(vid, name)
    except vibes_repo.NameTaken:
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
    n = vibes_repo.reset_weights(vid)
    return jsonify({"reset": True, "tracks": n})


@bp.post("/vibes/clear")
def vibes_clear():
    """Remove ALL tracks from a vibe (keeps the empty vibe itself)."""
    data = request.get_json(silent=True) or {}
    vid = data.get("vibe_id")
    if not vid:
        return jsonify({"error": "vibe_id required"}), 400
    n = vibes_repo.clear(vid)
    return jsonify({"cleared": True, "removed": n})


@bp.post("/vibes/delete")
def vibes_delete():
    """Delete a vibe entirely, along with all of its membership links."""
    data = request.get_json(silent=True) or {}
    vid = data.get("vibe_id")
    if not vid:
        return jsonify({"error": "vibe_id required"}), 400
    return jsonify({"deleted": vibes_repo.delete(vid)})


@bp.get("/vibes/export")
def vibes_export():
    """Export every vibe + its member tracks (content hash + weight) as JSON, for
    backup, sharing, or moving to another machine."""
    out = [
        {
            "name": name,
            "tracks": [{"hash": h, "weight": 1.0 if w is None else w} for h, w in members],
        }
        for name, members in vibes_repo.export()
    ]
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
    # Validate the file first; the repo then merges it under one lock.
    clean = []
    for v in vibes:
        name = (v.get("name") or "").strip() if isinstance(v, dict) else ""
        if not name:
            continue
        tracks = []
        for t in v.get("tracks") or []:
            h = t.get("hash") if isinstance(t, dict) else None
            if not h:
                continue
            try:
                w = max(-1.0, min(1.0, float(t.get("weight", 1.0))))
            except (TypeError, ValueError):
                w = 1.0
            tracks.append((h, w))
        clean.append((name, tracks))
    created, merged, links = vibes_repo.import_(clean)
    return jsonify({"ok": True, "created": created, "merged": merged, "tracks": links})


@bp.get("/vibes/<int:vid>/members")
def vibes_members(vid):
    """Member tracks of a vibe with their current weights, for the weight editor.
    Ordered strongest-pull first."""
    rows = vibes_repo.members(vid)
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
    rows = vibes_repo.membership()
    out = {}
    for vid, name, h in rows:
        if vid not in out:
            out[vid] = {"id": vid, "name": name, "hashes": []}
        if h:
            out[vid]["hashes"].append(h)
    return jsonify(list(out.values()))


def _vibe_centroids():
    """[(id, name, centroid)] for every vibe that has one. Computed once per
    request: a centroid is a pass over the vibe's members, and asking for it
    per track would repeat that for every row on screen."""
    out = []
    for vid, name in vibes_repo.ids_and_names():
        cen = vibe_centroid(vid)
        if cen is not None:
            out.append((vid, name, cen))
    return out


def _matches(emb, centroids):
    out = [
        {"id": vid, "name": name, "sim": round(cosine(emb, cen), 4)} for vid, name, cen in centroids
    ]
    out.sort(key=lambda x: -x["sim"])
    return out


@bp.get("/vibes/match/<h>")
def vibes_match(h):
    """Similarity of one track against every vibe's centroid."""
    emb = track_embedding(h)
    if emb is None:
        return jsonify({"error": "track not in database"}), 404
    return jsonify(_matches(emb, _vibe_centroids()))


@bp.get("/vibes/match")
def vibes_match_batch():
    """``?hashes=a,b,c`` -> ``{hash: [{id, name, sim}, ...]}``.

    The Analyzer asks for every row that scrolls into view together: one
    request, the centroids computed once, and a track with no embedding is
    simply absent from the answer rather than a 404 for the lot.
    """
    from .tags import _hashes_arg

    hashes = _hashes_arg()
    if not hashes:
        return jsonify({})
    centroids = _vibe_centroids()
    out = {
        h: _matches(np.frombuffer(blob, dtype=np.float32), centroids)
        for h, blob in tracks_repo.embeddings_for(hashes).items()
    }
    return jsonify(out)


@bp.get("/vibes/<int:vid>/playlist")
def vibes_playlist(vid):
    """All cached tracks ranked by similarity to this vibe's centroid."""
    cen = vibe_centroid(vid)
    if cen is None:
        return jsonify({"error": "vibe has no member tracks yet"}), 404
    threshold = float(request.args.get("threshold", 0.60))
    rows = tracks_repo.embedded_rows()
    members = vibes_repo.member_hashes(vid)
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
    if not vibes_repo.set_description(vid, text):
        return jsonify({"error": "vibe not found"}), 404
    return jsonify({"ok": True, "id": vid, "description": text, "length": len(text)})
