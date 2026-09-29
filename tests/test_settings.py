"""Settings: read from the environment in one place, never at import.

``Settings.from_env`` is tested against a plain dict, so these tests never read
the developer's real environment (and pass no ``.env`` loading either: an
explicit mapping skips it).
"""

import os
import subprocess  # nosec B404  # runs this interpreter on a fixed snippet
import sys
from pathlib import Path

import pytest

from vibenative import settings as S


@pytest.fixture()
def legacy():
    """conftest's stand-in for ~/essentia_models."""
    return S._legacy_model_dir()


def test_defaults_are_the_ones_the_constants_had(tmp_path, legacy):
    # Nothing set but an empty config dir (so no settings.ini is consulted).
    s = S.Settings.from_env({"VIBE_CONFIG_DIR": str(tmp_path)})
    assert s.db_path == Path.home() / "genre_v2.db"
    assert s.fake is False
    assert s.model_dir == tmp_path / "models"  # the config dir, not ~/essentia_models
    assert s.custom_head_path == tmp_path / "models" / "custom_head.npz"
    assert s.snapshots_dir == Path.home() / "vibe_snapshots"
    assert s.taxonomy is None and s.token == "" and s.provider == ""
    assert s.max_upload_mb == 512
    assert (s.discogs_token, s.discogs_key, s.discogs_secret, s.lastfm_key) == ("",) * 4
    assert s.backend_log == ""
    assert (s.host, s.port) == ("127.0.0.1", 5005)


def test_every_variable_lands_in_its_field(tmp_path):
    env = {
        "GENRE_DB": str(tmp_path / "lib.db"),
        "FAKE_ANALYZER": "1",
        "MODEL_DIR": str(tmp_path / "models"),
        "CUSTOM_HEAD": str(tmp_path / "head.npz"),
        "VIBE_SNAPSHOTS": str(tmp_path / "snaps"),
        "VIBE_CONFIG_DIR": str(tmp_path / "cfg"),
        "VIBE_TAXONOMY": str(tmp_path / "tax.json"),
        "GENRE_TOKEN": " tok ",
        "VIBE_PROVIDER": " GPU ",
        "MAX_UPLOAD_MB": "64",
        "DISCOGS_TOKEN": " dt ",
        "DISCOGS_KEY": "dk",
        "DISCOGS_SECRET": "ds",
        "LASTFM_KEY": "lk",
        "GENRE_BACKEND_LOG": "C:/log.txt",
        "GENRE_HOST": "0.0.0.0",  # nosec B104  # a value under test, never bound
        "GENRE_PORT": "5123",
    }
    s = S.Settings.from_env(env)
    assert s.db_path == tmp_path / "lib.db" and s.fake is True
    assert s.model_dir == tmp_path / "models"
    assert s.custom_head_path == tmp_path / "head.npz"
    assert s.snapshots_dir == tmp_path / "snaps"
    assert s.config_dir == tmp_path / "cfg" and s.taxonomy == tmp_path / "tax.json"
    assert s.token == "tok" and s.provider == "GPU" and s.max_upload_mb == 64
    assert (s.discogs_token, s.discogs_key, s.discogs_secret, s.lastfm_key) == (
        "dt",
        "dk",
        "ds",
        "lk",
    )
    assert s.backend_log == "C:/log.txt"
    assert (s.host, s.port) == ("0.0.0.0", 5123)  # nosec B104


def test_fake_needs_exactly_one(tmp_path):
    base = {"VIBE_CONFIG_DIR": str(tmp_path)}
    assert S.Settings.from_env(base | {"FAKE_ANALYZER": "1"}).fake is True
    assert S.Settings.from_env(base | {"FAKE_ANALYZER": "1 "}).fake is False  # cmd's `set X=1 &&`


def test_settings_ini_db_path_is_used_without_genre_db(tmp_path):
    (tmp_path / "settings.ini").write_text("[vibenative]\ndb_path = D:/Music/lib.db\n", "utf-8")
    assert S.Settings.from_env({"VIBE_CONFIG_DIR": str(tmp_path)}).db_path == Path(
        "D:/Music/lib.db"
    )
    env = {"VIBE_CONFIG_DIR": str(tmp_path), "GENRE_DB": str(tmp_path / "wins.db")}
    assert S.Settings.from_env(env).db_path == tmp_path / "wins.db"


def test_a_head_left_in_the_old_folder_is_still_used_with_a_warning(tmp_path, legacy, caplog):
    legacy.mkdir()
    (legacy / "custom_head.npz").write_bytes(b"trained before the move")
    env = {"VIBE_CONFIG_DIR": str(tmp_path / "cfg")}
    with caplog.at_level("WARNING", logger="vibenative"):
        s = S.Settings.from_env(env)
    assert s.custom_head_path == legacy / "custom_head.npz"
    assert [r.levelname for r in caplog.records] == ["WARNING"]
    assert str(legacy) in caplog.text and str(tmp_path / "cfg" / "models") in caplog.text

    # once it has been moved, the new folder wins and nothing is said
    (tmp_path / "cfg" / "models").mkdir(parents=True)
    (tmp_path / "cfg" / "models" / "custom_head.npz").write_bytes(b"moved")
    caplog.clear()
    s = S.Settings.from_env(env)
    assert s.custom_head_path == tmp_path / "cfg" / "models" / "custom_head.npz"
    assert caplog.records == []


def test_model_dir_and_custom_head_still_override_the_default(tmp_path, legacy):
    legacy.mkdir()
    (legacy / "custom_head.npz").write_bytes(b"old")
    env = {"VIBE_CONFIG_DIR": str(tmp_path), "MODEL_DIR": str(tmp_path / "mine")}
    assert S.Settings.from_env(env).model_dir == tmp_path / "mine"
    env = {"VIBE_CONFIG_DIR": str(tmp_path), "CUSTOM_HEAD": str(tmp_path / "h.npz")}
    assert S.Settings.from_env(env).custom_head_path == tmp_path / "h.npz"


def test_derived_paths_follow_their_base(tmp_path):
    s = S.Settings(db_path=tmp_path / "a" / "lib.db", model_dir=tmp_path / "m")
    assert s.snapshots_dir == tmp_path / "a" / "vibe_snapshots"
    assert s.custom_head_path == tmp_path / "m" / "custom_head.npz"


def test_current_refuses_to_guess_in_the_test_suite(monkeypatch):
    monkeypatch.setattr(S, "_current", None)
    with pytest.raises(RuntimeError, match="no Settings installed"):
        S.current()


def test_current_builds_from_the_environment_once_outside_tests(monkeypatch, tmp_path):
    # What a script gets when it imports a module without create_app().
    built = S.Settings(db_path=tmp_path / "x.db", model_dir=tmp_path / "m")
    calls = []
    monkeypatch.setattr(S, "_current", None)
    monkeypatch.setattr(S, "_implicit", True)
    monkeypatch.setattr(S.Settings, "from_env", classmethod(lambda cls: calls.append(1) or built))
    assert S.current() is built and S.current() is built
    assert calls == [1]


def test_create_app_installs_its_settings(settings, tmp_path):
    import dataclasses

    import vibenative

    mine = dataclasses.replace(settings, max_upload_mb=7)
    app = vibenative.create_app(mine)
    assert S.current() is mine and app.config["SETTINGS"] is mine
    assert app.config["MAX_CONTENT_LENGTH"] == 7 * 1024 * 1024


def test_nothing_reads_the_environment_at_import():
    # Import every module of the package in a fresh interpreter whose os.environ
    # records each read made from vibenative code. Importing must make none.
    snippet = r"""
import os, pkgutil, importlib, sys

reads = []

class Env(dict):
    def _note(self, key):
        f = sys._getframe(2)
        if f.f_globals.get("__name__", "").startswith("vibenative"):
            reads.append((f.f_globals["__name__"], key))
    def get(self, key, default=None):
        self._note(key)
        return super().get(key, default)
    def __getitem__(self, key):
        self._note(key)
        return super().__getitem__(key)
    def __contains__(self, key):
        self._note(key)
        return super().__contains__(key)

os.environ = Env(os.environ)
os.getenv = os.environ.get
import vibenative
for m in pkgutil.walk_packages(vibenative.__path__, "vibenative."):
    if m.name != "vibenative.__main__":
        importlib.import_module(m.name)
print(reads)
"""
    out = subprocess.run(  # nosec B603  # fixed argv, no shell
        [sys.executable, "-c", snippet],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
        env={**os.environ, "FAKE_ANALYZER": "1"},
    )
    assert out.stdout.strip() == "[]", out.stdout + out.stderr
