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
import os
import shutil
import time
from contextlib import closing
from pathlib import Path

from .analysis import CUSTOM_HEAD_PATH
from .config import log
from .db import DB_PATH, _db_lock, db

# The word a caller must pass to reset(). The UI asks the user to type it.
CONFIRM_WORD = "RESET"

# Tables holding learned state. Each is snapshotted whole and cleared on reset.
_TABLES = ("training_labels", "training_rejects", "segment_overrides")

SNAPSHOT_DIR = Path(os.environ.get("VIBE_SNAPSHOTS", Path(DB_PATH).parent / "vibe_snapshots"))


class ConfirmationRequired(ValueError):
    """reset() was called without the exact confirmation word."""


def _safe(label):
    keep = "".join(c if c.isalnum() or c in " _-" else "_" for c in (label or "")).strip()
    return keep.replace(" ", "-")[:40] or "snapshot"


def _capture():
    """Read every piece of learned state out of the database.

    Track overrides live inside each track's payload JSON rather than their own
    table, so they're pulled out by hash -- restoring writes them back into the
    payload without disturbing the analysis stored alongside.
    """
    state = {"tables": {}, "overrides": {}}
    with _db_lock, closing(db()) as conn, conn as c:
        for t in _TABLES:
            cur = c.execute(f"SELECT * FROM {t}")  # nosec B608  # fixed table allow-list
            cols = [d[0] for d in cur.description]
            state["tables"][t] = {"columns": cols, "rows": [list(r) for r in cur.fetchall()]}
        for h, payload in c.execute("SELECT hash, payload FROM tracks"):
            try:
                p = json.loads(payload) if isinstance(payload, str) else (payload or {})
            except (TypeError, ValueError):
                continue
            if p.get("override"):
                state["overrides"][h] = p["override"]
    return state


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
    state = _capture()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = SNAPSHOT_DIR / f"{stamp}-{_safe(label)}"
    path.mkdir(parents=True, exist_ok=True)

    head_saved = False
    if CUSTOM_HEAD_PATH.exists():
        shutil.copy2(CUSTOM_HEAD_PATH, path / "custom_head.npz")
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
    if not SNAPSHOT_DIR.is_dir():
        return []
    out = []
    for d in SNAPSHOT_DIR.iterdir():
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
    with _db_lock, closing(db()) as conn, conn as c:
        for t in _TABLES:
            c.execute(f"DELETE FROM {t}")  # nosec B608  # fixed table allow-list
        for h, payload in c.execute("SELECT hash, payload FROM tracks").fetchall():
            try:
                p = json.loads(payload) if isinstance(payload, str) else (payload or {})
            except (TypeError, ValueError):
                continue
            if p.get("override"):
                p.pop("override", None)
                c.execute("UPDATE tracks SET payload=? WHERE hash=?", (json.dumps(p), h))


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
    if CUSTOM_HEAD_PATH.exists():
        aside = CUSTOM_HEAD_PATH.with_name(f"{CUSTOM_HEAD_PATH.stem}.{snap['id']}.npz")
        CUSTOM_HEAD_PATH.rename(aside)
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
    path = SNAPSHOT_DIR / snapshot_id
    if not (path / "state.json").is_file():
        raise FileNotFoundError(f"no snapshot {snapshot_id!r}")
    state = json.loads((path / "state.json").read_text(encoding="utf-8"))

    before = create(f"pre-restore-{snapshot_id}")
    _clear()

    with _db_lock, closing(db()) as conn, conn as c:
        for t, blob in state.get("tables", {}).items():
            if t not in _TABLES:
                continue  # ignore anything not on the allow-list
            cols, rows = blob.get("columns") or [], blob.get("rows") or []
            if not cols or not rows:
                continue
            ph = ",".join("?" * len(cols))
            names = ",".join(cols)
            c.executemany(
                f"INSERT OR REPLACE INTO {t} ({names}) VALUES ({ph})",  # nosec B608
                [tuple(r) for r in rows],
            )
        for h, override in (state.get("overrides") or {}).items():
            row = c.execute("SELECT payload FROM tracks WHERE hash=?", (h,)).fetchone()
            if not row:
                continue  # the track is gone; its override has nowhere to land
            try:
                p = json.loads(row[0]) if isinstance(row[0], str) else (row[0] or {})
            except (TypeError, ValueError):
                continue
            p["override"] = override
            c.execute("UPDATE tracks SET payload=? WHERE hash=?", (json.dumps(p), h))

    head = path / "custom_head.npz"
    if head.is_file():
        CUSTOM_HEAD_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(head, CUSTOM_HEAD_PATH)

    log.info("restored snapshot %s (previous state saved as %s)", snapshot_id, before["id"])
    return {"restored": snapshot_id, "previous_state_saved_as": before["id"]}
