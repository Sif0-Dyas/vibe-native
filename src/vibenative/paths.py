"""Where this program's files are: its executable, its settings, its models, and
the read-only resources bundled with it.

Every answer differs between a dev checkout and a PyInstaller build, which is the
whole reason this module exists -- callers ask for the thing, not for the layout.

Path translation for a library inherited from the predecessor app now lives in
``legacy.py``; it is a migration concern, not a question about where this build
keeps its files.
"""

import sys
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def exe_dir() -> Path:
    """The folder holding the running program's executable: the .exe's directory in a
    PyInstaller build (where loose, exe-adjacent resources like ffmpeg live), or the
    interpreter's dir in dev (harmless — no resources there, callers fall through)."""
    return Path(sys.executable).resolve().parent


@lru_cache(maxsize=1)
def settings_ini() -> Path:
    """Where the persisted app settings live, for both reading and writing.

    In a packaged build that's next to the .exe -- the installer's DB-location
    page writes there and the exe reads it back.

    In dev it's the repo root, NOT ``exe_dir()``. exe_dir() resolves to
    ``.venv/Scripts`` when running from a venv, so a setting written there would
    sit inside the virtualenv and vanish the next time it was rebuilt. That was
    fine while the file was only ever read (a missing one just falls through to
    the default); it stops being fine now that the Options tab can write it.
    """
    if getattr(sys, "frozen", False):
        return exe_dir() / "settings.ini"
    return Path(__file__).resolve().parents[2] / "settings.ini"


# Both are cached because each resolves a path against the filesystem and
# neither answer can change while the process runs -- ``sys.frozen`` is fixed at
# startup and ``__file__`` does not move. They were being called from inside the
# per-genre lookup in taxonomy.load(), which a single /map build invokes ~47,000
# times; the resolve() syscalls alone accounted for about 3 seconds of an
# 18-second response.


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
