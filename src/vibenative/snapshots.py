"""Snapshots of the genre training state, and a non-destructive reset.

Everything you teach the app about genres -- manual overrides, confirmed and
rejected training labels, segment overrides, and the trained custom head --
accumulates. When it starts pulling the wrong way, you want to put it back to
stock without losing the work that got you here.

So **reset never deletes**. It takes a full snapshot first, then clears the live
state; the snapshot holds everything and ``restore()`` puts it back. The audio in
``~/genre_training/`` is never touched at all -- that's your curated source
material, not algorithm state, and rebuilding it by hand would be the real loss.

Snapshots live beside the library database, so they travel with it. Each is a
plain directory of JSON plus a copy of the head weights: readable, diffable,
and restorable by hand if this module ever goes away.

``reset()`` requires the caller to pass the literal confirmation word. That's a
guard against a mis-click reaching it, not security -- the route layer asks the
user to type it.
"""

import itertools
import json
import shutil
import time

from .config import log
from .names import safe_name
from .repo import snapshots as snapshots_repo
from .settings import current

# The word a caller must pass to reset(). The UI asks the user to type it.
CONFIRM_WORD = "RESET"

# Tables holding learned state. Each is snapshotted whole and cleared on reset.
_TABLES = ("training_labels", "training_rejects", "segment_overrides")


class ConfirmationRequired(ValueError):
    """reset() was called without the exact confirmation word."""


def _safe(label):
    keep = safe_name(label)
    return keep.replace(" ", "-")[:40] or "snapshot"


def _capture():
    """Read every piece of learned state out of the database.

    Track overrides live inside each track's payload JSON rather than their own
    table, so they're pulled out by hash -- restoring writes them back into the
    payload without disturbing the analysis stored alongside.
    """
    return snapshots_repo.capture(_TABLES)


# Windows' wall clock ticks every 15.6 ms (`time.get_clock_info("time").resolution`),
# and no clock available here does better -- time_ns and monotonic share it. Two
# snapshots taken back to back therefore record the SAME `created`, and a sort on
# that alone falls back to whatever order the filesystem lists them in, which is
# alphabetical by label: "...-first" ahead of a newer "...-second". This counter
# records the order within a process so the tie can be broken correctly. Across
# process restarts it resets, which is harmless: two runs landing in the same
# 15.6 ms tick is vanishingly unlikely, and snapshots from different runs are
# separated by the wall clock long before the tie-break is consulted.
_seq = itertools.count()


def create(label="manual"):
    """Snapshot the current training state. Returns the snapshot's metadata.

    Cheap and side-effect free -- take one whenever you're about to do something
    you might regret.
    """
    settings = current()
    state = _capture()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = settings.snapshots_dir / f"{stamp}-{_safe(label)}"
    path.mkdir(parents=True, exist_ok=True)

    head_saved = False
    if settings.custom_head_path.exists():
        shutil.copy2(settings.custom_head_path, path / "custom_head.npz")
        head_saved = True

    meta = {
        "id": path.name,
        "label": label,
        "created": time.time(),
        "created_human": time.strftime("%Y-%m-%d %H:%M:%S"),
        "seq": next(_seq),  # tie-break only; see _seq above
        "overrides": len(state["overrides"]),
        "rows": {t: len(v["rows"]) for t, v in state["tables"].items()},
        "custom_head": head_saved,
    }
    (path / "state.json").write_text(json.dumps(state, indent=1), encoding="utf-8")
    (path / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    log.info("snapshot created: %s (%s overrides)", path.name, meta["overrides"])
    return meta


def list_all():
    """Every snapshot on disk, newest first. Unreadable ones are skipped, not
    raised -- a corrupt directory shouldn't make the whole list unavailable."""
    snapshot_dir = current().snapshots_dir
    if not snapshot_dir.is_dir():
        return []
    out = []
    for d in snapshot_dir.iterdir():
        if not d.is_dir():
            continue
        try:
            out.append(json.loads((d / "meta.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            log.warning("snapshot %s is unreadable; skipping", d.name)
    # `seq` orders snapshots the coarse wall clock stamped identically; snapshots
    # written before it existed default to 0 and keep their previous order.
    return sorted(out, key=lambda m: (m.get("created", 0), m.get("seq", 0)), reverse=True)


def _clear():
    """Wipe the live learned state. Only ever called after a snapshot exists."""
    snapshots_repo.clear(_TABLES)


def reset(confirm, label="pre-reset"):
    """Return genre behaviour to stock, keeping everything recoverable.

    Snapshots first, then clears overrides and training rows and moves any
    trained head aside (renamed, not removed -- the snapshot has a copy too).
    Raises ``ConfirmationRequired`` unless ``confirm`` is exactly ``RESET``.

    Not touched, on purpose: the analysed tracks themselves, and the audio in
    ``~/genre_training/``. Reset undoes what the app learned, not your library.
    """
    if confirm != CONFIRM_WORD:
        raise ConfirmationRequired(f"pass confirm={CONFIRM_WORD!r} to reset")

    snap = create(label)
    _clear()

    head_moved = None
    head_path = current().custom_head_path
    if head_path.exists():
        aside = head_path.with_name(f"{head_path.stem}.{snap['id']}.npz")
        head_path.rename(aside)
        head_moved = str(aside)

    log.info("genre state reset; recoverable from snapshot %s", snap["id"])
    return {
        "reset": True,
        "snapshot": snap,
        "custom_head_moved_to": head_moved,
        "note": "Nothing was deleted. Restore with snapshots.restore(<id>). "
        "A restart is needed for a moved custom head to stop being used.",
    }


def restore(snapshot_id):
    """Put a snapshot's state back, replacing whatever is live now.

    Takes its own snapshot of the current state first, so restoring is itself
    undoable and you can never strand yourself between two states.
    """
    settings = current()
    path = settings.snapshots_dir / snapshot_id
    if not (path / "state.json").is_file():
        raise FileNotFoundError(f"no snapshot {snapshot_id!r}")
    state = json.loads((path / "state.json").read_text(encoding="utf-8"))

    before = create(f"pre-restore-{snapshot_id}")
    _clear()

    snapshots_repo.restore(state, _TABLES)

    head = path / "custom_head.npz"
    if head.is_file():
        settings.custom_head_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(head, settings.custom_head_path)

    log.info("restored snapshot %s (previous state saved as %s)", snapshot_id, before["id"])
    return {"restored": snapshot_id, "previous_state_saved_as": before["id"]}
