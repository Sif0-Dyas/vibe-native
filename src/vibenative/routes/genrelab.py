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
    from .. import keystone as K

    top = max(0, min(int(request.args.get("top", 5) or 0), 25))
    mode = "light" if request.args.get("mode") == "light" else "dark"
    if request.args.get("flat"):
        return jsonify(genres.summarise(top_n=top, mode=mode))
    if request.args.get("by") == "archgenre":
        # archgenre -> keystone, the display hierarchy. Grouped here rather than
        # in the client so the tier logic has exactly one owner.
        profiles = genres.summarise(top_n=top, mode=mode)
        grouped = {}
        for p in profiles:
            p["archgenre"] = K.archgenre_of(p["keystone"])
            grouped.setdefault(p["archgenre"], []).append(p)
        total = sum(p["count"] for p in profiles) or 1
        # Ordered groups first, then anything the order doesn't mention. Filtering
        # to the known order alone would silently drop a group -- and every track
        # in it -- the moment a user overlay invented an archgenre for it.
        order = [a for a in K.archgenre_order() if a in grouped]
        order += [a for a in grouped if a not in order]
        return jsonify(
            [
                {
                    "archgenre": a,
                    "count": sum(p["count"] for p in grouped[a]),
                    "share": round(sum(p["count"] for p in grouped[a]) / total, 4),
                    "standalone": a in K.STANDALONE_ARCHGENRES,
                    "keystones": grouped[a],
                }
                for a in order
            ]
        )
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


# --- taxonomy overlay ---------------------------------------------------------
# The user's edits to the genre tables, kept in a JSON file outside the database
# so they survive the re-scans that throw the database away. See ``taxonomy``.
@bp.get("/taxonomy/overlay")
def overlay_get_route():
    """The current overlay, plus where it lives and what it may contain.

    The path is returned because hand-editing the file is a supported way to use
    it, and the UI has no other way to tell you where to look.
    """
    from .. import keystone as K
    from .. import taxonomy

    return jsonify(
        {
            "overlay": taxonomy.load(),
            "path": str(taxonomy.path()),
            "version": taxonomy.VERSION,
            "archgenres": K.archgenre_order(),
            "families": K.FAMILY_ORDER,
        }
    )


@bp.post("/taxonomy/overlay")
def overlay_patch_route():
    """Merge edits into the overlay.

    Body is the overlay shape, e.g. ``{"archgenre": {"Halftime": "Drum n Bass"}}``.
    A map value of ``null`` clears that entry, which is how you go back to the
    built-in default rather than overriding it with something else.
    """
    from .. import taxonomy

    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        return jsonify({"error": "object required"}), 400
    return jsonify({"overlay": taxonomy.patch(d), "path": str(taxonomy.path())})


@bp.post("/taxonomy/overlay/reset")
def overlay_reset_route():
    """Drop every taxonomy edit. Requires the confirmation word.

    Nothing is deleted -- the file is renamed, so a mis-click is recoverable.
    Same stance as the training reset below.
    """
    from .. import snapshots, taxonomy

    confirm = (request.get_json(silent=True) or {}).get("confirm")
    if (confirm or "").strip().upper() != snapshots.CONFIRM_WORD:
        return jsonify(
            {
                "error": f"type {snapshots.CONFIRM_WORD} to confirm",
                "confirm_word": snapshots.CONFIRM_WORD,
            }
        ), 400
    return jsonify(taxonomy.reset())


# --- colour presets -----------------------------------------------------------
@bp.get("/palettes")
def palettes_route():
    """Every colour preset with its swatches and its measured separation.

    The separation numbers ship with the list on purpose: the presets are not
    equally readable, and a picker that hid that would be pretending they were.
    """
    from .. import palettes as PP

    mode = "light" if request.args.get("mode") == "light" else "dark"
    return jsonify({"current": PP.current(), "default": PP.DEFAULT, "presets": PP.summarise(mode)})


@bp.post("/palettes/<name>")
def palette_apply_route(name):
    """Switch to a colour preset. Per-genre colours are left alone -- they are
    the exceptions layered on top, and dropping them here would silently discard
    hand-picked colours as a side effect of trying a scheme out."""
    from .. import palettes as PP

    try:
        return jsonify({"current": PP.apply(name)})
    except ValueError:
        return jsonify({"error": f"unknown palette {name!r}", "known": PP.names()}), 404


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
