"""A track's genre identity: the one style every view reports for it.

``dominant_style(payload)`` is what the Library list, the map, the Map popup,
/similar, the misread check and the training-set tools all show, and what the
``tracks.style`` column stores. It used to be spelled out in more than one
place, and the copies disagreed: the misread check skipped hand adjustments
and re-labels, so it could call a track "misread" as a genre it no longer had.

Imports nothing from ``routes`` -- this is domain logic, not HTTP.
"""

from .weights import base_read, read_with_steps


def dominant_style(payload):
    """The track's style, or None if the payload has no read at all.

    See :func:`dominant_read` for the precedence."""
    return dominant_read(payload)[0]


def dominant_read(payload):
    """(style, score) -- the track's identity, by precedence:

    1. a manual override (POST /override) -- "it IS this", it wins outright
       with score 1.0;
    2. manual weight adjustments (``weights`` / ``drops``) -- "it leans this
       way", the read nudged by hand; see ``vibenative.weights``;
    3. a retroactive re-label (``relabel``) -- a newer head's opinion, applied
       without re-scanning; see ``vibenative.relabel``;
    4. the salience read -- the energy/confidence/recurrence-weighted identity
       from the original analysis;
    5. the top flat style (``styles[0]``).

    Adjustments outrank both automatic reads because they are those reads with
    your judgement applied; an override outranks them only because it is the
    blunter statement. A re-label outranks salience because it is the *newer*
    judgement -- it exists only when a head has been trained since the track was
    analysed, and cannot be merged into salience, which needs per-frame
    predictions the database doesn't keep.

    Every tier leaves the ones beneath it intact, so any of them can be undone.
    (None, 0.0) when there is no read at all.
    """
    ident = identity(payload)
    return ident["style"], ident["score"]


def identity(payload):
    """The track's identity, the tier it came from, and that tier's read:
    ``{"style", "score", "source", "read"}``. ``source`` is "override",
    "weights", "relabel", "salience" or "styles" (None with no read at all);
    ``read`` is the ranked read the style is the top of -- what a view shows
    as the track's blend. The precedence is dominant_read's (above); this is
    the same chain, reporting which step answered."""
    p = payload or {}
    if p.get("override"):
        o = p["override"]
        return {
            "style": o,
            "score": 1.0,
            "source": "override",
            "read": [{"style": o, "score": 1.0}],
        }
    read = read_with_steps(p)
    if read:
        source = "weights"
    else:
        read = base_read(p)
        if (p.get("relabel") or {}).get("styles"):
            source = "relabel"
        elif p.get("salience"):
            source = "salience"
        elif p.get("styles"):
            source = "styles"
        else:
            return {"style": None, "score": 0.0, "source": None, "read": []}
    top = read[0]
    return {
        "style": top.get("style"),
        "score": round(float(top.get("score", 0)), 4),
        "source": source,
        "read": read,
    }


def identity_fields(payload, top=8):
    """identity() as the flat fields every analysis response, cached row and
    edit response carries, so a client shows the server's answer instead of
    working one out: dominant_style, dominant_score, dominant_source and
    dominant_read (the top ``top`` entries of the read)."""
    ident = identity(payload)
    return {
        "dominant_style": ident["style"],
        "dominant_score": ident["score"],
        "dominant_source": ident["source"],
        "dominant_read": [
            {"style": e.get("style"), "score": float(e.get("score", 0) or 0)}
            for e in ident["read"][:top]
        ],
    }


def ranked_read(payload):
    """The one ranked read every per-track derivation shares (tiers 2-5 above).

    The hand-adjusted blend if the track has one, else ``weights.base_read``
    (relabel, then salience, then the flat styles). The label, the colour
    blend and the override candidates all come from this, so a track you have
    relabelled or nudged cannot be labelled from one read and coloured from
    another -- which is what happened when each of them spelled out its own
    chain and two of them left the relabel tier out.
    """
    return read_with_steps(payload) or base_read(payload)
