"""Shared pytest fixtures.

Every test runs against its own ``Settings`` (vibenative/settings.py), installed by
the autouse ``settings`` fixture before the test body: FAKE mode (no models), and
a throwaway database, config dir (settings.ini, dev_token), taxonomy overlay and
model dir (custom head) under the test's tmp_path. So the suite never touches real
models, the user's ~/genre_v2.db, or their settings -- and since nothing in the
package reads the environment at import, no module is reloaded between tests.
"""

import atexit
import dataclasses
import os
import shutil
import tempfile

import pytest

from vibenative import settings as vn_settings
from vibenative.settings import Settings

# A test must never build settings from the real environment: settings.current()
# before the fixture below has installed a Settings raises, instead of silently
# reading the developer's GENRE_DB and friends.
vn_settings._implicit = False

# The one path that still reads the environment on purpose is Settings.from_env()
# (python -m vibenative's main(), wsgi.py, create_app() without arguments). Point
# what it would find at a throwaway dir, assigned outright rather than setdefault,
# so a GENRE_DB exported in the developer's shell cannot leak into a test that
# exercises one of those.
SESSION_DIR = tempfile.mkdtemp(prefix="vibe-tests-")
atexit.register(shutil.rmtree, SESSION_DIR, ignore_errors=True)
os.environ["GENRE_DB"] = os.path.join(SESSION_DIR, "genre_v2.db")
os.environ["VIBE_CONFIG_DIR"] = os.path.join(SESSION_DIR, "config")
os.environ["VIBE_TAXONOMY"] = os.path.join(SESSION_DIR, "taxonomy.json")
os.environ["MODEL_DIR"] = os.path.join(SESSION_DIR, "models")
for _name in ("CUSTOM_HEAD", "VIBE_SNAPSHOTS", "GENRE_TOKEN"):
    os.environ.pop(_name, None)

# Every request needs the app's token (vibenative/auth.py) -- there is no
# unauthenticated mode, tests included. The per-test Settings carry this one;
# anything that builds its own app talks to it through authed().
TEST_TOKEN = "test-token"  # nosec B105  # a fixed token for the test apps, not a secret


def make_settings(tmp_path, **overrides):
    """The Settings a test runs with: everything under ``tmp_path``, FAKE mode."""
    base = {
        "db_path": tmp_path / "genre_v2.db",
        "fake": True,
        "model_dir": tmp_path / "models",
        "config_dir": tmp_path / "config",
        "taxonomy": tmp_path / "taxonomy.json",
        "token": TEST_TOKEN,
    }
    return Settings(**(base | overrides))


@pytest.fixture(autouse=True)
def settings(tmp_path, monkeypatch):
    """Install this test's Settings, and afterwards close every connection db()
    opened (Windows won't delete an open file) and uninstall them, so nothing
    between tests -- or a thread outliving one -- can use a stale test's paths.

    The Essentia-era ~/essentia_models that Settings.from_env() falls back to for
    an unmoved custom head is redirected too, so no test looks at the real one."""
    monkeypatch.setattr(vn_settings, "_legacy_model_dir", lambda: tmp_path / "essentia_models")
    s = vn_settings.use(make_settings(tmp_path))
    yield s
    _close_db_connections()
    vn_settings._current = None


@pytest.fixture()
def use_settings(settings):
    """``use_settings(**changes)`` swaps the installed Settings for a copy with
    ``changes`` (e.g. ``fake=False`` or another ``db_path``) and returns it."""

    def swap(**changes):
        _close_db_connections()
        return vn_settings.use(dataclasses.replace(vn_settings.current(), **changes))

    return swap


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    # Belt and braces for the autouse fixture: by the time any test body runs,
    # its Settings are installed, so current() never falls back to the environment.
    assert vn_settings._current is not None, f"{item.nodeid}: no Settings installed"
    yield


def _close_db_connections():
    """Close the connections db() keeps per thread (vibenative.db.close_all), so no
    test leaves a database file open for the next -- or locked for deletion."""
    from vibenative.db import close_all

    close_all()


def seed_track(h, payload):
    """Put one analysed track in the scratch DB, keyed by content hash.

    The three test modules that build a library each spelled out the same
    ``cache_put`` call; this is the one place that knows its argument order.
    """
    from vibenative.db import cache_put

    cache_put(h, f"{h}.mp3", "", h, payload, None)
    return h


def authed(app):
    """A test client for ``app`` that carries the auth cookie, as a browser does
    after its first ``/?k=<token>`` navigation."""
    from vibenative.auth import TOKEN_COOKIE

    c = app.test_client()
    c.set_cookie(TOKEN_COOKIE, app.config["AUTH_TOKEN"])
    return c


@pytest.fixture()
def client(settings):
    import vibenative

    app = vibenative.create_app(settings)
    app.config.update(TESTING=True)
    with authed(app) as c:
        yield c
