"""One product name, "Vibe Identify", wherever a user sees it.

The package stays ``vibenative`` in code; the name a user reads -- the page and
window titles, the taskbar identity, the log folder, the installer, the
User-Agent sent to MusicBrainz / Discogs -- comes from ``PRODUCT_NAME``. The
shell and the installer can't import the package, so they spell it out; these
tests hold them to it. The old name is gone from everything shipped.
"""

import re
import subprocess  # nosec B404  # git ls-files, fixed args
from pathlib import Path

from vibenative import PRODUCT_NAME, __version__
from vibenative.lookup import USER_AGENT

ROOT = Path(__file__).resolve().parent.parent


def test_the_product_name():
    assert PRODUCT_NAME == "Vibe Identify"


def test_the_user_agent_is_the_product_and_its_version():
    assert USER_AGENT.startswith(f"VibeIdentify/{__version__} (+https://")


def test_the_shell_and_installer_spell_the_same_name():
    shell = (ROOT / "desktop" / "genre_app.pyw").read_text(encoding="utf-8")
    assert re.search(r'^PRODUCT_NAME = "(.*)"$', shell, re.M).group(1) == PRODUCT_NAME
    iss = (ROOT / "tools" / "installer.iss").read_text(encoding="utf-8")
    assert re.search(r'^#define MyAppName "(.*)"$', iss, re.M).group(1) == PRODUCT_NAME
    # the uninstaller removes the log folder under its new name
    assert r"{localappdata}\{#MyAppName}" in iss


def test_the_page_title_is_the_product(client):
    assert f"<title>{PRODUCT_NAME}</title>".encode() in client.get("/").data


def test_the_old_name_is_gone():
    """Nothing tracked says "Vibedentify" except history: the plan and docs/history
    describe the rename, and tools/make_oracle.py imports the legacy reference
    implementation, whose package really is called ``vibedentify``."""
    allowed = {"docs/REMEDIATION_PLAN.md", "tools/make_oracle.py", "tests/test_one_name.py"}
    files = subprocess.run(  # nosec B603 B607
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    hits = []
    for f in files:
        if f in allowed or f.startswith("docs/history/"):
            continue
        p = ROOT / f
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "vibedentify" in text.lower():
            hits.append(f)
    assert hits == []
