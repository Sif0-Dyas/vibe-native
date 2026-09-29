"""Shared routing state: the Blueprint and the cross-domain helpers (used by
both the map and library routes). Request auth is app-wide, in ``auth.py``."""

from pathlib import Path

from flask import Blueprint, jsonify
from werkzeug.exceptions import HTTPException

from ..config import log
from ..db import artist_tag as _artist_tag
from ..style import ranked_read

bp = Blueprint("main", __name__)


class UploadError(Exception):
    """Bad/missing upload -- carries the HTTP status the route should return."""

    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


@bp.errorhandler(UploadError)
def _upload_error(e):
    return jsonify({"error": str(e)}), e.status


@bp.errorhandler(Exception)
def _unexpected_error(e):
    """Anything a route didn't handle: logged with its traceback, and a 500 that
    says nothing about the internals. HTTP errors (413 from MAX_CONTENT_LENGTH,
    405, abort()) are not failures -- they go back as themselves."""
    if isinstance(e, HTTPException):
        return e
    log.exception("request failed")
    return jsonify({"error": "internal error"}), 500


# ---------------------------------------------------------------------------
# Genre Map -- interactive constellation of the entire scanned library.
# /map returns every track + nearest-neighbour edges; /similar/<h> powers the
# popup. Both lean on the same 1280-d embeddings that drive vibes.
# ---------------------------------------------------------------------------
def _artist_of(payload, title, filename):
    """Best-effort artist: prefer the file's `artist` metadata tag (stored under
    payload['tags']['tag']); otherwise parse it out of an 'Artist - Title' name."""
    return _artist_from(_artist_tag(payload), title, filename)


def _artist_from(tagged, title, filename):
    """_artist_of without a payload: the tag artist already extracted (the
    ``tracks.tag_artist`` column), else parsed from an 'Artist - Title' name."""
    if tagged:
        return tagged
    base = (title or "") or (Path(filename).stem if filename else "")
    return base.split(" - ", 1)[0].strip() if " - " in base else ""


def _second_style(payload, top_style, top_score):
    """The runner-up style + its weight relative to the top read, for colour
    blending on the map (a track that's partly a 2nd genre leans toward its
    colour). Returns [style2, weight2] with weight2 in [0, 0.5], or None when
    there's an override or no distinct runner-up.

    Reads the same ranked read ``style.dominant_style`` does, so a track you've
    hand-weighted or relabelled leans toward the colour you gave it. Reading raw
    salience here left the dot's blend arguing with its own label."""
    if payload.get("override"):
        return None
    for s in ranked_read(payload):
        st, sc = s.get("style"), float(s.get("score", 0) or 0)
        if st and st != top_style and sc > 0:
            denom = (top_score or 0) + sc
            return [st, round(sc / denom, 3) if denom else 0.0]
    return None
