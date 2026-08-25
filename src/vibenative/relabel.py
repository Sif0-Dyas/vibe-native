"""Retroactively re-label already-analysed tracks -- no audio, no re-scan.

The point of training a custom head is that tracks analysed *before* the training
are still wrong. Re-scanning the library to fix them means decoding every file
again (~2s each, and impossible at all for the 81% of tracks with no stored
filepath). This does it from what's already in the database.

**How it works.** Every track keeps its 1280-d mean embedding. The embedding is
the expensive part -- it comes from the audio -- and it does not change when the
*head* changes. So a re-label is just the classifier head re-run over stored
vectors: a matrix multiply, the whole library in seconds.

**What it costs in fidelity.** A full analysis classifies every ~2s patch and
collapses them with :func:`analysis.salience_read`, weighting each frame by
energy, confidence and recurrence. Only the *mean* embedding is stored, so a
re-label sees one averaged vector instead of the track's structure. Measured
against 400 real tracks, the mean-embedding top-1 matches the salience top-1
**86.8%** of the time, and the salience top-1 is inside the mean's top-3 **97.8%**
of the time. Good enough to correct a library; not identical to a re-scan.

**Nothing is overwritten.** The result goes in its own ``relabel`` key with
provenance -- when, by which head, and how. The original ``styles`` and
``salience`` stay exactly as analysed, so a re-label is reversible by deleting
one key, and you can always tell a re-labelled read from a measured one.
"""

import json
import time
from contextlib import closing

import numpy as np

from .config import log
from .db import _db_lock, db

# Marks a payload's re-labelled read. Consumers prefer this over `salience` when
# present -- see routes._shared._dominant_style.
KEY = "relabel"

TOPK = 8


def _head_id():
    """Identify the head that produced a re-label, so a stale one is visible.

    The custom head's file mtime + size is enough to tell "trained again" from
    "same head"; the stock head has no file, so it reports as such.
    """
    from .analysis import CUSTOM_HEAD_PATH

    try:
        st = CUSTOM_HEAD_PATH.stat()
        return f"custom:{int(st.st_mtime)}:{st.st_size}"
    except OSError:
        return "stock"


def _predict(engine, blob):
    """Class probabilities for one stored mean embedding."""
    v = np.frombuffer(blob, dtype=np.float32).reshape(1, -1)
    return engine["classifier"](v)[0]


def _read(pred, labels, topk=TOPK):
    """Top-k [{style, score}], strongest first, normalised over the kept mass.

    Normalised so the scores read like the existing salience shares rather than
    raw sigmoid outputs, which the rest of the app already treats as weights.
    """
    order = np.argsort(-pred)[:topk]
    total = float(pred[order].sum()) or 1.0
    return [
        {"style": labels[int(i)], "score": round(float(pred[i]) / total, 4)}
        for i in order
        if pred[i] > 0
    ]


def _rows(limit=None):
    q = "SELECT hash, title, filename, payload, embedding FROM tracks WHERE embedding IS NOT NULL"
    if limit:
        q += f" LIMIT {int(limit)}"
    with _db_lock, closing(db()) as conn, conn as c:
        return c.execute(q).fetchall()


def _current_top(p):
    """What the track reads as right now, by the same precedence the app uses."""
    if p.get("override"):
        return p["override"]
    for key in (KEY, "salience", "styles"):
        entries = p.get(key) or []
        if entries:
            return (entries[0] or {}).get("style")
    return None


def preview(limit=None):
    """What a re-label *would* change, without writing anything.

    Returns ``{"total", "changed", "unchanged", "head", "examples"}``. Run this
    before :func:`apply` -- a head trained on too little data can move a lot of
    tracks, and that is much easier to see before it happens than after.
    """
    from .analysis import get_engine

    eng = get_engine()
    labels = [x.split("---", 1)[1] for x in eng["labels"]]
    changed, examples, total = 0, [], 0
    for h, title, filename, payload, blob in _rows(limit):
        try:
            p = json.loads(payload) if isinstance(payload, str) else (payload or {})
        except (TypeError, ValueError):
            continue
        total += 1
        if p.get("override"):
            continue  # a manual override outranks any re-label; leave it alone
        new = _read(_predict(eng, blob), labels)
        if not new:
            continue
        before, after = _current_top(p), new[0]["style"]
        if before != after:
            changed += 1
            if len(examples) < 25:
                examples.append(
                    {
                        "hash": h,
                        "title": title or filename or h[:8],
                        "from": before,
                        "to": after,
                        "score": new[0]["score"],
                    }
                )
    return {
        "total": total,
        "changed": changed,
        "unchanged": total - changed,
        "head": _head_id(),
        "examples": examples,
    }


def apply(limit=None):
    """Write the re-labelled read into every track's payload.

    Skips tracks with a manual override -- you told the app what those are.
    Original ``styles``/``salience`` are left untouched; only the ``relabel`` key
    is added or replaced, so this is safe to re-run and undo.
    """
    from .analysis import get_engine

    eng = get_engine()
    labels = [x.split("---", 1)[1] for x in eng["labels"]]
    head, stamp = _head_id(), time.time()
    updates, skipped = [], 0
    for h, _title, _filename, payload, blob in _rows(limit):
        try:
            p = json.loads(payload) if isinstance(payload, str) else (payload or {})
        except (TypeError, ValueError):
            continue
        if p.get("override"):
            skipped += 1
            continue
        entries = _read(_predict(eng, blob), labels)
        if not entries:
            continue
        p[KEY] = {
            "styles": entries,
            "head": head,
            "at": stamp,
            # Recorded so a reader can tell how this was produced -- and so a
            # future full-audio re-analysis can be distinguished from this.
            "method": "mean-embedding",
        }
        updates.append((json.dumps(p), h))
    with _db_lock, closing(db()) as conn, conn as c:
        c.executemany("UPDATE tracks SET payload=? WHERE hash=?", updates)
    log.info(
        "relabel: %d tracks updated, %d skipped (manual override), head=%s",
        len(updates),
        skipped,
        head,
    )
    return {"updated": len(updates), "skipped_override": skipped, "head": head}


def revert():
    """Remove every re-label, restoring the originally analysed reads."""
    cleared = []
    with _db_lock, closing(db()) as conn, conn as c:
        for h, payload in c.execute("SELECT hash, payload FROM tracks").fetchall():
            try:
                p = json.loads(payload) if isinstance(payload, str) else (payload or {})
            except (TypeError, ValueError):
                continue
            if KEY in p:
                p.pop(KEY, None)
                cleared.append((json.dumps(p), h))
        c.executemany("UPDATE tracks SET payload=? WHERE hash=?", cleared)
    log.info("relabel: reverted %d tracks", len(cleared))
    return {"reverted": len(cleared)}


def status():
    """How much of the library currently carries a re-label, and from which head."""
    total = relabelled = 0
    heads = {}
    with _db_lock, closing(db()) as conn, conn as c:
        for (payload,) in c.execute("SELECT payload FROM tracks"):
            try:
                p = json.loads(payload) if isinstance(payload, str) else (payload or {})
            except (TypeError, ValueError):
                continue
            total += 1
            r = p.get(KEY)
            if r:
                relabelled += 1
                heads[r.get("head", "?")] = heads.get(r.get("head", "?"), 0) + 1
    return {
        "total": total,
        "relabelled": relabelled,
        "heads": heads,
        "current_head": _head_id(),
        # True when the library was re-labelled by a head that has since changed.
        "stale": bool(heads) and any(h != _head_id() for h in heads),
    }
