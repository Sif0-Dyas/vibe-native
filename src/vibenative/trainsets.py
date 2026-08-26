"""Per-genre training sets: inspect, reset, export and import one genre at a time.

Training is global in effect -- one head learns every genre together -- but it
goes wrong locally. One genre gets fed the wrong tracks and starts pulling
everything toward itself, while the rest are fine. Resetting the whole training
state to fix one poisoned genre throws away every other genre's work.

So everything here is scoped to a single genre: its files, its labels, its
rejections. Reset one, export one, import one.

**Nothing is deleted.** A reset moves the genre's folder into
``~/genre_training/_archive/<genre>-<timestamp>/`` and clears only that genre's
rows. The audio you curated is the expensive part -- it took listening to
gather -- so it is always recoverable by moving the folder back.

**Export is a manifest, not audio.** A training set's value is *which tracks*,
and the audio is already in your library; shipping copies would turn a 20-track
export into hundreds of megabytes. The manifest records content hashes, so an
import re-files the same audio from wherever the library now keeps it -- which
also means it survives moving your music or rebuilding the database.
"""

import json
import shutil
import time
from contextlib import closing
from pathlib import Path

from .config import log
from .db import _db_lock, db

# Mirrors routes.training: the folder /override and /save_training file into,
# and the one training/train_head.py consumes.
ROOT = Path.home() / "genre_training"
ARCHIVE = ROOT / "_archive"

MANIFEST_VERSION = 1


def _safe(genre):
    """The folder name a genre maps to, or None if the name isn't usable.

    Same character substitution as ``/override`` and ``/save_training`` so the
    three agree on where a genre's audio lives. It adds one rejection those
    don't: a name with no alphanumeric character at all. "///" sanitises to
    "___", which would silently create a junk folder and then let a reset claim
    it had cleared something real.
    """
    raw = genre or ""
    if not any(c.isalnum() for c in raw):
        return None
    keep = "".join(c if c.isalnum() or c in " _-" else "_" for c in raw).strip()
    return keep or None


def folder(genre):
    s = _safe(genre)
    return (ROOT / s) if s else None


def _audio_files(d):
    if not d or not d.is_dir():
        return []
    return sorted(f for f in d.iterdir() if f.is_file() and not f.name.startswith("._"))


def detail(genre, top_n=10):
    """Everything about one genre's training: its files, and the library tracks
    that currently read as it.

    ``tracks`` is what the app believes today -- useful both as "is this genre
    working" and as the pool to pick more training examples from.
    """
    from . import keystone as K
    from .routes._shared import _dominant_style

    d = folder(genre)
    files = _audio_files(d)
    want = (genre or "").strip().lower()

    tracks = []
    with _db_lock, closing(db()) as conn, conn as c:
        rows = c.execute("SELECT hash, title, filename, filepath, payload FROM tracks").fetchall()
        labelled = {
            r[0]
            for r in c.execute("SELECT hash FROM training_labels WHERE LOWER(genre)=?", (want,))
        }
        rejected = sum(
            1 for _ in c.execute("SELECT 1 FROM training_rejects WHERE LOWER(genre)=?", (want,))
        )
    for h, title, filename, filepath, payload in rows:
        try:
            p = json.loads(payload) if isinstance(payload, str) else (payload or {})
        except (TypeError, ValueError):
            continue
        style, score = _dominant_style(p)
        # Match either the exact style or the keystone it rolls up to, so
        # clicking "House" finds the deep/tech/progressive house tracks too.
        if not style:
            continue
        if str(style).lower() != want and str(K.keystone_of(style) or "").lower() != want:
            continue
        tracks.append(
            {
                "hash": h,
                "title": title or filename or h[:8],
                "style": style,
                "score": round(float(score or 0), 4),
                "bpm": p.get("bpm"),
                "playable": bool((filepath or "").strip()),
                "in_training": h in labelled,
            }
        )
    tracks.sort(key=lambda t: -t["score"])
    return {
        "genre": genre,
        "folder": str(d) if d else None,
        "files": len(files),
        "file_names": [f.name for f in files[:50]],
        "labelled": len(labelled),
        "rejected": rejected,
        "library_tracks": len(tracks),
        "top": tracks[:top_n],
    }


def reset(genre):
    """Clear one genre's training, keeping the audio recoverable.

    The folder is archived rather than removed, and only this genre's label and
    rejection rows are cleared -- every other genre's work is untouched. Use
    when a genre has been fed the wrong tracks and started skewing.
    """
    d = folder(genre)
    if not d:
        raise ValueError("invalid genre name")
    want = (genre or "").strip().lower()

    moved = None
    if d.is_dir() and _audio_files(d):
        ARCHIVE.mkdir(parents=True, exist_ok=True)
        dest = ARCHIVE / f"{d.name}-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.move(str(d), str(dest))
        moved = str(dest)

    with _db_lock, closing(db()) as conn, conn as c:
        labels = c.execute("DELETE FROM training_labels WHERE LOWER(genre)=?", (want,)).rowcount
        rejects = c.execute("DELETE FROM training_rejects WHERE LOWER(genre)=?", (want,)).rowcount
    log.info("trainset reset %r: archived=%s labels=%d rejects=%d", genre, moved, labels, rejects)
    return {
        "genre": genre,
        "archived_to": moved,
        "labels_cleared": labels,
        "rejects_cleared": rejects,
        "note": "Audio was archived, not deleted -- move the folder back to undo.",
    }


def export(genre):
    """A portable manifest of one genre's training set.

    Content hashes rather than audio, so it stays small and survives the library
    moving or being rebuilt -- the same song re-imports from wherever it lives
    now. File names ride along only as a human hint when a hash no longer
    resolves.

    Hashes come from the **folder**, not just ``training_labels``. The two
    disagree: ``/override`` copies audio into the genre folder without writing a
    label row, so a genre trained entirely by overriding tracks has files and
    zero labels. The folder is what ``training/train_head.py`` actually consumes,
    which makes it the source of truth -- exporting from the table alone
    produced a manifest that restored nothing.
    """
    from .db import file_hash

    d = folder(genre)
    files = _audio_files(d)
    want = (genre or "").strip().lower()

    seen, entries = set(), []
    for f in files:
        try:
            h = file_hash(f)
        except OSError:
            continue  # unreadable file: skip it rather than fail the export
        if h in seen:
            continue
        seen.add(h)
        entries.append({"hash": h, "source": "folder", "name": f.name})

    with _db_lock, closing(db()) as conn, conn as c:
        for h, src in c.execute(
            "SELECT hash, source FROM training_labels WHERE LOWER(genre)=?", (want,)
        ):
            if h not in seen:
                seen.add(h)
                entries.append({"hash": h, "source": src or "label"})
        rejects = [
            r[0]
            for r in c.execute("SELECT hash FROM training_rejects WHERE LOWER(genre)=?", (want,))
        ]
    return {
        "version": MANIFEST_VERSION,
        "genre": genre,
        "exported": time.time(),
        "files": [f.name for f in files],
        "labels": entries,
        "rejects": rejects,
        "note": "Hashes, not audio. Import re-files the same tracks from your library.",
    }


def import_(manifest, genre=None, copy_audio=True):
    """Restore a training set from :func:`export`.

    Merges rather than replaces: importing twice is harmless, and importing into
    a genre that already has work adds to it. Tracks whose hash is not in the
    library are reported rather than silently dropped -- that is the honest
    answer to "I exported this from a bigger collection".
    """
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be an object")
    target = (genre or manifest.get("genre") or "").strip()
    if not target:
        raise ValueError("no genre in the manifest and none given")
    safe = _safe(target)
    if not safe:
        raise ValueError("invalid genre name")

    wanted = [entry.get("hash") for entry in (manifest.get("labels") or []) if entry.get("hash")]
    rejects = [h for h in (manifest.get("rejects") or []) if h]

    found, missing, copied = [], [], 0
    dest = ROOT / safe
    with _db_lock, closing(db()) as conn, conn as c:
        for h in wanted:
            row = c.execute("SELECT filepath FROM tracks WHERE hash=?", (h,)).fetchone()
            if row is None:
                missing.append(h)
            else:
                found.append((h, (row[0] or "").strip()))
        now = time.time()
        c.executemany(
            "INSERT OR IGNORE INTO training_labels(hash, genre, source, created) VALUES(?,?,?,?)",
            [(h, target, "import", now) for h, _ in found],
        )
        c.executemany(
            "INSERT OR IGNORE INTO training_rejects(hash, genre) VALUES(?,?)",
            [(h, target) for h in rejects],
        )

    no_path = sum(1 for _h, fp in found if not fp)
    if copy_audio:
        dest.mkdir(parents=True, exist_ok=True)
        for _h, fp in found:
            if not fp:
                continue  # analysed by drag-and-drop; no file to copy
            src = Path(fp)
            if src.is_file() and not (dest / src.name).exists():
                try:
                    shutil.copy2(src, dest / src.name)
                    copied += 1
                except OSError:
                    pass  # unreadable source shouldn't abort the whole import
    log.info(
        "trainset import %r: %d labels, %d copied, %d missing",
        target,
        len(found),
        copied,
        len(missing),
    )
    return {
        "genre": target,
        "labels_added": len(found),
        "audio_copied": copied,
        "rejects_added": len(rejects),
        "missing_from_library": len(missing),
        "missing_hashes": missing[:25],
        # Labels alone don't train anything: train_head.py reads the genre
        # FOLDERS. A track the library has no path for can be labelled but not
        # copied, so an import can look successful and still leave the trainer
        # with nothing. Say so rather than let it be discovered at training time.
        "known_but_no_audio": no_path,
        "trainable": copied > 0 or bool(_audio_files(dest)),
    }
