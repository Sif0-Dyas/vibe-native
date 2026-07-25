"""WSL <-> native-Windows path translation.

The oracle's index.json (and the legacy genre_v2.db that Phase 4 inherits) store
source paths as WSL mount paths, e.g. ``/mnt/c/Users/mrand/oracle_tracks/x.mp3``.
On native Windows those must become ``C:\\Users\\mrand\\oracle_tracks\\x.mp3``.

Reused by the Phase-4 database migration (addendum §5: translate the /mnt-prefix
filepaths stored in old rows so audio preview + section extraction keep working).
"""

import re
import sys
from pathlib import Path, PureWindowsPath

_MNT = re.compile(r"^/mnt/([a-zA-Z])/(.*)$")


def exe_dir() -> Path:
    """The folder holding the running program's executable: the .exe's directory in a
    PyInstaller build (where loose, exe-adjacent resources like ffmpeg live), or the
    interpreter's dir in dev (harmless — no resources there, callers fall through)."""
    return Path(sys.executable).resolve().parent


def resource_base() -> Path:
    """Base dir for BUNDLED read-only data files (e.g. docs/USAGE.md). In a PyInstaller
    build this is the bundle's extraction dir (sys._MEIPASS — the _internal/ folder for a
    onedir build); in dev it's the repo root."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parents[2]


def models_dir() -> Path:
    """The ONNX models directory. Checks EXE-ADJACENT ``models/`` first (the packaged
    build ships them as loose files next to the exe, not baked into the bundle), then
    the dev-tree ``<repo>/models``. Returns the first that exists, else the dev path
    so error messages point somewhere sensible."""
    candidates = [
        Path(sys.executable).resolve().parent / "models",  # next to the packaged exe
        Path(__file__).resolve().parents[2] / "models",  # dev tree: <repo>/models
    ]
    return next((c for c in candidates if c.is_dir()), candidates[-1])


def wsl_to_windows(path: str) -> str:
    """``/mnt/c/Users/x`` -> ``C:\\Users\\x``. A path that isn't a /mnt mount
    (already-Windows, UNC, relative, ...) is returned unchanged."""
    if not path:
        return path
    m = _MNT.match(path.replace("\\", "/"))
    if not m:
        return path
    drive, rest = m.group(1).upper(), m.group(2)
    return str(PureWindowsPath(f"{drive}:/") / rest) if rest else f"{drive}:\\"
