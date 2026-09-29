"""Tag routes: manual designations ("high energy", "opener"...) attached to tracks."""

from flask import jsonify, request

from ..repo import tags as tags_repo
from ._shared import bp


@bp.get("/tags")
def tags_list():
    rows = tags_repo.all_with_counts()
    return jsonify([{"id": r[0], "name": r[1], "count": r[2]} for r in rows])


@bp.post("/tags")
def tags_create():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    return jsonify({"id": tags_repo.get_or_create(name), "name": name})


@bp.post("/tags/toggle")
def tags_toggle():
    """Add the tag to the track if absent, remove it if present."""
    data = request.get_json(silent=True) or {}
    tid, h = data.get("tag_id"), data.get("hash")
    if not tid or not h:
        return jsonify({"error": "tag_id and hash required"}), 400
    return jsonify({"tagged": tags_repo.toggle(tid, h)})


def _hashes_arg():
    """The ``hashes`` query parameter as a de-duplicated list."""
    raw = request.args.get("hashes", "")
    seen, out = set(), []
    for h in raw.split(","):
        h = h.strip()
        if h and h not in seen:
            seen.add(h)
            out.append(h)
    return out


@bp.get("/tags/for/<h>")
def tags_for(h):
    return jsonify(tags_repo.for_hashes([h])[h])


@bp.get("/tags/for")
def tags_for_batch():
    """``?hashes=a,b,c`` -> ``{hash: [{id, name}, ...]}``.

    The Analyzer asks for every row that scrolls into view together; one
    request for the lot instead of one per row.
    """
    return jsonify(tags_repo.for_hashes(_hashes_arg()))
