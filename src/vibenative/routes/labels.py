"""Blind labelling routes, behind the /label page.

The page picks a genre for a track while the model's read stays hidden, so the
labels can benchmark the model instead of echoing it (an override or a weight
adjustment is chosen looking at the read). Blind by construction: no response
here carries anything from the payload -- no style, read, score, BPM or key --
and the page calls nothing but these routes and /audio. ``tests/test_labels.py``
pins both.

``?order=contested`` serves first the tracks whose file tag and the model's own
read disagree (tagcheck.contested_order), so a label lands where it settles
something. The read decides only which track comes next; the response is the
same three fields. A label saved in that mode is stored with source
``blind-contested``, so the benchmark can tell that sample from the random one.
"""

import json
import threading
from pathlib import Path

from flask import jsonify, request

from ..repo import labels as labels_repo
from ..repo import tracks as tracks_repo
from ..tagcheck import contested_order
from ..taxonomy.classify import discogs_labels, style_keystones
from ._shared import bp

# A label is a genre name, not a note; the longest of the 400 styles is ~25.
MAX_GENRE = 80

# Tracks whose recorded file is gone are passed over, this many at most per
# request. On the local library 1,730 of 4,584 recorded paths still exist, so a
# random pick misses ~60% of the time; 50 misses in a row is (0.6^50) never,
# unless almost nothing is left to play.
MAX_MISSES = 50


# The contested order costs a pass over every payload (~3 s on 6,000 tracks), so
# it is kept until the library or the taxonomy changes: keyed on the database,
# its revision (bumped on every write to tracks) and the taxonomy overlay file.
_contested = {"key": None, "order": []}
_contested_lock = threading.Lock()


def _contested_key():
    from ..settings import current
    from ..taxonomy.overlay import path as taxonomy_path

    try:
        st = taxonomy_path().stat()
        overlay = (st.st_mtime_ns, st.st_size)
    except OSError:
        overlay = None
    return (str(current().db_path), tracks_repo.library_rev(), overlay)


def _contested_hashes():
    key = _contested_key()
    with _contested_lock:
        if _contested["key"] != key:
            rows = ((h, json.loads(p) if p else {}) for h, p in tracks_repo.hash_payloads())
            _contested.update(key=key, order=contested_order(rows))
        return _contested["order"]


def _track(row):
    """The fields a blind card may show: who and what, never how it reads."""
    h, title, filename, artist = row[:4]
    return {"hash": h, "title": title or filename or h, "artist": artist or ""}


def _next_contested(skip):
    """(row, left): the first unlabelled contested track with its file on disk,
    and how many unlabelled contested tracks there are, playable or not."""
    done = labels_repo.labelled()
    queue = [h for h in _contested_hashes() if h not in done]
    passed = set(skip)
    for h in queue:
        if h in passed:
            continue
        row = labels_repo.card(h)
        if row and row[4] and Path(row[4]).is_file():
            return row, len(queue)
    return None, len(queue)


@bp.get("/labels/next")
def labels_next():
    """A random unlabelled track; ``?skip=h1,h2`` leaves out ones passed over.
    ``?order=contested``: the next contested one instead, plus ``contested_left``."""
    skip = [s.strip() for s in request.args.get("skip", "").split(",") if s.strip()][:500]
    if request.args.get("order") == "contested":
        row, left = _next_contested(skip)
        return jsonify(
            {
                "track": _track(row) if row else None,
                "labelled": labels_repo.count(),
                "contested_left": left,
            }
        )
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
    body = request.get_json(silent=True) or {}
    genre = " ".join(str(body.get("genre") or "").split())
    if not genre:
        return jsonify({"error": "genre required"}), 400
    if len(genre) > MAX_GENRE:
        return jsonify({"error": f"genre is longer than {MAX_GENRE} characters"}), 400
    source = "blind-contested" if body.get("order") == "contested" else "blind"
    if not labels_repo.put(h, genre, source):
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
