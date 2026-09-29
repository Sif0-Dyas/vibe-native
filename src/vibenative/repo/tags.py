"""Tags and their assignment to tracks (``tags``, ``track_tags``)."""

from . import reading, writing


def names_by_hash():
    """{hash: [tag name, ...]} for the whole library in one query.

    Fetched in bulk rather than per track: the map reads every track, and a
    per-track lookup would turn one query into thousands.
    """
    out = {}
    with reading() as c:
        for h, name in c.execute(
            "SELECT tt.hash, t.name FROM track_tags tt JOIN tags t ON t.id = tt.tag_id"
        ):
            out.setdefault(h, []).append(name)
    return out


def all_with_counts():
    """[(id, name, number of tracks tagged)] for every tag, by name."""
    with reading() as c:
        return c.execute(
            "SELECT t.id, t.name, COUNT(tt.hash) FROM tags t "
            "LEFT JOIN track_tags tt ON tt.tag_id = t.id "
            "GROUP BY t.id ORDER BY t.name"
        ).fetchall()


def get_or_create(name) -> int:
    """The id of the tag called ``name``, creating it if there is none."""
    with writing() as c:
        row = c.execute("SELECT id FROM tags WHERE name=?", (name,)).fetchone()
        if row:
            return row[0]
        return c.execute("INSERT INTO tags(name) VALUES(?)", (name,)).lastrowid


def toggle(tag_id, h) -> bool:
    """Tag the track if it isn't, untag it if it is. True if it is now tagged."""
    with writing() as c:
        row = c.execute(
            "SELECT 1 FROM track_tags WHERE tag_id=? AND hash=?", (tag_id, h)
        ).fetchone()
        if row:
            c.execute("DELETE FROM track_tags WHERE tag_id=? AND hash=?", (tag_id, h))
            return False
        c.execute("INSERT OR IGNORE INTO track_tags(tag_id, hash) VALUES(?,?)", (tag_id, h))
        return True


def for_hashes(hashes):
    """{hash: [{id, name}, ...]} for every hash given, in one query per 500.

    Every hash asked for is a key in the answer, tagged or not, so a caller
    can tell "no tags" from "not asked".
    """
    out = {h: [] for h in hashes}
    keys = list(out)
    with reading() as c:
        for i in range(0, len(keys), 500):
            chunk = keys[i : i + 500]
            q = ",".join("?" * len(chunk))
            for h, tid, name in c.execute(
                f"SELECT tt.hash, t.id, t.name FROM track_tags tt JOIN tags t ON t.id=tt.tag_id "  # nosec B608
                f"WHERE tt.hash IN ({q}) ORDER BY t.name",
                chunk,
            ):
                out[h].append({"id": tid, "name": name})
    return out
