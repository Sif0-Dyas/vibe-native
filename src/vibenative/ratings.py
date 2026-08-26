"""Per-track ratings, and the Rekordbox collection XML they export into.

A rating is three things the analysis can't know: how good the track is (stars),
a letter grade, and a free note. They live in their own table rather than in the
analysis payload, which gets rewritten whenever a track is re-analysed.

Nothing here writes to your audio files. The rating exists in this app's database
and materialises only when you export a playlist -- file-tag editing is a separate
concern with a much bigger blast radius.

**The Rekordbox encoding.** Its collection XML does not store 1-5. The ``Rating``
attribute takes 0, 51, 102, 153, 204 or 255 -- one 51-step per star -- and any
other value is ignored or rounded unpredictably by the importer. ``STARS_TO_RB``
is that mapping, and it's applied at export only, so the number in the database
stays the one you actually set.

The grade and note are combined into the single ``Comments`` field, since
Rekordbox has nowhere else to put them: grade first, then the note, joined with
" - " exactly as typed -- ``A - peak time, big room``.
"""

import time
from contextlib import closing
from xml.sax.saxutils import quoteattr

from .db import _db_lock, db

# Rekordbox stores stars as 51-point steps, not 1-5. Values off this ladder are
# not honoured by the importer, so map rather than scale.
STARS_TO_RB = {0: 0, 1: 51, 2: 102, 3: 153, 4: 204, 5: 255}

# Letter grades offered in the UI. Free-form text still goes in the note, so this
# list only has to cover the common case, not every scheme anyone might use.
GRADES = ["A", "B", "C", "D", "F"]

MAX_NOTE = 1000


def _clamp_stars(v):
    try:
        return max(0, min(5, int(v)))
    except (TypeError, ValueError):
        return 0


def get(hash_):
    """One track's rating, or the empty rating if it has none."""
    with _db_lock, closing(db()) as conn, conn as c:
        row = c.execute("SELECT stars, grade, note FROM ratings WHERE hash=?", (hash_,)).fetchone()
    if not row:
        return {"hash": hash_, "stars": 0, "grade": "", "note": ""}
    return {"hash": hash_, "stars": row[0] or 0, "grade": row[1] or "", "note": row[2] or ""}


def get_many(hashes):
    """{hash: rating} for many tracks in one query -- the list and map views need
    every rating at once, and a per-track lookup would be thousands of queries."""
    hashes = list(hashes)
    if not hashes:
        return {}
    out = {}
    with _db_lock, closing(db()) as conn, conn as c:
        # chunked so a huge library can't blow SQLite's variable limit (999)
        for i in range(0, len(hashes), 500):
            chunk = hashes[i : i + 500]
            q = ",".join("?" * len(chunk))
            for h, stars, grade, note in c.execute(
                f"SELECT hash, stars, grade, note FROM ratings WHERE hash IN ({q})",  # nosec B608
                chunk,
            ):
                out[h] = {"hash": h, "stars": stars or 0, "grade": grade or "", "note": note or ""}
    return out


def put(hash_, stars=None, grade=None, note=None):
    """Create or update a rating. Only the fields passed are changed, so setting
    stars from the map doesn't wipe a note written in the library view."""
    cur = get(hash_)
    stars = _clamp_stars(cur["stars"] if stars is None else stars)
    grade = (cur["grade"] if grade is None else str(grade)).strip().upper()[:4]
    note = (cur["note"] if note is None else str(note)).strip()[:MAX_NOTE]
    with _db_lock, closing(db()) as conn, conn as c:
        c.execute(
            "INSERT INTO ratings(hash, stars, grade, note, updated) VALUES(?,?,?,?,?) "
            "ON CONFLICT(hash) DO UPDATE SET stars=excluded.stars, grade=excluded.grade, "
            "note=excluded.note, updated=excluded.updated",
            (hash_, stars, grade, note, time.time()),
        )
    return {"hash": hash_, "stars": stars, "grade": grade, "note": note}


def comment_for(rating):
    """The Comments string Rekordbox should show: ``"A - some text"``.

    Either half may be missing -- a grade with no note is just ``"A"``, a note
    with no grade is the note alone -- so an empty field never leaves a dangling
    separator.
    """
    grade = (rating.get("grade") or "").strip()
    note = (rating.get("note") or "").strip()
    if grade and note:
        return f"{grade} - {note}"
    return grade or note


def _attr(value):
    """XML attribute value, quoted and escaped. quoteattr picks the quote style
    and escapes &, <, > and whichever quote it used."""
    return quoteattr("" if value is None else str(value))


def _location(filepath):
    """Rekordbox's ``Location``: a file:// URL with the host part present.

    Rekordbox is strict here -- it wants ``file://localhost/C:/path/x.mp3``, with
    forward slashes and percent-encoded specials. A plain Windows path silently
    imports as a missing file.
    """
    from urllib.parse import quote

    p = str(filepath or "").replace("\\", "/")
    if len(p) > 1 and p[1] == ":":
        p = "/" + p
    return "file://localhost" + quote(p, safe="/:")


def playlist_xml(name, tracks, ratings=None):
    """A Rekordbox-importable collection XML for one playlist.

    ``tracks`` is a sequence of dicts with at least ``hash``; ``title``,
    ``artist``, ``filepath``, ``bpm``, ``key`` and ``duration`` are used when
    present. ``ratings`` is the {hash: rating} map from :func:`get_many`.

    The document carries both a COLLECTION (the track rows, where ratings and
    comments live) and a PLAYLISTS tree referencing them by ``TrackID`` --
    Rekordbox needs both; a playlist node alone imports as empty.

    **Tracks with no stored filepath are skipped.** Rekordbox locates audio by
    path; a row without one imports as a permanently missing file, which is worse
    than an honest omission because it looks like a successful import. The count
    is recorded in an XML comment and returned by :func:`playlist_export` so the
    caller can say why a 50-track playlist produced 9 rows. Tracks analysed by
    drag-and-drop have no path -- re-scanning their folder backfills it.
    """
    ratings = ratings or {}
    rows, refs, skipped = [], [], []
    for t in tracks:
        if not str(t.get("filepath") or "").strip():
            skipped.append(t.get("title") or t.get("hash") or "?")
    exportable = [t for t in tracks if str(t.get("filepath") or "").strip()]
    for i, t in enumerate(exportable, start=1):
        r = ratings.get(t.get("hash")) or {}
        bits = [
            f"TrackID={_attr(i)}",
            f"Name={_attr(t.get('title') or '')}",
            f"Artist={_attr(t.get('artist') or '')}",
            f"Location={_attr(_location(t.get('filepath')))}",
            f"Rating={_attr(STARS_TO_RB.get(_clamp_stars(r.get('stars')), 0))}",
        ]
        comment = comment_for(r)
        if comment:
            bits.append(f"Comments={_attr(comment)}")
        if t.get("bpm"):
            bits.append(f"AverageBpm={_attr(round(float(t['bpm']), 2))}")
        if t.get("key"):
            bits.append(f"Tonality={_attr(t['key'])}")
        if t.get("duration"):
            bits.append(f"TotalTime={_attr(int(float(t['duration'])))}")
        rows.append("      <TRACK " + " ".join(bits) + "/>")
        refs.append(f"        <TRACK Key={_attr(i)}/>")

    skip_note = (
        f"\n  <!-- {len(skipped)} track(s) omitted: no stored file path, so Rekordbox "
        "could not locate them. Re-scan their folder to record the path. -->"
        if skipped
        else ""
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<DJ_PLAYLISTS Version="1.0.0">\n'
        '  <PRODUCT Name="Vibe Identify" Version="1.0" Company="Vibe"/>' + skip_note + "\n"
        f"  <COLLECTION Entries={_attr(len(rows))}>\n" + "\n".join(rows) + "\n  </COLLECTION>\n"
        "  <PLAYLISTS>\n"
        '    <NODE Type="0" Name="ROOT" Count="1">\n'
        f'      <NODE Name={_attr(name)} Type="1" KeyType="0" Entries={_attr(len(refs))}>\n'
        + "\n".join(refs)
        + "\n      </NODE>\n"
        "    </NODE>\n"
        "  </PLAYLISTS>\n"
        "</DJ_PLAYLISTS>\n"
    )
