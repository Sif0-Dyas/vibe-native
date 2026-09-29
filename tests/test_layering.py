"""Layering: nothing outside vibenative/routes/ imports from it.

Routes are the HTTP edge. Domain modules (style, trainsets, insight...) and the
repository layer sit beneath them, so a dependency pointing up -- like trainsets
reaching into routes._shared for the dominant style -- is a cycle waiting to
happen and hides domain logic in the web layer.

The one exception is the package's own __init__.py: create_app() is where the
app is assembled, and it has to register the routes' blueprint.
"""

import ast
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parent.parent / "src" / "vibenative"
ROUTES = "vibenative.routes"
COMPOSITION_ROOT = PKG / "__init__.py"


def _module_name(path, pkg):
    rel = path.relative_to(pkg.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(path, pkg):
    """Every module ``path`` imports, as absolute dotted names (relative imports
    resolved; ``from X import y`` also yields ``X.y``, which may be a module)."""
    name = _module_name(path, pkg)
    package = name if path.name == "__init__.py" else name.rpartition(".")[0]
    out = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out += [(node.lineno, a.name) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - (node.level - 1)]
                mod = ".".join(base + ([node.module] if node.module else []))
            else:
                mod = node.module or ""
            out.append((node.lineno, mod))
            out += [(node.lineno, f"{mod}.{a.name}") for a in node.names]
    return out


def _routes_imports(path, pkg=PKG):
    return [
        f"{path.relative_to(pkg).as_posix()}:{line} imports {mod}"
        for line, mod in _imports(path, pkg)
        if mod == ROUTES or mod.startswith(ROUTES + ".")
    ]


OUTSIDE = sorted(
    p
    for p in PKG.rglob("*.py")
    if "routes" not in p.relative_to(PKG).parts and p != COMPOSITION_ROOT
)


def test_nothing_outside_routes_imports_routes():
    hits = [h for p in OUTSIDE for h in _routes_imports(p)]
    assert not hits, "\n".join(hits)


def test_the_walk_sees_the_modules_that_matter():
    names = {p.relative_to(PKG).as_posix() for p in OUTSIDE}
    assert {"trainsets.py", "style.py", "insight.py", "repo/tracks.py", "db.py"} <= names


@pytest.mark.parametrize(
    "rel, source",
    [
        ("trainsets.py", "from .routes._shared import _dominant_style\n"),
        ("trainsets.py", "from . import routes\n"),
        ("trainsets.py", "def f():\n    from .routes import bp\n"),
        ("repo/tracks.py", "from ..routes.analysis import UploadError\n"),
        ("style.py", "import vibenative.routes.map\n"),
    ],
)
def test_the_walk_catches(tmp_path, rel, source):
    fake_pkg = tmp_path / "vibenative"
    target = fake_pkg / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    assert _routes_imports(target, fake_pkg)


def test_the_walk_passes_imports_of_siblings(tmp_path):
    target = tmp_path / "vibenative" / "repo" / "tracks.py"
    target.parent.mkdir(parents=True)
    target.write_text("from ..style import dominant_style\nfrom . import reading\n", "utf-8")
    assert not _routes_imports(target, tmp_path / "vibenative")
