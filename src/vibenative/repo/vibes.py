"""Vibes -- the user's own categories -- and their weighted members (``vibes``,
``vibe_tracks``)."""

import sqlite3

from . import reading, writing

_UPSERT_MEMBER = (
    "INSERT INTO vibe_tracks(vibe_id, hash, weight) VALUES(?,?,?) "
    "ON CONFLICT(vibe_id, hash) DO UPDATE SET weight=excluded.weight"
)


class NameTaken(ValueError):
    """Another vibe already has that name."""


def all_with_counts():
    """[(id, name, member count, description)] for every vibe, by name."""
    with reading() as c:
        return c.execute(
            "SELECT v.id, v.name, COUNT(t.hash), COALESCE(v.description, '') FROM vibes v "
            "LEFT JOIN vibe_tracks t ON t.vibe_id = v.id "
            "GROUP BY v.id ORDER BY v.name"
        ).fetchall()


def ids_and_names():
    """[(id, name)] for every vibe, unordered."""
    with reading() as c:
        return c.execute("SELECT id, name FROM vibes").fetchall()


def create(name) -> int:
    """A new, empty vibe called ``name``; its id. Raises NameTaken."""
    try:
        with writing() as c:
            return c.execute("INSERT INTO vibes(name) VALUES(?)", (name,)).lastrowid
    except sqlite3.IntegrityError as e:
        raise NameTaken(name) from e


def rename(vid, name) -> bool:
    """Rename vibe ``vid``; False if there is no such vibe. Raises NameTaken."""
    try:
        with writing() as c:
            return bool(c.execute("UPDATE vibes SET name=? WHERE id=?", (name, vid)).rowcount)
    except sqlite3.IntegrityError as e:
        raise NameTaken(name) from e


def set_description(vid, text) -> bool:
    """False if there is no such vibe."""
    with writing() as c:
        return bool(c.execute("UPDATE vibes SET description=? WHERE id=?", (text, vid)).rowcount)


def delete(vid) -> bool:
    """Delete vibe ``vid`` and every membership link, in one transaction; False
    if there was no such vibe."""
    with writing() as c:
        c.execute("DELETE FROM vibe_tracks WHERE vibe_id=?", (vid,))
        return bool(c.execute("DELETE FROM vibes WHERE id=?", (vid,)).rowcount)


def set_weight(vid, h, weight):
    """Make track ``h`` a member of vibe ``vid`` with ``weight``, or update it."""
    with writing() as c:
        c.execute(_UPSERT_MEMBER, (vid, h, weight))


def remove(vid, h):
    with writing() as c:
        c.execute("DELETE FROM vibe_tracks WHERE vibe_id=? AND hash=?", (vid, h))


def reset_weights(vid) -> int:
    """Every member of ``vid`` back to weight 1.0; how many members there are."""
    with writing() as c:
        return c.execute("UPDATE vibe_tracks SET weight=1.0 WHERE vibe_id=?", (vid,)).rowcount


def clear(vid) -> int:
    """Remove every member of ``vid`` (the vibe stays); how many were removed."""
    with writing() as c:
        return c.execute("DELETE FROM vibe_tracks WHERE vibe_id=?", (vid,)).rowcount


def members(vid):
    """[(hash, weight, title, filename)] for vibe ``vid``'s members, strongest
    pull first; title/filename are None for a member not (yet) in the library."""
    with reading() as c:
        return c.execute(
            "SELECT vt.hash, vt.weight, t.title, t.filename FROM vibe_tracks vt "
            "LEFT JOIN tracks t ON t.hash=vt.hash WHERE vt.vibe_id=? "
            "ORDER BY vt.weight DESC",
            (vid,),
        ).fetchall()


def member_hashes(vid) -> set:
    with reading() as c:
        return {
            r[0]
            for r in c.execute("SELECT hash FROM vibe_tracks WHERE vibe_id=?", (vid,)).fetchall()
        }


def membership():
    """[(vibe id, name, member hash or None)] -- every vibe, by name, one row per
    member (a vibe with none gets one row with hash None)."""
    with reading() as c:
        return c.execute(
            "SELECT v.id, v.name, vt.hash FROM vibes v "
            "LEFT JOIN vibe_tracks vt ON vt.vibe_id = v.id ORDER BY v.name"
        ).fetchall()


def export():
    """[(name, [(hash, weight), ...])] for every vibe, by name."""
    out = []
    with reading() as c:
        for vid, name in c.execute("SELECT id, name FROM vibes ORDER BY name").fetchall():
            out.append(
                (
                    name,
                    c.execute(
                        "SELECT hash, weight FROM vibe_tracks WHERE vibe_id=?", (vid,)
                    ).fetchall(),
                )
            )
    return out


def import_(vibes):
    """Merge ``[(name, [(hash, weight), ...])]`` in: each vibe is found by name or
    created, and its members upserted -- all under one lock, so two imports can't
    both create the same name. Returns (created, merged, links written)."""
    created = merged = links = 0
    with writing() as c:
        for name, tracks in vibes:
            row = c.execute("SELECT id FROM vibes WHERE name=?", (name,)).fetchone()
            if row:
                vid = row[0]
                merged += 1
            else:
                vid = c.execute("INSERT INTO vibes(name) VALUES(?)", (name,)).lastrowid
                created += 1
            for h, w in tracks:
                c.execute(_UPSERT_MEMBER, (vid, h, w))
                links += 1
    return created, merged, links


def vibe_centroid(vibe_id: int):
    """Preference-weighted center of a vibe (Rocchio relevance feedback):

        center = Σ (weightᵢ · embeddingᵢ) / Σ |weightᵢ|

    Positive-weight (liked) tracks pull the center toward them; negative-weight
    (disliked) tracks push it away. Cosine ranking is scale-invariant, so the
    normalization just keeps magnitudes tame. With all weights = 1 this reduces
    to the old plain mean. Returns None if the vibe has no usable members."""
    import numpy as np

    with reading() as c:
        rows = c.execute(
            "SELECT t.embedding, v.weight FROM vibe_tracks v JOIN tracks t "
            "ON t.hash=v.hash WHERE v.vibe_id=? AND t.embedding IS NOT NULL",
            (vibe_id,),
        ).fetchall()
    acc, wsum = None, 0.0
    for blob, w in rows:
        if not blob:
            continue
        w = 1.0 if w is None else float(w)
        emb = np.frombuffer(blob, dtype=np.float32) * w
        acc = emb if acc is None else acc + emb
        wsum += abs(w)
    if acc is None or wsum == 0:
        return None
    return acc / wsum
