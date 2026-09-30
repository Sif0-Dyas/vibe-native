"""SQL lives in two places: vibenative/db.py (connections, the write lock, the
schema and its migrations) and vibenative/repo/ (every read and write of rows).

Everything else -- the routes, the domain modules (ratings, snapshots, relabel,
trainsets, insight, genres, filepaths...), the entry points -- calls a repo
function or nothing. So in every module under src/vibenative except those two,
none of these may appear: running SQL (execute / executemany / cursor), taking
the write lock (_db_lock), or opening a connection (db()).
"""

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "vibenative"
ALLOWED = {SRC / "db.py"} | set((SRC / "repo").rglob("*.py"))
GUARDED = sorted(p for p in SRC.rglob("*.py") if p not in ALLOWED)
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
        f"{path.relative_to(SRC).as_posix()} reaches the database directly; "
        "use vibenative.repo:\n" + "\n".join(hits)
    )


def test_the_guard_covers_everything_but_db_and_repo():
    names = {p.relative_to(SRC).as_posix() for p in GUARDED}
    assert {
        "routes/analysis.py",
        "routes/library.py",
        "routes/map.py",
        "routes/playlists.py",
        "routes/tags.py",
        "routes/training.py",
        "routes/vibes.py",
        "trainsets.py",
        "ratings.py",
        "snapshots.py",
        "relabel.py",
        "filepaths.py",
        "insight.py",
        "genres.py",
        "analysis.py",
        "__init__.py",
    } <= names
    assert not any(n == "db.py" or n.startswith("repo/") for n in names)
    assert len(GUARDED) == len(list(SRC.rglob("*.py"))) - len(ALLOWED)


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
