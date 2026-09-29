"""Tags and their assignment to tracks (``tags``, ``track_tags``)."""

from . import reading


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
