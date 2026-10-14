"""One product name, "Vibedentify", wherever a user sees it.

The package stays ``vibenative`` in code; the name a user reads -- the page and
window titles, the taskbar identity, the config and log folders, the installer,
the User-Agent sent to MusicBrainz / Discogs -- comes from ``PRODUCT_NAME``. The
shell and the installer can't import the package, so they spell it out; these
tests hold them to it.

The two-word name used before the rename is gone from everything tracked, except the
history (docs/history) and the few lines that must name it to clean up after
it: the one-time move of the old config folder, and the installer removing the
old exe, shortcuts and folders. Those are listed in LEGACY_NAME_ALLOWED, each
with the line it may appear on, so a new use anywhere else still fails.
"""

import re
import subprocess  # nosec B404  # git ls-files, fixed args
from pathlib import Path

from vibenative import PRODUCT_NAME, __version__
from vibenative.lookup import USER_AGENT

ROOT = Path(__file__).resolve().parent.parent

# Built rather than written out, so this file needs no exemption of its own.
OLD_NAME = "Vibe" + " Identify"
_OLD = re.compile(r"vibe ?identify", re.I)

# file -> the lines that may name the old product, and why.
LEGACY_NAME_ALLOWED = {
    # the config folder used before the rename, moved once on first start
    "src/vibenative/paths.py": {f'LEGACY_APP_DIR_NAME = "{OLD_NAME}"'},
    # the installer: the old name defined once, for the upgrade's and the
    # uninstaller's cleanup of the old exe, shortcuts and folders
    "tools/installer.iss": {f'#define LegacyAppName "{OLD_NAME}"'},
}


def test_the_product_name():
    assert PRODUCT_NAME == "Vibedentify"


def test_the_user_agent_is_the_product_and_its_version():
    assert USER_AGENT.startswith(f"Vibedentify/{__version__} (+https://")


def test_the_shell_and_installer_spell_the_same_name():
    shell = (ROOT / "desktop" / "genre_app.pyw").read_text(encoding="utf-8")
    assert re.search(r'^PRODUCT_NAME = "(.*)"$', shell, re.M).group(1) == PRODUCT_NAME
    assert 'SetCurrentProcessExplicitAppUserModelID("Vibedentify.App")' in shell
    # the WebView2 profile keeps its folder: renaming it would sign the user out of
    # everything the page stored (IndexedDB, local settings)
    assert '"Vibenative", "webview"' in shell
    iss = (ROOT / "tools" / "installer.iss").read_text(encoding="utf-8")
    assert re.search(r'^#define MyAppName "(.*)"$', iss, re.M).group(1) == PRODUCT_NAME
    assert re.search(r'^#define MyAppExeName "(.*)"$', iss, re.M).group(1) == f"{PRODUCT_NAME}.exe"
    # the uninstaller removes the log folder and both config folders
    for folder in (
        r"{localappdata}\{#MyAppName}",
        r"{userappdata}\{#MyAppName}",
        r"{userappdata}\{#LegacyAppName}",
    ):
        assert folder in iss, folder


def test_the_config_folder_is_the_product():
    from vibenative import paths

    assert paths.APP_DIR_NAME == PRODUCT_NAME
    assert paths.LEGACY_APP_DIR_NAME == OLD_NAME


def test_the_page_title_is_the_product(client):
    assert f"<title>{PRODUCT_NAME}</title>".encode() in client.get("/").data


def test_the_old_name_is_gone():
    files = subprocess.run(  # nosec B603 B607
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    hits = []
    for f in files:
        if f.startswith("docs/history/") or f == "uv.lock":
            continue
        if _OLD.search(f):
            hits.append(f"{f}: in the file name")
        try:
            text = (ROOT / f).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        allowed = LEGACY_NAME_ALLOWED.get(f, set())
        for n, line in enumerate(text.splitlines(), 1):
            if _OLD.search(line) and line.strip() not in allowed:
                hits.append(f"{f}:{n}: {line.strip()}")
    assert hits == []
