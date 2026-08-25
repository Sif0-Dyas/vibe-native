"""A lexicon of electronic genres, for names the classifier cannot emit.

The model knows 400 Discogs styles. You type more than that -- ``riddim``,
``neurofunk``, ``amapiano``, ``colour bass`` -- and every one that the taxonomy
doesn't recognise falls into the non-electronic *Other* family, which is the
worst possible answer for an electronic library.

This reads the crawl produced by ``tools/crawl_genres.py`` (on the
``worktree-genre-crawler`` branch): 610 electronic genres assembled from
Wikidata (CC0), DBpedia and Wikipedia (CC BY-SA) and MusicBrainz (CC0). Unlike
the Every Noise snapshot it superseded, those sources are properly licensed and
the file carries its own attribution block.

**What it's actually used for.** Not the descriptions -- only 70 of 610 run past
60 characters, and most are Wikidata stubs like "music genre", which is no
improvement on a hand-written line. The value is structural:

* ``parents`` -- a real hierarchy. ``riddim -> dubstep``, ``neurofunk -> drum and
  bass``, ``amapiano -> house music``. Walking it resolves 167 genres the tables
  miss, taking coverage from 269/610 to 436/610.
* ``aliases`` -- 1,137 alternate spellings, so ``hard wave`` finds ``hardwave``.
* ``excerpt`` -- 196 genres do carry real prose, worth showing when present.

Optional: if the crawl hasn't been run the module degrades to empty and every
lookup returns None, exactly like the Every Noise snapshot before it.
"""

import json
import threading
from pathlib import Path

from .config import log

DATA = Path(__file__).resolve().parent / "data" / "genres_electronic.json"

# How far to walk up the parent chain before giving up. The hierarchy is shallow
# in practice; a cap also stops a cycle in the source data from hanging a lookup.
MAX_DEPTH = 5

_lock = threading.Lock()
_index = None  # name/alias (lowercased) -> entry


def _norm(name):
    return str(name or "").strip().lower()


def _load():
    global _index
    with _lock:
        if _index is not None:
            return _index
        try:
            raw = json.loads(DATA.read_text(encoding="utf-8"))
        except FileNotFoundError:
            _index = {}
            return _index
        except (OSError, ValueError) as e:
            log.warning("genrelex: unusable crawl at %s (%s); lexicon disabled", DATA, e)
            _index = {}
            return _index
        idx = {}
        for g in raw.get("genres") or []:
            name = _norm(g.get("name"))
            if not name:
                continue
            idx.setdefault(name, g)
            # Aliases only fill gaps -- a real genre name must never be shadowed
            # by another genre's alias for the same string.
            for a in g.get("aliases") or []:
                idx.setdefault(_norm(a), g)
        _index = idx
        log.info("genrelex: %d genre names loaded (incl. aliases)", len(idx))
        return _index


def get(name):
    """The lexicon entry for a genre name or alias, or None."""
    return _load().get(_norm(name))


def describe(name):
    """The best available prose for a genre: the wiki excerpt if there is one,
    else the short description, else None.

    Wikidata descriptions are frequently just "music genre" -- worse than saying
    nothing, because it looks like information. Those are filtered out.
    """
    g = get(name)
    if not g:
        return None
    exc = (g.get("excerpt") or "").strip()
    if exc:
        return exc
    desc = (g.get("description") or "").strip()
    generic = {"music genre", "electronic music genre", "genre of music", "musical genre"}
    return desc if desc and desc.lower() not in generic else None


def resolve_keystone(name, keystone_of):
    """Map a genre name onto a keystone by walking its parents.

    ``keystone_of`` is passed in rather than imported so this module stays a
    pure lexicon and the taxonomy keeps one owner -- and so the caller can't
    accidentally create an import cycle between the two.

    Breadth-first, because a genre with several parents ("hardwave" is both wave
    and bass music) should take the shortest route to a keystone rather than
    whichever branch happens to be first.
    """
    idx = _load()
    if not idx:
        return None
    start = idx.get(_norm(name))
    if not start:
        return None

    # Try the canonical name through the caller's own tables before walking
    # parents. An alias must inherit whatever its real name resolves to: "hard
    # wave" is an alias of "hardwave", which is curated as Hard Dance, but
    # walking hardwave's parents finds "wave" first and lands in Downtempo. A
    # curated answer for the same genre has to win over an inferred one.
    canonical = start.get("name")
    if canonical and _norm(canonical) != _norm(name):
        hit = keystone_of(canonical)
        if hit:
            return hit

    seen, frontier = {_norm(name), _norm(canonical)}, [start]
    for _ in range(MAX_DEPTH):
        nxt = []
        for g in frontier:
            for p in g.get("parents") or []:
                pn = _norm(p)
                if pn in seen:
                    continue
                seen.add(pn)
                hit = keystone_of(p)
                if hit:
                    return hit
                pg = idx.get(pn)
                if pg:
                    nxt.append(pg)
        if not nxt:
            break
        frontier = nxt
    return None


def names():
    """Every known genre name (not aliases), sorted -- for autocomplete."""
    seen = {}
    for entry in _load().values():
        n = entry.get("name")
        if n:
            seen[n] = True
    return sorted(seen)


def stats():
    idx = _load()
    entries = {id(v): v for v in idx.values()}
    return {
        "available": bool(idx),
        "genres": len(entries),
        "names_incl_aliases": len(idx),
        "with_prose": sum(1 for v in entries.values() if (v.get("excerpt") or "").strip()),
    }
