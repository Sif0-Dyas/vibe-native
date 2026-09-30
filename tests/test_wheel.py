"""A built wheel carries every subpackage.

pyproject.toml used to list the packages by hand, and the list stopped at
``vibenative`` and ``vibenative.routes``: a wheel installed anywhere but an
editable checkout had no ``repo`` or ``taxonomy`` and failed at import. The
packages are discovered now. This builds a wheel the way a user would get one
and looks inside.

The build runs on a copy of pyproject.toml, README.md and src/ in tmp_path, so
setuptools' build/ and egg-info never land in the repo.
"""

import shutil
import subprocess  # nosec B404  # sys.executable with fixed args, no shell
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_the_wheel_contains_every_subpackage(tmp_path):
    for name in ("pyproject.toml", "README.md"):
        shutil.copy(ROOT / name, tmp_path / name)
    shutil.copytree(
        ROOT / "src",
        tmp_path / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"),
    )
    out = tmp_path / "wheelhouse"
    subprocess.run(  # nosec B603  # sys.executable with fixed args, no shell
        [
            sys.executable,
            "-c",
            "import sys; from setuptools import build_meta; build_meta.build_wheel(sys.argv[1])",
            str(out),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        timeout=300,
    )
    (wheel,) = out.glob("vibenative-*.whl")
    names = zipfile.ZipFile(wheel).namelist()
    packages = {n.rsplit("/", 1)[0] for n in names if n.endswith("/__init__.py")}

    assert {"vibenative/repo", "vibenative/taxonomy"} <= packages
    # every package in the source tree, not just the two that were missing
    source = {
        p.parent.relative_to(ROOT / "src").as_posix()
        for p in (ROOT / "src" / "vibenative").rglob("__init__.py")
        if "__pycache__" not in p.parts
    }
    assert packages == source
