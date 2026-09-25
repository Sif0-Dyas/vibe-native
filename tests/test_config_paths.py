"""Where settings.ini and taxonomy.json live: dev vs a packaged build vs the override.

The packaged build is installed into Program Files, which a normal user cannot
write. These files used to sit next to the exe, so /db-path and every Genres-tab
taxonomy edit failed for anyone who wasn't an administrator. They now live in
%APPDATA%\\Vibe Identify, seeded once from the settings.ini the installer writes
beside the exe.

"Packaged" is simulated: sys.frozen is set, exe_dir() points at a temp "install
folder" and APPDATA at a temp profile, so nothing here touches real folders.
"""

import configparser
import importlib
import os
import stat
import sys

import pytest


def _paths():
    # The client fixture re-imports the package, so always use the live module.
    return importlib.import_module("vibenative.paths")


def _ini(path, db_path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"[vibenative]\ndb_path = {db_path}\n", encoding="utf-8")


def _db_path_in(path):
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(path, encoding="utf-8")
    return cp.get("vibenative", "db_path")


@pytest.fixture()
def packaged(tmp_path, monkeypatch):
    """A simulated installed build: returns (install folder, per-user config dir)."""
    paths = _paths()
    app = tmp_path / "Program Files" / "Vibe Identify"
    app.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths, "exe_dir", lambda: app)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.delenv("VIBE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("VIBE_TAXONOMY", raising=False)
    return app, tmp_path / "Roaming" / "Vibe Identify"


def test_resolution_dev_packaged_and_override(tmp_path, monkeypatch):
    paths = _paths()
    taxonomy = importlib.import_module("vibenative.taxonomy")
    monkeypatch.delenv("VIBE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("VIBE_TAXONOMY", raising=False)

    # dev: the repo root, exactly as before
    repo = paths.Path(paths.__file__).resolve().parents[2]
    assert paths.config_dir() == repo
    assert paths.settings_ini() == repo / "settings.ini"
    assert taxonomy.path() == repo / "taxonomy.json"

    # packaged: %APPDATA%\Vibe Identify, never the exe's folder
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths, "exe_dir", lambda: tmp_path / "app")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    cfg = tmp_path / "Roaming" / "Vibe Identify"
    assert paths.config_dir() == cfg
    assert paths.settings_ini() == cfg / "settings.ini"
    assert taxonomy.path() == cfg / "taxonomy.json"

    # the override wins in either mode
    monkeypatch.setenv("VIBE_CONFIG_DIR", str(tmp_path / "override"))
    assert paths.settings_ini() == tmp_path / "override" / "settings.ini"
    monkeypatch.delattr(sys, "frozen")
    assert taxonomy.path() == tmp_path / "override" / "taxonomy.json"


def test_installer_seed_is_copied_exactly_once(packaged, monkeypatch):
    paths = _paths()
    app, cfg = packaged
    _ini(app / "settings.ini", r"D:\Music\genre_v2.db")

    copies = []
    real_copy = paths.shutil.copyfile
    monkeypatch.setattr(
        paths.shutil, "copyfile", lambda *a, **k: copies.append(a) or real_copy(*a, **k)
    )

    for _ in range(3):
        assert paths.settings_ini() == cfg / "settings.ini"
    assert len(copies) == 1
    assert _db_path_in(cfg / "settings.ini") == r"D:\Music\genre_v2.db"

    # a later change to the installer's file (a reinstall) no longer propagates
    _ini(app / "settings.ini", r"E:\elsewhere.db")
    paths.settings_ini()
    assert len(copies) == 1
    assert _db_path_in(paths.settings_ini_for_read()) == r"D:\Music\genre_v2.db"


def test_unwritable_profile_falls_back_to_reading_the_seed(packaged, monkeypatch):
    paths = _paths()
    app, cfg = packaged
    _ini(app / "settings.ini", r"D:\Music\genre_v2.db")

    def fail(*a, **k):
        raise PermissionError("profile is read-only")

    monkeypatch.setattr(paths.shutil, "copyfile", fail)
    assert not paths.settings_ini().exists()
    assert paths.settings_ini_for_read() == app / "settings.ini"


def test_db_path_and_taxonomy_edits_write_to_the_config_dir(client, tmp_path, monkeypatch):
    cfg = tmp_path / "config"  # conftest points VIBE_CONFIG_DIR here
    monkeypatch.delenv("VIBE_TAXONOMY", raising=False)

    r = client.post("/db-path", json={"path": str(tmp_path / "lib.db")})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["settings_ini"] == str(cfg / "settings.ini")
    assert _db_path_in(cfg / "settings.ini") == str(tmp_path / "lib.db")

    r = client.post("/taxonomy/overlay", json={"archgenre": {"Halftime": "Drum n Bass"}})
    assert r.status_code == 200, r.get_json()
    saved = (cfg / "taxonomy.json").read_text(encoding="utf-8")
    assert '"Halftime": "Drum n Bass"' in saved
    importlib.import_module("vibenative.taxonomy").load(force=True)


def test_read_only_installer_ini_no_longer_breaks_db_path(client, packaged, tmp_path):
    # The Program Files case: the installer's settings.ini can be read but not
    # written. /db-path used to write it in place and fail; now it writes the
    # per-user copy and leaves the installer's file alone.
    app, cfg = packaged
    seed = app / "settings.ini"
    _ini(seed, r"%USERPROFILE%\genre_v2.db")
    os.chmod(seed, stat.S_IREAD)
    try:
        r = client.post("/db-path", json={"path": str(tmp_path / "moved.db")})
        assert r.status_code == 200, r.get_json()
        assert r.get_json()["settings_ini"] == str(cfg / "settings.ini")
        assert _db_path_in(cfg / "settings.ini") == str(tmp_path / "moved.db")
        assert _db_path_in(seed) == r"%USERPROFILE%\genre_v2.db"  # untouched
    finally:
        os.chmod(seed, stat.S_IREAD | stat.S_IWRITE)


@pytest.mark.skipif(sys.platform != "win32", reason="%VAR% expansion is Windows-only (ntpath)")
def test_userprofile_db_path_resolves_to_the_file_the_app_opens(tmp_path, monkeypatch):
    # The installer writes db_path=%USERPROFILE%\genre_v2.db unexpanded; the app
    # expands it on read. Resolve it the way startup does (a fresh import of db),
    # open a connection through db.db(), and check where the file actually landed.
    from contextlib import closing

    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setenv("USERPROFILE", str(profile))
    monkeypatch.delenv("GENRE_DB", raising=False)
    _ini(
        tmp_path / "config" / "settings.ini", r"%USERPROFILE%\genre_v2.db"
    )  # conftest's VIBE_CONFIG_DIR

    # Put back BOTH the sys.modules entry and the package attribute afterwards:
    # import_module rebinds vibenative.db, and a module left bound there but missing
    # from sys.modules breaks any later importlib.reload(vibenative.db).
    pkg = importlib.import_module("vibenative")
    saved = (sys.modules.pop("vibenative.db", None), pkg.__dict__.get("db"))
    try:
        db = importlib.import_module("vibenative.db")
        assert "%" not in str(db.DB_PATH)
        with closing(db.db()) as conn:
            conn.execute("CREATE TABLE t(x)")
        assert (profile / "genre_v2.db").is_file()
        assert db.DB_PATH.samefile(profile / "genre_v2.db")
    finally:
        mod, attr = saved
        if mod is None:
            sys.modules.pop("vibenative.db", None)
        else:
            sys.modules["vibenative.db"] = mod
        if attr is None:
            pkg.__dict__.pop("db", None)
        else:
            pkg.db = attr
