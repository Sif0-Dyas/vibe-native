"""Blind labelling routes, behind the /label page.

The page picks a genre for a track while the model's read stays hidden, so the
labels can benchmark the model instead of echoing it (an override or a weight
adjustment is chosen looking at the read). Blind by construction: no response
here carries anything from the payload -- no style, read, score, BPM or key --
and the page calls nothing but these routes and /audio. ``tests/test_labels.py``
pins both.
"""

from pathlib import Path

from flask import jsonify, request

from ..repo import labels as labels_repo
from ..taxonomy.classify import discogs_labels, style_keystones
from ._shared import bp

# A label is a genre name, not a note; the longest of the 400 styles is ~25.
MAX_GENRE = 80

# Tracks whose recorded file is gone are passed over, this many at most per
# request. On the local library 1,730 of 4,584 recorded paths still exist, so a
# random pick misses ~60% of the time; 50 misses in a row is (0.6^50) never,
# unless almost nothing is left to play.
MAX_MISSES = 50


def _track(row):
    """The fields a blind card may show: who and what, never how it reads."""
    h, title, filename, artist = row[:4]
    return {"hash": h, "title": title or filename or h, "artist": artist or ""}


@bp.get("/labels/next")
def labels_next():
    """A random unlabelled track; ``?skip=h1,h2`` leaves out ones passed over."""
    skip = [s.strip() for s in request.args.get("skip", "").split(",") if s.strip()][:500]
    row = None
    for _ in range(MAX_MISSES):
        row = labels_repo.next_unlabelled(skip)
        if row is None or Path(row[4]).is_file():
            break
        skip.append(row[0])  # moved or deleted: the page could not play it
        row = None
    return jsonify({"track": _track(row) if row else None, "labelled": labels_repo.count()})


@bp.get("/labels")
def labels_recent():
    limit = request.args.get("limit", 20, type=int) or 20
    rows = labels_repo.recent(max(1, min(limit, 200)))
    return jsonify(
        {
            "labelled": labels_repo.count(),
            "labels": [_track(r) | {"genre": r[4], "created": r[5]} for r in rows],
        }
    )


@bp.put("/labels/<h>")
def labels_put(h):
    genre = " ".join(str((request.get_json(silent=True) or {}).get("genre") or "").split())
    if not genre:
        return jsonify({"error": "genre required"}), 400
    if len(genre) > MAX_GENRE:
        return jsonify({"error": f"genre is longer than {MAX_GENRE} characters"}), 400
    if not labels_repo.put(h, genre):
        return jsonify({"error": "track not in database"}), 404
    return jsonify({"ok": True, "genre": genre, "labelled": labels_repo.count()})


@bp.delete("/labels/<h>")
def labels_delete(h):
    return jsonify({"deleted": labels_repo.delete(h), "labelled": labels_repo.count()})


@bp.get("/labels/vocabulary")
def labels_vocabulary():
    """The names to choose from: every keystone and the classifier's 400 styles.
    Deliberately not the library's own reads (/genres) -- a list of what this
    library was read as, ranked or not, is a hint about the answer."""
    names = set(style_keystones().values())
    try:
        names |= {lab.rpartition("---")[2] for lab in discogs_labels()}
    except FileNotFoundError:
        pass
    return jsonify(sorted(names, key=str.lower))
