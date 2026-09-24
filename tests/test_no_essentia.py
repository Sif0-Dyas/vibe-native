"""Guard: nothing that ships or trains may import essentia.

Essentia is AGPL and the app is being sold, so the engine was rebuilt on ONNX
Runtime. This walks every .py/.pyw file under src/, desktop/ and training/,
parses it with ``ast`` and fails on any ``import essentia[...]`` or
``from essentia[...] import ...``. It is a parse, not a text grep, so comments
and docstrings that mention essentia (history, oracle provenance) are fine.

tools/ is deliberately outside the walk: it holds the one-off model-conversion
scripts, which never ship.
"""

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ROOTS = ("src", "desktop", "training")


def _is_essentia(module: str | None) -> bool:
    return module is not None and (module == "essentia" or module.startswith("essentia."))


def _essentia_imports(path: Path):
    """Yield "path:line: <import>" for each essentia import in one file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    rel = path.relative_to(_REPO_ROOT).as_posix()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_essentia(alias.name):
                    yield f"{rel}:{node.lineno}: import {alias.name}"
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and _is_essentia(node.module):
            yield f"{rel}:{node.lineno}: from {node.module} import ..."


def _source_files():
    for root in _ROOTS:
        for path in sorted((_REPO_ROOT / root).rglob("*")):
            if path.suffix in (".py", ".pyw") and path.is_file():
                yield path


def test_no_essentia_imports():
    files = list(_source_files())
    # A typo in _ROOTS would otherwise make this pass vacuously.
    assert {p.relative_to(_REPO_ROOT).parts[0] for p in files} == set(_ROOTS)
    hits = [hit for path in files for hit in _essentia_imports(path)]
    assert not hits, "essentia imports found:\n" + "\n".join(hits)
