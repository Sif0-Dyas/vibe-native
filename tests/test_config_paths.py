"""Where settings.ini and taxonomy.json live: dev vs a packaged build vs the override.

The packaged build is installed into Program Files, which a normal user cannot
write. These files used to sit next to the exe, so /db-path and every Genres-tab
taxonomy edit failed for anyone who wasn't an administrator. They now live in
%APPDATA%\\Vibedentify, seeded once from the settings.ini the installer writes
beside the exe.

"Packaged" is simulated: sys.frozen is set, exe_dir() points at a temp "install
folder" and APPDATA at a temp profile, so nothing here touches real folders.
"""

import configparser
import os
import stat
import sys

import pytest

from vibenative import paths
from vibenative.taxonomy import overlay


def _ini(path, db_path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"[vibenative]\ndb_path = {db_path}\n", encoding="utf-8")


def _db_path_in(path):
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(path, encoding="utf-8")
    return cp.get("vibenative", "db_path")


@pytest.fixture()
def packaged(tmp_path, monkeypatch, use_settings):
    """A simulated installed build: returns (install folder, per-user config dir)."""
    app = tmp_path / "Program Files" / "Vibedentify"
    app.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths, "exe_dir", lambda: app)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    use_settings(config_dir=None, taxonomy=None)
    return app, tmp_path / "Roaming" / "Vibedentify"


def test_resolution_dev_packaged_and_override(tmp_path, monkeypatch, use_settings):
    use_settings(config_dir=None, taxonomy=None)

    # dev: the repo root, exactly as before
    repo = paths.Path(paths.__file__).resolve().parents[2]
    assert paths.config_dir() == repo
    assert paths.settings_ini() == repo / "settings.ini"
    assert overlay.path() == repo / "taxonomy.json"

    # packaged: %APPDATA%\Vibedentify, never the exe's folder
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths, "exe_dir", lambda: tmp_path / "app")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    cfg = tmp_path / "Roaming" / "Vibedentify"
    assert paths.config_dir() == cfg
    assert paths.settings_ini() == cfg / "settings.ini"
    assert overlay.path() == cfg / "taxonomy.json"

    # the override wins in either mode
    use_settings(config_dir=tmp_path / "override")
    assert paths.settings_ini() == tmp_path / "override" / "settings.ini"
    monkeypatch.delattr(sys, "frozen")
    assert overlay.path() == tmp_path / "override" / "taxonomy.json"


def test_installer_seed_is_copied_exactly_once(packaged, monkeypatch):
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
    app, cfg = packaged
    _ini(app / "settings.ini", r"D:\Music\genre_v2.db")

    def fail(*a, **k):
        raise PermissionError("profile is read-only")

    monkeypatch.setattr(paths.shutil, "copyfile", fail)
    assert not paths.settings_ini().exists()
    assert paths.settings_ini_for_read() == app / "settings.ini"


def test_db_path_and_taxonomy_edits_write_to_the_config_dir(client, tmp_path, use_settings):
    cfg = tmp_path / "config"  # conftest's Settings.config_dir
    use_settings(taxonomy=None)

    r = client.post("/api/v1/db-path", json={"path": str(tmp_path / "lib.db")})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["settings_ini"] == str(cfg / "settings.ini")
    assert _db_path_in(cfg / "settings.ini") == str(tmp_path / "lib.db")

    r = client.post("/api/v1/taxonomy/overlay", json={"archgenre": {"Halftime": "Drum n Bass"}})
    assert r.status_code == 200, r.get_json()
    saved = (cfg / "taxonomy.json").read_text(encoding="utf-8")
    assert '"Halftime": "Drum n Bass"' in saved
    overlay.load(force=True)


def test_read_only_installer_ini_no_longer_breaks_db_path(client, packaged, tmp_path):
    # The Program Files case: the installer's settings.ini can be read but not
    # written. /db-path used to write it in place and fail; now it writes the
    # per-user copy and leaves the installer's file alone.
    app, cfg = packaged
    seed = app / "settings.ini"
    _ini(seed, r"%USERPROFILE%\genre_v2.db")
    os.chmod(seed, stat.S_IREAD)
    try:
        r = client.post("/api/v1/db-path", json={"path": str(tmp_path / "moved.db")})
        assert r.status_code == 200, r.get_json()
        assert r.get_json()["settings_ini"] == str(cfg / "settings.ini")
        assert _db_path_in(cfg / "settings.ini") == str(tmp_path / "moved.db")
        assert _db_path_in(seed) == r"%USERPROFILE%\genre_v2.db"  # untouched
    finally:
        os.chmod(seed, stat.S_IREAD | stat.S_IWRITE)


@pytest.mark.skipif(sys.platform != "win32", reason="%VAR% expansion is Windows-only (ntpath)")
def test_userprofile_db_path_resolves_to_the_file_the_app_opens(tmp_path, monkeypatch):
    # The installer writes db_path=%USERPROFILE%\genre_v2.db unexpanded; the app
    # expands it on read. Resolve it the way startup does (Settings.from_env, with
    # no GENRE_DB), open a connection through db.db(), and check where the file
    # actually landed.
    from contextlib import closing

    from vibenative import db, settings

    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setenv("USERPROFILE", str(profile))  # what expandvars reads
    _ini(tmp_path / "config" / "settings.ini", r"%USERPROFILE%\genre_v2.db")

    s = settings.use(settings.Settings.from_env({"VIBE_CONFIG_DIR": str(tmp_path / "config")}))
    assert "%" not in str(s.db_path)
    with closing(db.db()) as conn:
        conn.execute("CREATE TABLE t(x)")
    assert (profile / "genre_v2.db").is_file()
    assert s.db_path.samefile(profile / "genre_v2.db")


def test_without_a_fixture_nothing_reaches_the_real_library(tmp_path):
    # The collection-time case: a fresh interpreter imports conftest (as pytest
    # does, before any test module) and then vibenative.db, with no fixture in
    # play -- and with GENRE_DB in the parent environment pointing at the real
    # library, as a developer's shell might. db() must refuse (no Settings
    # installed, and conftest forbids building them from the environment), and
    # Settings.from_env() -- what main() and wsgi.py call -- must still land in
    # the throwaway session dir.
    import subprocess  # nosec B404  # runs this interpreter on a fixed snippet
    from pathlib import Path

    tests_dir = Path(__file__).resolve().parent
    env = {**os.environ, "GENRE_DB": str(Path.home() / "genre_v2.db")}
    env.pop("VIBE_CONFIG_DIR", None)
    env.pop("VIBE_TAXONOMY", None)
    snippet = (
        "import conftest\n"
        "from vibenative import db, settings\n"
        "try:\n"
        "    db.db()\n"
        "    print('opened')\n"
        "except RuntimeError:\n"
        "    print('refused')\n"
        "print(conftest.SESSION_DIR)\n"
        "print(settings.Settings.from_env().db_path)\n"
    )
    out = subprocess.run(  # nosec B603  # fixed argv, no shell
        [sys.executable, "-c", snippet],
        cwd=tests_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    ).stdout.splitlines()
    assert out[0] == "refused", out
    session_dir, db_path = Path(out[1]), Path(out[2])
    assert db_path.is_relative_to(session_dir), (db_path, session_dir)
    assert db_path != Path.home() / "genre_v2.db"


# --- the move from the folder used before the rename ---------------------------


def _legacy(tmp_path):
    old = tmp_path / "Roaming" / paths.LEGACY_APP_DIR_NAME
    _ini(old / "settings.ini", r"D:\Music\genre_v2.db")
    (old / "taxonomy.json").write_text('{"placements": {}}', encoding="utf-8")
    (old / "dev_token").write_text("tok", encoding="utf-8")
    (old / "models").mkdir()
    (old / "models" / "custom_head.npz").write_bytes(b"head")
    (old / "unrelated.txt").write_text("not ours to move", encoding="utf-8")
    return old


def test_first_packaged_start_moves_the_old_config_folder(tmp_path, packaged):
    from vibenative.settings import Settings

    old = _legacy(tmp_path)
    app, cfg = packaged
    assert paths.config_dir() == cfg
    for name in ("settings.ini", "taxonomy.json", "dev_token"):
        assert (cfg / name).is_file() and not (old / name).exists(), name
    assert (cfg / "models" / "custom_head.npz").read_bytes() == b"head"  # a trained head survives
    assert (old / "unrelated.txt").is_file()  # only what is ours moves
    # and it is read from its new home, before anything else looks
    env = {"APPDATA": str(tmp_path / "Roaming")}
    assert str(Settings.from_env(env).db_path) == r"D:\Music\genre_v2.db"


def test_the_move_never_overwrites_the_new_folder(tmp_path, packaged):
    old = _legacy(tmp_path)
    app, cfg = packaged
    _ini(cfg / "settings.ini", r"E:\Newer\genre_v2.db")
    moved = paths.move_legacy_config(old, cfg)
    assert "settings.ini" not in moved and "taxonomy.json" in moved
    assert _db_path_in(cfg / "settings.ini") == r"E:\Newer\genre_v2.db"
    assert (old / "settings.ini").is_file()  # left where it was, for the uninstaller
    assert paths.move_legacy_config(old, cfg) == []  # nothing left to do: once in effect


def test_a_dev_checkout_moves_nothing(tmp_path, monkeypatch, use_settings):
    old = _legacy(tmp_path)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    use_settings(config_dir=None, taxonomy=None)
    paths.config_dir()  # dev: the repo root
    assert (old / "settings.ini").is_file()
