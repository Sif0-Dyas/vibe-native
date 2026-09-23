"""Bring a WSL Vibe_Identify library across: its live genre_v2.db -> GENRE_DB.

Run once per machine that still has the old WSL app, to inherit its library DB
(analysis cache, vibes, tags, training labels, segment overrides) instead of
starting empty. The cutover on the original dev machine is long done; this stays
because a fresh install on a machine with the WSL app is the same problem again,
and the README points users here. The WSL original is only READ — it stays put as
the rollback.

    python tools/db_cutover.py            # copy live WSL DB -> %USERPROFILE%\\genre_v2.db
    python tools/db_cutover.py --force    # overwrite an existing destination
    GENRE_DB=D:\\path.db python tools/db_cutover.py   # custom destination

What it does:
  1. Locate the live DB at \\\\wsl$\\<distro>\\home\\<user>\\genre_v2.db.
  2. Copy it (OS byte copy — reliable over the wsl$ 9p mount where SQLite locking
     is not) to GENRE_DB, and integrity-check the copy.
  3. Verify tracks / vibes / tags row counts match the source (read on the WSL side).
Path translation (/mnt/... -> C:\\...) is left to the app's schema migration #2,
which runs automatically on first boot (init_db). Counts are unchanged by it.

Sensible Windows default destination: %USERPROFILE%\\genre_v2.db (= db.py's
GENRE_DB default, Path.home()/"genre_v2.db"), so the app finds it with no config.
"""

import argparse
import json
import os
import shutil
import sqlite3
import subprocess  # nosec B404  # only runs wsl.exe with a fixed read-only query, no shell
import sys
from pathlib import Path

# Candidate live-DB locations (WSL exposes the distro FS under these UNC roots).
_WSL_USER = os.environ.get("GENRE_WSL_USER", "euphy")
_WSL_DISTRO = os.environ.get("GENRE_WSL_DISTRO", "Ubuntu")
_CANDIDATES = [
    Path(rf"\\wsl$\{_WSL_DISTRO}\home\{_WSL_USER}\genre_v2.db"),
    Path(rf"\\wsl.localhost\{_WSL_DISTRO}\home\{_WSL_USER}\genre_v2.db"),
]

_DEFAULT_DEST = Path(os.environ.get("GENRE_DB", Path.home() / "genre_v2.db"))
_COUNT_TABLES = ("tracks", "vibes", "tags")


def _find_source() -> Path | None:
    return next((p for p in _CANDIDATES if p.is_file()), None)


def _wsl_source_counts() -> dict | None:
    """Read the source row counts on the WSL side (native ext4, reliable SQLite
    locking) so the verification is genuinely against the source. Read-only
    (mode=ro). Returns None if wsl.exe / a usable Python isn't reachable."""
    tables = ",".join(repr(t) for t in _COUNT_TABLES)
    code = (
        "import sqlite3,json;"  # nosec B608  # tables are the fixed _COUNT_TABLES constant, not user input
        f"c=sqlite3.connect('file:/home/{_WSL_USER}/genre_v2.db?mode=ro',uri=True);"
        f"print(json.dumps({{t:c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in [{tables}]}}))"
    )
    distro = ["-d", _WSL_DISTRO] if _WSL_DISTRO else []
    for py in (f"/home/{_WSL_USER}/genre/bin/python", "python3"):
        try:
            out = subprocess.run(  # nosec B603 B607  # wsl.exe + fixed args, no shell
                ["wsl.exe", *distro, "--", py, "-c", code],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if out.returncode == 0 and out.stdout.strip():
            try:
                return json.loads(out.stdout.strip().splitlines()[-1])
            except ValueError:
                continue
    return None


def _counts(conn) -> dict:
    out = {}
    for t in _COUNT_TABLES:
        try:
            out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # nosec B608  # t is from the fixed _COUNT_TABLES constant
        except sqlite3.Error:
            out[t] = None
    return out


def cutover(dest: Path, force: bool) -> int:
    src = _find_source()
    if src is None:
        print("ERROR: live WSL DB not found. Tried:")
        for p in _CANDIDATES:
            print(f"  {p}")
        print("Is the distro running? Set GENRE_WSL_USER / GENRE_WSL_DISTRO if they differ.")
        return 2
    print(f"source (live, read-only): {src}  ({src.stat().st_size / 1e6:.1f} MB)")

    if dest.exists() and not force:
        print(f"ERROR: destination already exists: {dest}\n  re-run with --force to overwrite it.")
        return 2

    # A plain OS file copy is a consistent snapshot here (no -wal/-shm sidecar => the
    # DB is checkpointed on disk) and NEVER opens/locks the source in SQLite. We copy
    # rather than use SQLite's backup API because SQLite locking is unreliable over
    # the \\wsl$ 9p mount ("database is locked" even for reads); byte copy is not.
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    print(f"copied -> {dest}  ({dest.stat().st_size / 1e6:.1f} MB)")

    # Verify the LOCAL copy: integrity + row counts + how many /mnt paths remain to
    # translate on first boot. (The copy is on NTFS, where SQLite works normally.)
    with sqlite3.connect(dest) as dconn:
        dest_counts = _counts(dconn)
        integrity = dconn.execute("PRAGMA integrity_check").fetchone()[0]
        mnt = dconn.execute("SELECT COUNT(*) FROM tracks WHERE filepath LIKE '/mnt/%'").fetchone()[
            0
        ]
    print(f"dest counts:   {dest_counts}   (integrity_check: {integrity})")
    print(f"               /mnt filepaths to translate on first boot: {mnt}")
    if integrity != "ok":
        print("ERROR: destination failed integrity_check!")
        return 1

    # Cross-check against the SOURCE counts read on the WSL side (native ext4, where
    # SQLite locking is reliable), so the verification is genuinely vs. the source.
    src_counts = _wsl_source_counts()
    if src_counts is None:
        print("NOTE: could not read source counts via WSL to cross-check; relying on the")
        print("      copy's integrity_check(ok) + counts above. (Is wsl.exe on PATH?)")
    else:
        print(f"source counts (via WSL): {src_counts}")
        if dest_counts != src_counts:
            print("ERROR: row counts differ between source and copy!")
            return 1
        print("counts match source exactly.")

    print("\nOK. The WSL original is untouched (read-only cross-check) — rollback intact.")
    print("Path translation (/mnt -> C:\\) runs automatically on first app boot.")
    print(f"Point the app at it with GENRE_DB={dest} (this is also the default).")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Cut the live WSL genre_v2.db over to Windows.")
    ap.add_argument(
        "--dest", type=Path, default=_DEFAULT_DEST, help=f"destination (default {_DEFAULT_DEST})"
    )
    ap.add_argument("--force", action="store_true", help="overwrite an existing destination")
    args = ap.parse_args()
    return cutover(args.dest, args.force)


if __name__ == "__main__":
    sys.exit(main())
