"""The app's settings, read from the environment in exactly one place.

``Settings.from_env()`` is the only code in the package that reads an app setting
from ``os.environ`` (it also loads the project-root ``.env`` first, outside pytest).
Nothing is read at import: ``create_app(settings)`` installs a ``Settings`` with
``use()``, and the rest of the package asks ``current()`` at call time. A script
that never calls ``create_app`` still works: the first ``current()`` builds one
from the environment.

Facts about the machine rather than settings of the app -- ``APPDATA``,
``LOCALAPPDATA``, ``USERPROFILE`` -- are still read where they are used.

The fields hold what the environment said; a field left ``None`` falls back to
the default its property computes, so a test can build ``Settings(db_path=...)``
without restating every derived path.
"""

import configparser
import dataclasses
import os
import sys
from pathlib import Path

from .config import _apply_dotenv, log

_ROOT_DOTENV = Path(__file__).resolve().parent.parent.parent / ".env"  # src/vibenative -> root


@dataclasses.dataclass(frozen=True)
class Settings:
    # The library database. GENRE_DB, else settings.ini's db_path, else ~/genre_v2.db.
    db_path: Path
    # MODEL_DIR: user-supplied extras (the optional custom head); default
    # <config_dir>/models, see _default_model_dir. The ONNX models the engine runs
    # live in the repo's / exe's models/ (paths.models_dir).
    model_dir: Path
    # FAKE_ANALYZER=1: instant fake results, no models loaded.
    fake: bool = False
    # CUSTOM_HEAD; None -> model_dir / custom_head.npz (see custom_head_path).
    custom_head: Path | None = None
    # VIBE_SNAPSHOTS; None -> beside the database (see snapshots_dir).
    snapshots: Path | None = None
    # VIBE_CONFIG_DIR; None -> paths.config_dir()'s own default.
    config_dir: Path | None = None
    # VIBE_TAXONOMY; None -> <config_dir>/taxonomy.json.
    taxonomy: Path | None = None
    # GENRE_TOKEN; "" -> auth picks one (a dev token, or a fresh one when frozen).
    token: str = ""
    # VIBE_PROVIDER: "gpu"/"dml"/... opts into DirectML; anything else is CPU.
    provider: str = ""
    # MAX_UPLOAD_MB: the largest upload Flask accepts.
    max_upload_mb: int = 512
    # Optional metadata-lookup credentials (the per-row lookup). Absent -> that
    # source is skipped. Discogs takes a personal token OR key + secret; the token
    # wins if both are set.
    discogs_token: str = ""
    discogs_key: str = ""
    discogs_secret: str = ""
    lastfm_key: str = ""
    # GENRE_BACKEND_LOG: the desktop shell's log file, surfaced by /status.
    backend_log: str = ""
    # GENRE_HOST / GENRE_PORT: where python -m vibenative and wsgi.py serve.
    host: str = "127.0.0.1"
    port: int = 5005

    @property
    def custom_head_path(self) -> Path:
        return self.custom_head or self.model_dir / "custom_head.npz"

    @property
    def snapshots_dir(self) -> Path:
        return self.snapshots or Path(self.db_path).parent / "vibe_snapshots"

    @classmethod
    def from_env(cls, environ=None) -> "Settings":
        """Settings from ``environ`` (default: ``os.environ``, after loading the
        project-root ``.env`` into it -- skipped under pytest, so a developer's
        local .env never leaks into the test run)."""
        if environ is None:
            if "pytest" not in sys.modules:
                _apply_dotenv(_ROOT_DOTENV)  # real environment variables still win
            environ = os.environ

        def text(name, default=""):
            return environ.get(name, default).strip()

        def path(name):
            v = environ.get(name)
            return Path(v) if v else None

        config_dir = path("VIBE_CONFIG_DIR")
        return cls(
            db_path=_db_path(environ.get("GENRE_DB"), config_dir),
            fake=environ.get("FAKE_ANALYZER") == "1",
            model_dir=path("MODEL_DIR") or _default_model_dir(config_dir),
            custom_head=path("CUSTOM_HEAD"),
            snapshots=path("VIBE_SNAPSHOTS"),
            config_dir=config_dir,
            taxonomy=path("VIBE_TAXONOMY"),
            token=text("GENRE_TOKEN"),
            provider=text("VIBE_PROVIDER"),
            max_upload_mb=int(environ.get("MAX_UPLOAD_MB", "512")),
            discogs_token=text("DISCOGS_TOKEN"),
            discogs_key=text("DISCOGS_KEY"),
            discogs_secret=text("DISCOGS_SECRET"),
            lastfm_key=text("LASTFM_KEY"),
            backend_log=environ.get("GENRE_BACKEND_LOG") or "",
            host=environ.get("GENRE_HOST", "127.0.0.1"),
            port=int(environ.get("GENRE_PORT", "5005")),
        )


def _db_path(env, config_dir) -> Path:
    """Where the library database lives, in priority order:

    1. ``GENRE_DB`` -- always wins (power users, dev).
    2. ``[vibenative] db_path`` in ``settings.ini`` (``paths.settings_ini_for_read``):
       the per-user copy in ``%APPDATA%\\Vibe Identify``, which a packaged build seeds
       once from the installer's DB-location page (written beside the exe) and the
       Options tab updates; the exe-adjacent file is read only if that copy is
       missing. Env vars in the value (e.g. ``%USERPROFILE%``) are expanded at
       runtime so a machine-wide setting still resolves per-user.
    3. Default: ``%USERPROFILE%\\genre_v2.db``.
    """
    if env:
        return Path(os.path.expandvars(env))
    try:
        from .paths import resolve_config_dir, settings_ini_for_read

        ini = settings_ini_for_read(resolve_config_dir(config_dir))
        if ini.is_file():
            # interpolation=None so a literal "%USERPROFILE%" in the value isn't parsed
            # as configparser interpolation; os.path.expandvars expands it below.
            cp = configparser.ConfigParser(interpolation=None)
            cp.read(ini, encoding="utf-8")
            val = cp.get("vibenative", "db_path", fallback="").strip()
            if val:
                return Path(os.path.expandvars(val))
    except Exception:  # nosec B110  # a malformed settings.ini must never block startup -> fall through
        pass
    return Path.home() / "genre_v2.db"


def _legacy_model_dir() -> Path:
    return Path.home() / "essentia_models"


def _default_model_dir(config_dir) -> Path:
    """``<config_dir>/models``: per-user state, beside settings.ini (``%APPDATA%``
    in a packaged build), not the Essentia-era ``~/essentia_models``.

    A custom head trained before the move is still in the old folder. While the
    new one has none, keep using the old folder -- a restart must not silently
    drop the user's trained head -- and say where to move it."""
    from .paths import resolve_config_dir

    new = resolve_config_dir(config_dir) / "models"
    old = _legacy_model_dir()
    if not (new / "custom_head.npz").exists() and (old / "custom_head.npz").exists():
        log.warning(
            "custom head found in the old model folder %s; using it from there. "
            "Move custom_head.npz to %s to stop this warning.",
            old,
            new,
        )
        return old
    return new


_current: Settings | None = None
# The test suite turns this off, so a stray current() fails loudly instead of
# quietly building settings from the developer's real environment.
_implicit = True


def use(settings: Settings) -> Settings:
    """Make ``settings`` the ones ``current()`` returns (create_app calls this)."""
    global _current
    _current = settings
    return settings


def current() -> Settings:
    """The settings in effect. Built from the environment on first use if nothing
    has installed any -- a script that imports a module without create_app()."""
    if _current is None:
        if not _implicit:
            raise RuntimeError("settings.current() before settings.use(): no Settings installed")
        use(Settings.from_env())
    return _current
