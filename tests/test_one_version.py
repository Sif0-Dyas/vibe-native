"""One version, written once: pyproject.toml's [project].version.

vibenative.__version__ reads it through importlib.metadata; /status reports it;
the exe build, the installer build and smoke_dist take it from tools/version.py;
the installer script has no default of its own.
"""

import importlib.util
import re
import tomllib
from pathlib import Path

import vibenative

ROOT = Path(__file__).resolve().parent.parent


def _pyproject_version():
    with (ROOT / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)["project"]["version"]


def _tools_version():
    spec = importlib.util.spec_from_file_location("tools_version", ROOT / "tools" / "version.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_version_is_pyprojects():
    assert vibenative.__version__ == _pyproject_version()
    assert _tools_version().pyproject_version() == _pyproject_version()


def test_status_reports_it(client):
    assert client.get("/api/v1/status").get_json()["version"] == _pyproject_version()


def test_no_version_literal_left_to_drift():
    """The number appears in pyproject.toml and uv.lock only -- not in the
    package, the build tools or the installer script."""
    v = re.escape(_pyproject_version())
    for rel in (
        "src/vibenative/__init__.py",
        "tools/build_exe.py",
        "tools/build_installer.py",
        "tools/installer.iss",
        "tools/smoke_dist.py",
        "Vibe Identify.spec",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert not re.search(rf"(?<![\d.]){v}(?![\d.])", text), rel
    iss = (ROOT / "tools" / "installer.iss").read_text(encoding="utf-8")
    assert "#error MyAppVersion is not set" in iss


def test_the_frozen_build_bundles_the_metadata_it_reads():
    spec = (ROOT / "Vibe Identify.spec").read_text(encoding="utf-8")
    assert 'copy_metadata("vibenative")' in spec
