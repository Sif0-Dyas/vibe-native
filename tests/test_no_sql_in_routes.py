"""Routes contain no SQL: they call vibenative.repo, which owns the statements
and the write lock.

A route that needs data calls a repo function (or nothing). So in routes/*.py --
and in trainsets.py, whose SQL moved to repo/training.py -- none of these may
appear: running SQL (execute / executemany / cursor), taking the write lock
(_db_lock), or opening a connection (db()).
"""

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "vibenative"
GUARDED = sorted((SRC / "routes").glob("*.py")) + [SRC / "trainsets.py"]
FORBIDDEN = re.compile(r"\.(?:execute|executemany|cursor)\(|\b_db_lock\b|\bdb\(\)")


def _hits(text):
    return [
        f"{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if FORBIDDEN.search(line)
    ]


@pytest.mark.parametrize("path", GUARDED, ids=lambda p: p.relative_to(SRC).as_posix())
def test_module_contains_no_sql(path):
    hits = _hits(path.read_text(encoding="utf-8"))
    assert not hits, (
        f"{path.name} reaches the database directly; use vibenative.repo:\n" + "\n".join(hits)
    )


def test_the_guard_covers_every_route_module():
    assert {p.name for p in GUARDED} >= {
        "analysis.py",
        "library.py",
        "map.py",
        "playlists.py",
        "tags.py",
        "training.py",
        "vibes.py",
        "trainsets.py",
    }


@pytest.mark.parametrize(
    "line",
    [
        'c.execute("SELECT 1")',
        "conn.executemany(q, rows)",
        "cur = conn.cursor()",
        "with _db_lock, closing(db()) as conn, conn as c:",
        "conn = db()",
    ],
)
def test_the_guard_catches(line):
    assert _hits(line)


@pytest.mark.parametrize(
    "line",
    [
        "rows = tracks_repo.listing()",
        "init_db()",
        "from ..db import cosine, track_embedding",
        "vibes_repo.set_weight(vid, h, weight)",
    ],
)
def test_the_guard_passes(line):
    assert not _hits(line)
