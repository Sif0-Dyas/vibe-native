"""Export the library's genre labels as a CSV: hash, filepath, genre, source.

The labels a genre head could be trained on, or an engine benchmarked against,
from four sources -- one row per (track, source), so a track with an override
and a tag appears twice and the sources can be compared:

* ``override`` -- ``payload["override"]``: "it IS this", set in the app.
* ``weight``   -- the top of the hand-adjusted blend (``payload["weights"]`` /
  ``["drops"]``, vibenative.weights), for tracks that have adjustments.
* ``id3-genre`` -- the file's own genre tag, as metadata.read_tags read it at
  analysis time (stored in ``payload["tags"]``; ``--probe`` re-reads the files).
* ``manual``   -- a blind label from the /label page (``genre_labels``, v12).

Overrides and weights are chosen looking at the model's read, so they are
anchored to it; only ``manual`` is blind. A benchmark should score against
``manual`` and use the others for training at most.

Every genre goes through one normaliser, so the four sources share a spelling:
the classifier's style name when the name is one of its 400 -- case and
``&``/``and``/``'n'`` folded, a parenthesised qualifier or one half of an
``A / B`` allowed, or reached through one of the lexicon's 1,137 aliases
("drum & bass" -> "drum and bass" -> Drum n Bass) -- else the name as written
(first spelling seen, case-insensitively). It respells; it does not collapse a
genre into its keystone: "Trap Wave" (10 overrides) and "Phonk" are genres the
model has no label for, which is why someone typed them, and a head trained on
these labels needs them kept. The keystone each genre belongs to (overlay ->
built-in tables -> lexicon, taxonomy/README.md) is in the report instead.

A tag holding several genres ("Trance; Electronic") keeps the one specific genre
in it; a tag naming several (a store's whole genre menu pasted into one field)
is skipped as ambiguous, and one naming only a shelf ("Electronic", "Dance") as
carrying no genre.

Reads the database read-only and never migrates it. Point it at a copy:

    python tools/export_labels.py C:/tmp/genre_v2_copy.db --out labels.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vibenative.style import identity  # noqa: E402
from vibenative.taxonomy import lexicon  # noqa: E402
from vibenative.taxonomy.classify import discogs_labels, keystone_of  # noqa: E402

SOURCES = ("override", "weight", "id3-genre", "manual")
FIELDS = ("hash", "filepath", "genre", "source")

# Tag values that name a shelf, not a genre. Compared on ASCII letters only, so
# "Électronique" and its mojibake "\ufffdlectronique" (a Latin-1 tag read as
# UTF-8) both match.
UMBRELLAS = {
    "electronic",
    "electronicmusic",
    "electronique",
    "lectronique",
    "elektronisch",
    "electronica",
    "electronico",
    "electronicdance",
    "dance",
    "edm",
    "club",
    "other",
    "unknown",
    "misc",
    "various",
    "genre",
    "music",
}

_SPLIT = re.compile(r"\s*[;,|\x00]\s*")
_PAREN = re.compile(r"\s*\([^)]*\)\s*")


def _key(s: str) -> str:
    return " ".join(str(s).split()).casefold()


def _fold(key: str) -> str:
    """``&`` / ``and`` / ``'n'`` as `` n ``, and hyphens as spaces: the model
    writes "Drum n Bass" and "Psy-Trance", tags write "Drum & Bass", "Hip-Hop"
    and "Tech-Trance"."""
    key = re.sub(r"\s*(?:&|\band\b|'n'|\bn'|'n\b)\s*", " n ", key.replace("-", " "))
    return " ".join(key.split())


def _spellings(key: str):
    yield key
    if _fold(key) != key:
        yield _fold(key)


class Normaliser:
    """Maps a genre name onto the export's vocabulary (see the module docstring)."""

    def __init__(self, labels=None):
        if labels is None:
            try:
                labels = discogs_labels()
            except FileNotFoundError:
                labels = []
        self.styles, self.parents = {}, {}
        for lab in labels:
            parent, _, style = lab.rpartition("---")
            for table, name in ((self.styles, style), (self.parents, parent)):
                if name:
                    table.setdefault(_key(name), name)
                    table.setdefault(_fold(_key(name)), name)
        self.spelling = {}  # casefolded name -> the first spelling seen

    def _style(self, name):
        """The model style ``name`` spells, directly or through a lexicon alias."""
        for k in _spellings(_key(name)):
            if k in self.styles:
                return self.styles[k]
        entry = lexicon.get(name)
        if entry and entry.get("name"):
            for k in _spellings(_key(entry["name"])):
                if k in self.styles:
                    return self.styles[k]
        return None

    def one(self, name: str):
        """(genre, kind) for one genre name. kind is "style" (one of the model's
        400), "parent" (one of their parent genres: Pop, Rock, Hip Hop...) or
        "other" (kept as written); (None, "umbrella") for a shelf name, (None,
        None) if empty or a bare number (an ID3v1 genre code, or a year)."""
        raw = " ".join(str(name or "").split())
        if not raw or re.fullmatch(r"\(?\d+\)?", raw):
            return None, None
        if re.sub(r"[^a-z]", "", raw.casefold()) in UMBRELLAS:
            return None, "umbrella"
        tries = [raw]
        bare = _PAREN.sub(" ", raw).strip()
        if bare and bare != raw:
            tries.append(bare)  # "Techno (Peak Time / Driving)" -> "Techno"
        tries += [part.strip() for t in tries if "/" in t for part in t.split("/")]
        for t in tries:  # "Rap/Hip Hop", "Minimal / Deep Tech": a half that is a style
            hit = t and self._style(t)
            if hit:
                return hit, "style"
        for t in tries:
            for k in _spellings(_key(t)):
                if k in self.parents:
                    return self.parents[k], "parent"
        return self.spelling.setdefault(_key(raw), raw), "other"

    def tag(self, value: str):
        """(genre, kind) for a whole tag value, which may hold several genres.
        kind as for ``one``, plus "ambiguous" (several specific genres)."""
        # Split first, so "House, Deep House, Tech House, ..." -- a store's whole
        # genre menu in one field -- is seen as the several genres it names.
        parts = [s for s in _SPLIT.split(str(value)) if s.strip()]
        if len(parts) <= 1:
            return self.one(value)
        found, umbrella = {}, False
        for part in parts:
            g, k = self.one(part)
            if g:
                found.setdefault(g, k)
            elif k == "umbrella":
                umbrella = True
        if len(found) > 1:
            return None, "ambiguous"
        if found:
            return next(iter(found.items()))
        return (None, "umbrella") if umbrella else (None, None)


def _payload(text):
    try:
        p = json.loads(text) if isinstance(text, str) else None
    except ValueError:
        return None
    return p if isinstance(p, dict) else None


def _weighted_top(p):
    """The top of the hand-adjusted blend, or None without adjustments. The
    override is set aside first: it sits above the adjustments in the identity
    chain but does not remove them."""
    q = dict(p)
    q.pop("override", None)
    ident = identity(q)
    return ident["style"] if ident["source"] == "weights" else None


def _stored_genre_tag(p):
    return (((p.get("tags") or {}).get("tag")) or {}).get("genre")


def _probed_genre_tag(filepath):
    from vibenative.metadata import read_tags

    if not filepath or not Path(filepath).is_file():
        return None
    return read_tags(Path(filepath))["tag"].get("genre")


def collect(db_path, probe=False, norm=None):
    """(rows, stats): the CSV rows and what the report prints."""
    norm = norm or Normaliser()
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        tracks = conn.execute("SELECT hash, filepath, payload FROM tracks").fetchall()
        manual = (
            conn.execute("SELECT hash, genre FROM genre_labels").fetchall()
            if "genre_labels" in tables
            else []
        )
    finally:
        conn.close()

    rows = []
    kinds = {s: Counter() for s in SOURCES}
    changed = Counter()  # non-tag labels the normaliser respelled
    tag_raw, tag_genres, tag_kind = set(), Counter(), {}
    filepaths = {}
    for h, filepath, text in tracks:
        filepaths[h] = filepath or ""
        p = _payload(text)
        if p is None:
            continue
        for source, value in (("override", p.get("override")), ("weight", _weighted_top(p))):
            if value:
                g, kind = norm.one(value)
                if g:
                    rows.append((h, filepath or "", g, source))
                    kinds[source][kind] += 1
                    changed[source] += g != value
        tag = _probed_genre_tag(filepath) if probe else _stored_genre_tag(p)
        if tag:
            tag_raw.add(tag)
            g, kind = norm.tag(tag)
            kinds["id3-genre"][kind or "empty"] += 1
            if g:
                rows.append((h, filepath or "", g, "id3-genre"))
                tag_genres[g] += 1
                tag_kind[g] = kind
    for h, value in manual:
        if h not in filepaths:
            continue  # an orphan row; forget_track clears genre_labels too
        g, kind = norm.one(value)
        if g:
            rows.append((h, filepaths[h], g, "manual"))
            kinds["manual"][kind] += 1
            changed["manual"] += g != value

    stats = {
        "tracks": len(tracks),
        "rows": Counter(r[3] for r in rows),
        "tracks_labelled": len({r[0] for r in rows}),
        "kinds": kinds,
        "respelled": changed,
        "tag_values": len(tag_raw),
        "tag_genres": tag_genres,
        "tag_genre_kinds": Counter(tag_kind.values()),
        "tag_keystones": Counter(keystone_of(g) for g in tag_genres),
        "genres": len({r[2] for r in rows}),
    }
    return rows, stats


def write_csv(rows, out):
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        w.writerows(sorted(rows, key=lambda r: (SOURCES.index(r[3]), r[0])))


def report(stats, top=15):
    out = [f"{stats['tracks']} tracks; {stats['tracks_labelled']} have at least one label", ""]
    out.append("rows per source:")
    for s in SOURCES:
        k = stats["kinds"][s]
        detail = ", ".join(f"{n} {kind}" for kind, n in sorted(k.items()))
        out.append(f"  {s:<10} {stats['rows'][s]:>6}   ({detail or 'none'})")
    resp = {s: n for s, n in stats["respelled"].items() if n}
    if resp:
        out.append(f"  respelled by the normaliser: {resp}")
    tg = stats["tag_genres"]
    kinds = stats["tag_genre_kinds"]
    keystones = stats["tag_keystones"]
    no_keystone = keystones.pop(None, 0)
    out += [
        f"  {stats['genres']} distinct genres across all sources",
        "",
        f"id3 genre tags: {stats['tag_values']} distinct values -> {len(tg)} distinct genres "
        f"after normalisation ({kinds['style']} of the model's styles, {kinds['parent']} of their "
        f"parent genres, {kinds['other']} other)",
        f"  they fall in {len(keystones)} keystones; {no_keystone} genres resolve to none",
        f"  keystones: {', '.join(sorted(keystones))}",
        f"  most common: {', '.join(f'{g} {n}' for g, n in tg.most_common(top))}",
    ]
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("db", help="the library database -- a copy; it is opened read-only")
    ap.add_argument("--out", default="labels.csv", help="CSV to write (default labels.csv)")
    ap.add_argument(
        "--probe",
        action="store_true",
        help="re-read each file's genre tag with ffprobe instead of the stored copy",
    )
    args = ap.parse_args(argv)
    # Genre names are not all cp1252 -- the Windows console's default.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows, stats = collect(args.db, probe=args.probe)
    write_csv(rows, args.out)
    print(report(stats))
    print(f"\nwrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
