"""User edits to the genre taxonomy, kept in a JSON file outside the database.

The built-in tables in ``keystone.py`` are a good default and a bad final
answer: they were written against one library, and the person using the app
knows things they don't -- that Halftime belongs under Drum n Bass rather than
standing alone, that a name you type constantly should resolve somewhere
specific. This is where those corrections live.

**Why a file and not the database.** The database is disposable. It gets nuked
and rebuilt from a re-scan whenever the library moves or the analysis changes,
and a taxonomy that died with it would have to be re-entered every time. This
file sits next to ``settings.ini``, survives every re-scan, copies to another
machine, and diffs in version control if you want it to.

**Why an overlay and not a copy.** It stores only your *departures* from the
built-in tables -- ``{"archgenre": {"Halftime": "Drum n Bass"}}``, not the whole
table with one line changed. A full copy would freeze the defaults at whatever
they were the day it was written: every later fix to the shipped tables would be
silently shadowed by a stale duplicate, and there would be no way to tell an
edit you meant from a default you inherited. Sparse means your edits persist and
everything you haven't touched keeps tracking the code.

Hand-editing is expected, so the file is re-read whenever it changes on disk and
a broken one degrades to "no overlay" rather than taking the app down with it.
"""

import json
import os
import threading
from pathlib import Path

from .config import log
from .paths import settings_ini

VERSION = 1

# The keys an overlay may carry. Anything else in the file is ignored rather
# than rejected -- a newer build's key must not make the file unloadable by an
# older one, and vice versa.
_MAPS = ("aliases", "archgenre", "family", "colors")
_LISTS = ("hidden", "order")
# Scalars. "" means "no choice made", which is how a preset returns to the
# default without the file having to carry a line saying so.
_SCALARS = ("palette",)

_lock = threading.Lock()
_cache = None  # the parsed overlay
_stamp = None  # (mtime, size) of the file it came from


def path():
    """The overlay file, beside settings.ini so the two travel together.

    ``VIBE_TAXONOMY`` overrides it, matching how ``GENRE_DB`` works. The test
    suite needs that: this file changes how every genre resolves, so a suite
    that read the developer's real overlay would pass or fail depending on
    whose machine it ran on.
    """
    env = os.environ.get("VIBE_TAXONOMY")
    if env:
        return Path(env)
    return settings_ini().with_name("taxonomy.json")


def _blank():
    return {k: {} for k in _MAPS} | {k: [] for k in _LISTS} | {k: "" for k in _SCALARS}


def _clean(raw):
    """Coerce a parsed file into the overlay shape, dropping what doesn't fit.

    Deliberately forgiving: this file is meant to be hand-edited, so one bad
    line should cost that line and nothing else. Values are not checked against
    the known keystones -- naming a genre the tables have never heard of is a
    legitimate thing to want, and refusing it would make the file useless for
    exactly the case it exists to serve.
    """
    out = _blank()
    if not isinstance(raw, dict):
        return out
    for key in _MAPS:
        for k, v in (raw.get(key) or {}).items():
            k, v = str(k).strip(), str(v).strip()
            # An empty value is meaningful for archgenre ("this one stands
            # alone") but is just noise everywhere else.
            if k and (v or key == "archgenre"):
                out[key][k] = v
    for key in _LISTS:
        seen = set()
        for v in raw.get(key) or []:
            v = str(v).strip()
            if v and v not in seen:
                seen.add(v)
                out[key].append(v)
    for key in _SCALARS:
        v = raw.get(key)
        out[key] = str(v).strip() if isinstance(v, (str, int, float)) else ""
    # Aliases resolve case-insensitively, matching keystone._USER_ALIASES.
    out["aliases"] = {k.lower(): v for k, v in out["aliases"].items()}
    return out


def load(force=False):
    """The current overlay, re-read when the file has changed on disk.

    Cheap enough to call per lookup: the common path is one ``stat`` against a
    cached result. Re-reading on change is what makes hand-editing work -- you
    save the file and the app follows, without a restart.
    """
    global _cache, _stamp
    p = path()
    try:
        st = p.stat()
        stamp = (st.st_mtime_ns, st.st_size)
    except OSError:
        stamp = None
    with _lock:
        if not force and _cache is not None and stamp == _stamp:
            return _cache
        if stamp is None:
            _cache, _stamp = _blank(), None
            return _cache
        try:
            _cache = _clean(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            # A typo in a hand-edited file must not take the app down. Fall back
            # to the built-in tables and say so.
            log.warning("taxonomy: unusable overlay at %s (%s); using defaults", p, e)
            _cache = _blank()
        _stamp = stamp
        return _cache


def save(overlay):
    """Write the overlay, dropping empty sections so the file stays readable.

    Keys are sorted: the file is meant to be diffable, and a dict that reorders
    itself between writes makes every diff noise.
    """
    global _cache, _stamp
    clean = _clean(overlay)
    body = {"version": VERSION}
    for k in _MAPS:
        if clean[k]:
            body[k] = dict(sorted(clean[k].items()))
    for k in _LISTS:
        if clean[k]:
            body[k] = clean[k]
    for k in _SCALARS:
        if clean[k]:
            body[k] = clean[k]
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    # Write-then-replace: a crash mid-write leaves the previous overlay intact
    # rather than a truncated file that won't parse.
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(p)
    with _lock:
        _cache = clean
        try:
            st = p.stat()
            _stamp = (st.st_mtime_ns, st.st_size)
        except OSError:
            _stamp = None
    return clean


def patch(changes):
    """Merge ``changes`` into the overlay and save.

    A map value of ``None`` removes that entry -- the way to say "go back to the
    built-in default", which is different from "override it with nothing" and
    needs to be expressible. Lists are replaced wholesale, since there is no
    sensible partial edit of an ordering.
    """
    cur = {k: dict(v) for k, v in load().items() if isinstance(v, dict)}
    cur |= {k: list(v) for k, v in load().items() if isinstance(v, list)}
    cur |= {k: load()[k] for k in _SCALARS}
    for key in _MAPS:
        for k, v in (changes.get(key) or {}).items():
            k = str(k).strip()
            if not k:
                continue
            if v is None:
                cur[key].pop(k.lower() if key == "aliases" else k, None)
            else:
                cur[key][k.lower() if key == "aliases" else k] = str(v).strip()
    for key in _LISTS:
        if key in changes:
            cur[key] = changes.get(key) or []
    for key in _SCALARS:
        if key in changes:
            cur[key] = "" if changes[key] is None else str(changes[key]).strip()
    return save(cur)


def reset():
    """Drop every user edit, returning the taxonomy to the built-in tables.

    The file is renamed rather than deleted, so a reset triggered by a mis-click
    is recoverable -- the same stance ``snapshots.reset`` takes.
    """
    global _cache, _stamp
    p = path()
    moved = None
    if p.exists():
        moved = p.with_suffix(".json.bak")
        p.replace(moved)
    with _lock:
        _cache, _stamp = _blank(), None
    return {"reset": True, "backup": str(moved) if moved else None}


# --- lookups, used by keystone.py and palette.py ------------------------------
def alias_of(style):
    """The keystone a user-named style resolves to, or None."""
    return load()["aliases"].get(str(style or "").strip().lower()) or None


def archgenre_override(keystone):
    """The user's archgenre for a keystone, or None if they haven't said.

    An empty string is a real answer meaning "this stands on its own", so this
    returns ``""`` for that and ``None`` for "no opinion" -- callers have to
    tell those apart or a keystone could never be promoted to standalone.
    """
    return load()["archgenre"].get(keystone)


def family_override(keystone):
    return load()["family"].get(keystone) or None


def color_override(keystone):
    return load()["colors"].get(keystone) or None


def hidden():
    return set(load()["hidden"])


def order():
    return list(load()["order"])
