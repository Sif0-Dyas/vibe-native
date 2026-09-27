"""Where this program's files are: its executable, its settings, its models, and
the read-only resources bundled with it.

Every answer differs between a dev checkout and a PyInstaller build, which is the
whole reason this module exists -- callers ask for the thing, not for the layout.

Path translation for a library inherited from the predecessor app now lives in
``legacy.py``; it is a migration concern, not a question about where this build
keeps its files.
"""

import os
import shutil
import sys
import threading
from functools import lru_cache
from pathlib import Path

APP_DIR_NAME = "Vibe Identify"  # the per-user folder under %APPDATA%
CONFIG_DIR_ENV = "VIBE_CONFIG_DIR"  # overrides config_dir(); the test suite sets it


@lru_cache(maxsize=1)
def exe_dir() -> Path:
    """The folder holding the running program's executable: the .exe's directory in a
    PyInstaller build (where loose, exe-adjacent resources like ffmpeg live), or the
    interpreter's dir in dev (harmless — no resources there, callers fall through)."""
    return Path(sys.executable).resolve().parent


def config_dir() -> Path:
    """Where the user's own settings live: settings.ini and taxonomy.json.

    * ``VIBE_CONFIG_DIR``, if set -- the test suite points it at a temp dir.
    * A packaged build: ``%APPDATA%/Vibe Identify``. NOT next to the exe: the
      installer puts the exe in Program Files, which a normal user cannot write, so
      /db-path and every taxonomy edit used to fail there.
    * Dev: the repo root, NOT ``exe_dir()`` -- that resolves to ``.venv/Scripts``,
      and a file written there vanishes the next time the venv is rebuilt.
    """
    return _config_dir(
        os.environ.get(CONFIG_DIR_ENV), getattr(sys, "frozen", False), os.environ.get("APPDATA")
    )


@lru_cache(maxsize=8)
def _config_dir(env, frozen, appdata) -> Path:
    # Cached: taxonomy.path() runs inside the per-genre lookup in taxonomy.load(),
    # which one /map build invokes ~47,000 times, and when this was an uncached
    # settings_ini() the resolve() syscalls alone cost ~3 s of an 18 s response.
    # Keyed on the inputs rather than cached outright, so a change to the env var
    # (which tests make) is still followed.
    if env:
        return Path(env)
    if frozen:
        return Path(appdata or Path.home() / "AppData" / "Roaming") / APP_DIR_NAME
    return Path(__file__).resolve().parents[2]


def _installer_ini() -> Path:
    """The settings.ini the installer writes beside the exe (its DB-location page).

    Read-only as far as the app is concerned: it seeds the per-user copy once
    (see settings_ini) and is otherwise only a fallback for reading."""
    return exe_dir() / "settings.ini"


_seed_lock = threading.Lock()


def settings_ini() -> Path:
    """The settings file the app WRITES (and normally reads): in config_dir().

    In a packaged build, the first call copies the installer-written settings.ini
    into the per-user dir if that has none yet -- once: after that the copy exists
    and the exe-adjacent file is never written, only read as a fallback by
    settings_ini_for_read(). A copy that fails (unwritable profile) is left for the
    next start to retry; reading still works via that fallback.
    """
    target = config_dir() / "settings.ini"
    if getattr(sys, "frozen", False) and not target.exists():
        seed = _installer_ini()
        with _seed_lock:
            if not target.exists() and seed.is_file() and seed != target:
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    # copyfile, not copy2: contents only. copy2 carries the
                    # read-only bit across, and the copy has to be writable.
                    shutil.copyfile(seed, target)
                except OSError:  # nosec B110  # retried next start; reads fall back to the seed
                    pass
    return target


def settings_ini_for_read() -> Path:
    """The settings file to READ: the per-user copy, or -- in a packaged build
    where that doesn't exist -- the installer-written one beside the exe."""
    target = settings_ini()
    if not target.is_file() and getattr(sys, "frozen", False) and _installer_ini().is_file():
        return _installer_ini()
    return target


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
