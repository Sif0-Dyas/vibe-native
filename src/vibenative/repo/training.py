"""Training labels and rejections (``training_labels``, ``training_rejects``).

Two ways of naming a genre meet here. The labelling queue (routes/training)
matches the genre exactly, as the user typed it; the per-genre training-set
tools (trainsets) match it case-insensitively, so "house" and "House" are one
set. Each function says which it does.
"""

import time

from . import NotFound, reading, writing


# --- the labelling queue: exact genre -----------------------------------------
def label_hashes(genre) -> set:
    """Hashes labelled exactly ``genre``."""
    with reading() as c:
        return {r[0] for r in c.execute("SELECT hash FROM training_labels WHERE genre=?", (genre,))}


def reject_hashes(genre) -> set:
    """Hashes rejected for exactly ``genre``."""
    with reading() as c:
        return {
            r[0] for r in c.execute("SELECT hash FROM training_rejects WHERE genre=?", (genre,))
        }


def confirm(h, genre):
    """Label track ``h`` as ``genre`` (source 'propagation') and clear any reject
    of the same pair, in one locked transaction. Returns the track's filepath
    (possibly empty); raises NotFound if the track isn't in the library."""
    with writing() as c:
        row = c.execute("SELECT filepath FROM tracks WHERE hash=?", (h,)).fetchone()
        if not row:
            raise NotFound(h)
        c.execute(
            "INSERT OR IGNORE INTO training_labels(hash, genre, source, created) VALUES(?,?,?,?)",
            (h, genre, "propagation", time.time()),
        )
        c.execute("DELETE FROM training_rejects WHERE hash=? AND genre=?", (h, genre))
        return row[0]


def reject(h, genre):
    """Never offer track ``h`` for ``genre`` again."""
    with writing() as c:
        c.execute("INSERT OR IGNORE INTO training_rejects(hash, genre) VALUES(?,?)", (h, genre))


def add_manual(genre, hashes) -> dict:
    """Label every hash that is in the library as ``genre`` (source 'manual').
    Returns {hash: filepath, stripped} for those; hashes not in the library are
    left out. The lookup and the inserts share one lock."""
    with writing() as c:
        rows = {
            r[0]: (r[1] or "").strip()
            for r in c.execute(
                "SELECT hash, filepath FROM tracks WHERE hash IN (%s)"  # nosec B608  # ints/params below
                % ",".join("?" * len(hashes)),
                hashes,
            )
        }
        now = time.time()
        c.executemany(
            "INSERT OR IGNORE INTO training_labels(hash, genre, source, created) VALUES(?,?,?,?)",
            [(h, genre, "manual", now) for h in rows],
        )
    return rows


# --- per-genre training sets: genre matched case-insensitively -----------------
def _ci(genre):
    return (genre or "").strip().lower()


def labels_any_case(genre):
    """[(hash, source)] labelled ``genre`` in any case."""
    with reading() as c:
        return c.execute(
            "SELECT hash, source FROM training_labels WHERE LOWER(genre)=?", (_ci(genre),)
        ).fetchall()


def rejects_any_case(genre) -> list:
    """Hashes rejected for ``genre`` in any case."""
    with reading() as c:
        return [
            r[0]
            for r in c.execute(
                "SELECT hash FROM training_rejects WHERE LOWER(genre)=?", (_ci(genre),)
            )
        ]


def clear_any_case(genre):
    """Delete ``genre``'s labels and rejects (any case), in one transaction.
    Returns (labels deleted, rejects deleted)."""
    want = _ci(genre)
    with writing() as c:
        labels = c.execute("DELETE FROM training_labels WHERE LOWER(genre)=?", (want,)).rowcount
        rejects = c.execute("DELETE FROM training_rejects WHERE LOWER(genre)=?", (want,)).rowcount
    return labels, rejects


def import_labels(genre, hashes, rejects):
    """Label each of ``hashes`` found in the library as ``genre`` (source
    'import') and record ``rejects``, under one lock. Returns (found, missing):
    found is [(hash, filepath, stripped)] in the order given, missing the hashes
    the library doesn't have."""
    found, missing = [], []
    with writing() as c:
        for h in hashes:
            row = c.execute("SELECT filepath FROM tracks WHERE hash=?", (h,)).fetchone()
            if row is None:
                missing.append(h)
            else:
                found.append((h, (row[0] or "").strip()))
        now = time.time()
        c.executemany(
            "INSERT OR IGNORE INTO training_labels(hash, genre, source, created) VALUES(?,?,?,?)",
            [(h, genre, "import", now) for h, _ in found],
        )
        c.executemany(
            "INSERT OR IGNORE INTO training_rejects(hash, genre) VALUES(?,?)",
            [(h, genre) for h in rejects],
        )
    return found, missing
