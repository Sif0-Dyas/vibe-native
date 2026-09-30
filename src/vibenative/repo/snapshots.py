"""The learned state a snapshot holds, read and written as one: the training
tables (whole) and each track's manual override (inside its payload).

``tables`` is the caller's allow-list (snapshots._TABLES); table names are
interpolated only from it."""

import json

from ..style import dominant_style
from . import reading, writing


def capture(tables):
    """{"tables": {name: {"columns", "rows"}}, "overrides": {hash: genre}}."""
    state = {"tables": {}, "overrides": {}}
    with reading() as c:
        for t in tables:
            cur = c.execute(f"SELECT * FROM {t}")  # nosec B608  # fixed table allow-list
            cols = [d[0] for d in cur.description]
            state["tables"][t] = {"columns": cols, "rows": [list(r) for r in cur.fetchall()]}
        for h, payload in c.execute("SELECT hash, payload FROM tracks"):
            try:
                p = json.loads(payload) if isinstance(payload, str) else (payload or {})
            except (TypeError, ValueError):
                continue
            if p.get("override"):
                state["overrides"][h] = p["override"]
    return state


def clear(tables):
    """Empty ``tables`` and drop every track's override, in one transaction."""
    with writing() as c:
        for t in tables:
            c.execute(f"DELETE FROM {t}")  # nosec B608  # fixed table allow-list
        for h, payload in c.execute("SELECT hash, payload FROM tracks").fetchall():
            try:
                p = json.loads(payload) if isinstance(payload, str) else (payload or {})
            except (TypeError, ValueError):
                continue
            if p.get("override"):
                p.pop("override", None)
                c.execute(
                    "UPDATE tracks SET payload=?, style=? WHERE hash=?",
                    (json.dumps(p), dominant_style(p), h),
                )


def restore(state, tables):
    """Write ``state`` (from :func:`capture`) back, in one transaction: rows of the
    allow-listed tables, then each override into its track's payload (a track no
    longer in the library is skipped)."""
    with writing() as c:
        for t, blob in state.get("tables", {}).items():
            if t not in tables:
                continue  # ignore anything not on the allow-list
            cols, rows = blob.get("columns") or [], blob.get("rows") or []
            if not cols or not rows:
                continue
            ph = ",".join("?" * len(cols))
            names = ",".join(cols)
            c.executemany(
                f"INSERT OR REPLACE INTO {t} ({names}) VALUES ({ph})",  # nosec B608
                [tuple(r) for r in rows],
            )
        for h, override in (state.get("overrides") or {}).items():
            row = c.execute("SELECT payload FROM tracks WHERE hash=?", (h,)).fetchone()
            if not row:
                continue  # the track is gone; its override has nowhere to land
            try:
                p = json.loads(row[0]) if isinstance(row[0], str) else (row[0] or {})
            except (TypeError, ValueError):
                continue
            p["override"] = override
            c.execute(
                "UPDATE tracks SET payload=?, style=? WHERE hash=?",
                (json.dumps(p), dominant_style(p), h),
            )
