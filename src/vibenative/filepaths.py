"""Audit and repair the file paths recorded against analysed tracks.

A track's ``filepath`` is where the audio actually lives. It is what makes
preview playback, on-demand waveforms, segment extraction and Rekordbox export
work -- an analysed track without one is a genre reading with no song attached.

Tracks analysed by drag-and-drop never had a path recorded (the browser only
hands over bytes), and a path goes stale whenever files are moved or a drive
letter changes. Both are repaired the same way: hash the files in a folder and
match them to tracks that are already analysed.

**Why this is not just a re-scan.** A scan decodes and analyses every file
(~2s each). Repair only needs the content hash -- 15ms for the same file, about
**136x faster** -- because the analysis already exists and is keyed by that hash.
Repairing 1,600 paths is seconds of hashing rather than an hour of inference,
and it never re-analyses anything or changes a genre.
"""

import os
from contextlib import closing
from pathlib import Path

from .config import AUDIO_EXTS, log
from .db import _db_lock, db, file_hash


def _is_sidecar(path) -> bool:
    """macOS AppleDouble stubs (``._Track.mp3``) look like audio and are not."""
    return path.name.startswith("._")


def audit(check_exists=True):
    """The state of every recorded path.

    ``missing`` -- analysed, no path at all (drag-and-drop, or never scanned).
    ``broken``  -- a path is recorded but nothing is there any more.
    ``ok``      -- recorded and present.

    ``check_exists=False`` skips the stat() per track, which matters when the
    files live on a slow or disconnected network/USB volume: without it an audit
    of a detached drive would report every track as broken after a long stall.
    """
    with _db_lock, closing(db()) as conn, conn as c:
        rows = c.execute("SELECT hash, title, filename, filepath FROM tracks").fetchall()
    ok, broken, missing = [], [], []
    for h, title, filename, fp in rows:
        name = title or filename or h[:8]
        if not (fp or "").strip():
            missing.append({"hash": h, "title": name})
        elif check_exists and not os.path.exists(fp):
            broken.append({"hash": h, "title": name, "path": fp})
        else:
            ok.append(h)
    return {
        "total": len(rows),
        "ok": len(ok),
        "broken": len(broken),
        "missing": len(missing),
        "broken_examples": broken[:25],
        "missing_examples": missing[:25],
    }


# Hashing reads the whole file, so it is I/O-bound and the volume dominates.
# Measured on this machine: ~15 ms/file on the internal SSD, ~199 ms/file on an
# external USB drive -- 13x slower. So an 11,796-file external drive is ~39
# minutes, not the 3 the SSD figure suggests.
#
# The estimate uses the *slow* figure deliberately. Under-promising turns a
# surprise into a wait you chose; the number exists to distinguish "a few
# seconds" from "go and make coffee", not to be precise.
_MS_PER_FILE = 200


def count_files(folder):
    """Walk ``folder`` and count candidate audio files without hashing anything.

    Hashing a whole drive is minutes of work, and a caller that jumps straight
    into it leaves the user staring at a frozen button. Walking is cheap, so the
    UI can say "12,000 files, about 3 minutes" and let you narrow the folder
    before committing.
    """
    root = Path(folder).expanduser()
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    n = 0
    for p in root.rglob("*"):
        try:
            if p.is_file() and p.suffix.lower() in AUDIO_EXTS and not _is_sidecar(p):
                n += 1
        except OSError:
            continue  # unreadable entry mid-walk; not worth failing the count for
    return {
        "folder": str(root),
        "audio_files": n,
        "estimated_seconds": round(n * _MS_PER_FILE / 1000),
    }


def scan_folder(folder, limit=None):
    """Hash every audio file under ``folder``. Returns ``{hash: path}``.

    Later duplicates lose to the first path seen, so a stable sort order gives a
    stable result when the same song exists twice on disk.
    """
    root = Path(folder).expanduser()
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    found, seen, errors = {}, 0, 0
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in AUDIO_EXTS or _is_sidecar(p):
            continue
        seen += 1
        try:
            h = file_hash(p)
        except OSError:
            errors += 1  # unreadable / locked / vanished mid-walk
            continue
        found.setdefault(h, str(p))
        if limit and len(found) >= limit:
            break
    return {"found": found, "scanned": seen, "unreadable": errors}


def repair(folder, dry_run=True, overwrite_broken=True):
    """Point at a music folder and reconnect analysed tracks to their files.

    Matches by content hash, so a renamed or moved file is still recognised.
    Only ever fills in a path that is absent or broken -- a track whose recorded
    file is present is left alone, so running this over a folder that also
    contains copies can't silently repoint your library at the copies.

    ``dry_run=True`` (the default) reports what it would do and writes nothing.
    """
    scan = scan_folder(folder)
    found = scan["found"]
    with _db_lock, closing(db()) as conn, conn as c:
        rows = c.execute("SELECT hash, filepath FROM tracks").fetchall()

    fills, fixes, already = [], [], 0
    for h, fp in rows:
        cand = found.get(h)
        if not cand:
            continue
        cur = (fp or "").strip()
        if not cur:
            fills.append((cand, h))
        elif overwrite_broken and not os.path.exists(cur):
            fixes.append((cand, h))
        else:
            already += 1

    if not dry_run and (fills or fixes):
        with _db_lock, closing(db()) as conn, conn as c:
            c.executemany("UPDATE tracks SET filepath=? WHERE hash=?", fills + fixes)
        log.info("filepaths: %d filled, %d re-pointed from %s", len(fills), len(fixes), folder)

    return {
        "folder": str(folder),
        "dry_run": dry_run,
        "audio_files_scanned": scan["scanned"],
        "unreadable": scan["unreadable"],
        "matched_tracks": len(fills) + len(fixes) + already,
        "filled": len(fills),
        "repointed": len(fixes),
        "already_ok": already,
        # files on disk that no analysed track claims -- i.e. not yet scanned
        "unanalysed_files": len(found) - (len(fills) + len(fixes) + already),
        "examples": [{"hash": h, "path": p} for p, h in (fills + fixes)[:25]],
    }
