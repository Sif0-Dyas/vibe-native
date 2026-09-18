"""Tag routes: manual designations ("high energy", "opener"...) attached to tracks."""

from contextlib import closing

from flask import jsonify, request

from ..db import _db_lock, db
from ._shared import bp


@bp.get("/tags")
def tags_list():
    with _db_lock, closing(db()) as conn, conn as c:
        rows = c.execute(
            "SELECT t.id, t.name, COUNT(tt.hash) FROM tags t "
            "LEFT JOIN track_tags tt ON tt.tag_id = t.id "
            "GROUP BY t.id ORDER BY t.name"
        ).fetchall()
    return jsonify([{"id": r[0], "name": r[1], "count": r[2]} for r in rows])


@bp.post("/tags")
def tags_create():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    with _db_lock, closing(db()) as conn, conn as c:
        row = c.execute("SELECT id FROM tags WHERE name=?", (name,)).fetchone()
        if row:
            return jsonify({"id": row[0], "name": name})
        cur = c.execute("INSERT INTO tags(name) VALUES(?)", (name,))
        return jsonify({"id": cur.lastrowid, "name": name})


@bp.post("/tags/toggle")
def tags_toggle():
    """Add the tag to the track if absent, remove it if present."""
    data = request.get_json(silent=True) or {}
    tid, h = data.get("tag_id"), data.get("hash")
    if not tid or not h:
        return jsonify({"error": "tag_id and hash required"}), 400
    with _db_lock, closing(db()) as conn, conn as c:
        row = c.execute("SELECT 1 FROM track_tags WHERE tag_id=? AND hash=?", (tid, h)).fetchone()
        if row:
            c.execute("DELETE FROM track_tags WHERE tag_id=? AND hash=?", (tid, h))
            return jsonify({"tagged": False})
        c.execute("INSERT OR IGNORE INTO track_tags VALUES(?,?)", (tid, h))
        return jsonify({"tagged": True})


def tags_for_many(hashes):
    """{hash: [{id, name}, ...]} for every hash given, in one query per 500.

    Every hash asked for is a key in the answer, tagged or not, so a caller
    can tell "no tags" from "not asked".
    """
    out = {h: [] for h in hashes}
    keys = list(out)
    with _db_lock, closing(db()) as conn, conn as c:
        for i in range(0, len(keys), 500):
            chunk = keys[i : i + 500]
            q = ",".join("?" * len(chunk))
            for h, tid, name in c.execute(
                f"SELECT tt.hash, t.id, t.name FROM track_tags tt JOIN tags t ON t.id=tt.tag_id "  # nosec B608
                f"WHERE tt.hash IN ({q}) ORDER BY t.name",
                chunk,
            ):
                out[h].append({"id": tid, "name": name})
    return out


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
    return jsonify(tags_for_many([h])[h])


@bp.get("/tags/for")
def tags_for_batch():
    """``?hashes=a,b,c`` -> ``{hash: [{id, name}, ...]}``.

    The Analyzer asks for every row that scrolls into view together; one
    request for the lot instead of one per row.
    """
    return jsonify(tags_for_many(_hashes_arg()))
