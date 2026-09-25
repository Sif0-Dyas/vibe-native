"""Shared routing state: the Blueprint and the cross-domain helpers (used by
both the map and library routes). Request auth is app-wide, in ``auth.py``."""

from pathlib import Path

from flask import Blueprint

bp = Blueprint("main", __name__)


# ---------------------------------------------------------------------------
# Genre Map -- interactive constellation of the entire scanned library.
# /map returns every track + nearest-neighbour edges; /similar/<h> powers the
# popup. Both lean on the same 1280-d embeddings that drive vibes.
# ---------------------------------------------------------------------------
def _artist_of(payload, title, filename):
    """Best-effort artist: prefer the file's `artist` metadata tag (stored under
    payload['tags']['tag']); otherwise parse it out of an 'Artist - Title' name."""
    tag = ((payload or {}).get("tags") or {}).get("tag") or {}
    tagged = (tag.get("artist") or tag.get("albumartist") or "").strip()
    if tagged:
        return tagged
    base = (title or "") or (Path(filename).stem if filename else "")
    return base.split(" - ", 1)[0].strip() if " - " in base else ""


def _dominant_style(payload):
    """The track's identity, by precedence:

    1. a manual override (POST /override) -- "it IS this", it wins outright;
    2. manual weight adjustments (``weights``) -- "it leans this way", the read
       nudged by hand; see ``vibenative.weights``;
    3. a retroactive re-label (``relabel``) -- a newer head's opinion, applied
       without re-scanning; see ``vibenative.relabel``;
    4. the salience read -- the energy/confidence/recurrence-weighted identity
       from the original analysis;
    5. the top flat style.

    Adjustments outrank both automatic reads because they are those reads with
    your judgement applied; an override outranks them only because it is the
    blunter statement. A re-label outranks salience because it is the *newer*
    judgement -- it exists only when a head has been trained since the track was
    analysed, and cannot be merged into salience, which needs per-frame
    predictions the database doesn't keep.

    Every tier leaves the ones beneath it intact, so any of them can be undone.
    """
    if payload.get("override"):
        return payload["override"], 1.0
    # Manual weight adjustments outrank any automatic read: they ARE the reads,
    # nudged by hand. They sit below a full override only because an override is
    # the blunter, more explicit statement -- "it is this", not "it leans this".
    ranked = _ranked_read(payload)
    if ranked:
        return ranked[0].get("style"), round(float(ranked[0].get("score", 0)), 4)
    return None, 0.0


def _ranked_read(payload):
    """The one ranked read every per-track derivation shares.

    The hand-adjusted blend if the track has one, else ``weights.base_read``
    (relabel, then salience, then the flat styles). The label, the colour
    blend and the override candidates all come from this, so a track you have
    relabelled or nudged cannot be labelled from one read and coloured from
    another -- which is what happened when each of them spelled out its own
    chain and two of them left the relabel tier out.
    """
    from ..weights import base_read, read_with_steps

    return read_with_steps(payload) or base_read(payload)


def _second_style(payload, top_style, top_score):
    """The runner-up style + its weight relative to the top read, for colour
    blending on the map (a track that's partly a 2nd genre leans toward its
    colour). Returns [style2, weight2] with weight2 in [0, 0.5], or None when
    there's an override or no distinct runner-up.

    Reads the same ranked read ``_dominant_style`` does, so a track you've
    hand-weighted or relabelled leans toward the colour you gave it. Reading raw
    salience here left the dot's blend arguing with its own label."""
    if payload.get("override"):
        return None
    for s in _ranked_read(payload):
        st, sc = s.get("style"), float(s.get("score", 0) or 0)
        if st and st != top_style and sc > 0:
            denom = (top_score or 0) + sc
            return [st, round(sc / denom, 3) if denom else 0.0]
    return None
