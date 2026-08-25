"""Genre-system routes: the taxonomy view, retroactive re-labelling, and the
snapshots that make re-labelling safe to try.

These expose three modules that until now had no way in:

* ``genres``    -- per-keystone profiles (description, canonical vs observed BPM,
                   colour, subgenres, most representative tracks), grouped by family.
* ``relabel``   -- re-run the classifier head over stored embeddings so tracks
                   analysed before a training are corrected without a re-scan.
* ``snapshots`` -- capture / restore / reset the learned state.

The destructive ones are deliberately awkward to reach: re-labelling defaults to
a preview, and reset needs the confirmation word typed. Both are cheap to undo,
but only if you know they happened.
"""

from flask import jsonify, request

from ._shared import bp


@bp.get("/genres")
def genres_route():
    """Every keystone in the library, grouped by family.

    ``?flat=1`` returns the ungrouped list; ``?top=N`` sets how many
    representative tracks each keystone carries (0 for none, which makes the
    response much smaller when only the counts are wanted).
    """
    from .. import genres

    top = max(0, min(int(request.args.get("top", 5) or 0), 25))
    mode = "light" if request.args.get("mode") == "light" else "dark"
    if request.args.get("flat"):
        return jsonify(genres.summarise(top_n=top, mode=mode))
    return jsonify(genres.by_family(top_n=top, mode=mode))


@bp.get("/genres/<keystone>")
def genre_one_route(keystone):
    """One keystone's profile, or 404 if nothing in the library reads as it."""
    from .. import genres

    prof = genres.one(keystone, top_n=int(request.args.get("top", 10) or 10))
    if not prof:
        return jsonify({"error": f"no tracks read as {keystone!r}"}), 404
    return jsonify(prof)


@bp.get("/genres/taxonomy")
def taxonomy_route():
    """The taxonomy itself -- families, their keystones, and the palette.

    Independent of what's in the library, so the Genres tab can show the whole
    scheme (including families you own no tracks in) rather than only what you
    happen to have.
    """
    from .. import keystone as K
    from .. import palette as P

    mode = "light" if request.args.get("mode") == "light" else "dark"
    return jsonify(
        {
            "families": [
                {
                    "family": fam,
                    "keystones": [
                        {
                            "keystone": k,
                            "color": P.keystone_color(k, mode),
                            "slotted": k in P.KEYSTONE_SLOT,
                        }
                        for k in (K.FAMILIES.get(fam) or [])
                    ],
                }
                for fam in K.FAMILY_ORDER
                if fam != K.OTHER_FAMILY
            ],
            "other_family": K.OTHER_FAMILY,
            "legend": P.legend(mode),
            "fusion_threshold": K.FUSION_THRESHOLD,
        }
    )


# --- retroactive re-labelling ------------------------------------------------
@bp.get("/relabel/status")
def relabel_status_route():
    """How much of the library carries a re-label, and whether it's stale."""
    from .. import relabel

    return jsonify(relabel.status())


@bp.post("/relabel/preview")
def relabel_preview_route():
    """What a re-label would change. Writes nothing."""
    from .. import relabel

    d = request.get_json(silent=True) or {}
    return jsonify(relabel.preview(limit=d.get("limit")))


@bp.post("/relabel/apply")
def relabel_apply_route():
    """Apply the re-label across the library.

    Takes a snapshot first. Re-labelling is already reversible on its own
    (``/relabel/revert`` drops one key), but a snapshot also captures the
    overrides and training rows, so one action restores everything if the newly
    trained head turns out to be worse than what it replaced.
    """
    from .. import relabel, snapshots

    d = request.get_json(silent=True) or {}
    snap = None
    if d.get("snapshot", True):
        snap = snapshots.create("pre-relabel")
    out = relabel.apply(limit=d.get("limit"))
    out["snapshot"] = snap
    return jsonify(out)


@bp.post("/relabel/revert")
def relabel_revert_route():
    """Drop every re-label, restoring the originally analysed reads."""
    from .. import relabel

    return jsonify(relabel.revert())


# --- snapshots ----------------------------------------------------------------
@bp.get("/snapshots")
def snapshots_list_route():
    from .. import snapshots

    return jsonify(snapshots.list_all())


@bp.post("/snapshots")
def snapshots_create_route():
    from .. import snapshots

    label = ((request.get_json(silent=True) or {}).get("label") or "manual").strip()
    return jsonify(snapshots.create(label))


@bp.post("/snapshots/<snap_id>/restore")
def snapshots_restore_route(snap_id):
    from .. import snapshots

    try:
        return jsonify(snapshots.restore(snap_id))
    except FileNotFoundError:
        return jsonify({"error": f"no snapshot {snap_id!r}"}), 404


@bp.post("/snapshots/reset")
def snapshots_reset_route():
    """Return genre behaviour to stock. Requires the confirmation word.

    Nothing is deleted -- a snapshot is taken first and a trained head is moved
    aside rather than removed. The confirmation exists so this cannot be reached
    by a mis-click; the UI asks the user to type it.
    """
    from .. import snapshots

    confirm = (request.get_json(silent=True) or {}).get("confirm")
    try:
        return jsonify(snapshots.reset(confirm))
    except snapshots.ConfirmationRequired as e:
        return jsonify({"error": str(e), "confirm_word": snapshots.CONFIRM_WORD}), 400
