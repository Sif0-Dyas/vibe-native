"""The file's own genre tag, set against the genre the app shows.

The cheapest misread detector there is: whoever tagged the file said what it
was. When that tag and the shown genre fall in different keystones (Trance vs
House, not Tech House vs Deep House), one of them is wrong -- often the read.
"Known You Before (Original Mix)", tagged Trance and read House 72% /
Jungle 28%, is the case this exists for.

Imports nothing from ``routes`` -- this is domain logic, not HTTP.
"""

import re

from .taxonomy import lexicon
from .taxonomy.classify import keystone_of

# A tag can hold several genres ("Trance; Electronic"); these separate them.
_SPLIT = re.compile(r"\s*[;,|/\x00]\s*")


def _fold(name: str) -> str:
    """Fold "Drum & Bass" / "Drum and Bass" into "Drum n Bass", the taxonomy's spelling."""
    return " ".join(re.sub(r"\s*(?:&|\band\b|'n'|\bn'|'n\b)\s*", " n ", name).split())


def keystone_for(name):
    """The keystone a genre name belongs to, or None: the taxonomy's own tables,
    then the lexicon's aliases and parents, as written and with "&"/"and" folded."""
    name = " ".join(str(name or "").split())
    if not name:
        return None
    for cand in dict.fromkeys((name, _fold(name))):
        hit = keystone_of(cand) or lexicon.resolve_keystone(cand, keystone_of)
        if hit:
            return hit
        entry = lexicon.get(cand)
        canonical = entry and entry.get("name")
        if canonical:
            hit = keystone_of(_fold(canonical))
            if hit:
                return hit
    return None


def tag_keystone(tag):
    """The keystone a whole tag value names, or None. A tag naming several genres
    keeps the one it is specific about -- the parts that carry no keystone
    ("Electronic", "Dance") drop out -- and names none if those disagree."""
    found = {keystone_for(part) for part in _SPLIT.split(str(tag or "")) if part.strip()}
    found.discard(None)
    return found.pop() if len(found) == 1 else None


def file_tag_fields(payload, shown_style):
    """``{"file_tag": {"text", "keystone", "agrees"}}`` for a track whose file
    carries a genre tag, else {}. ``agrees`` is whether the tag's keystone is the
    shown style's: True, False, or None when either has no keystone to compare."""
    tag = (((payload or {}).get("tags") or {}).get("tag") or {}).get("genre")
    text = " ".join(str(tag or "").split())
    if not text:
        return {}
    ks = tag_keystone(text)
    shown = keystone_for(shown_style)
    agrees = None if not (ks and shown) else ks == shown
    return {"file_tag": {"text": text, "keystone": ks, "agrees": agrees}}
