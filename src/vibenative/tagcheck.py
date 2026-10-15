"""The file's own genre tag, set against the genre the app shows.

The cheapest misread detector there is: whoever tagged the file said what it
was. When that tag and the shown genre fall in different keystones (Trance vs
House, not Tech House vs Deep House), one of them is wrong -- often the read.
"Known You Before (Original Mix)", tagged Trance and read House 72% /
Jungle 28%, is the case this exists for.

Imports nothing from ``routes`` -- this is domain logic, not HTTP.
"""

import random
import re
from collections import defaultdict

from .taxonomy import lexicon
from .taxonomy.classify import keystone_of
from .weights import base_read

# A tag can hold several genres ("Trance; Electronic"); these separate them.
_SPLIT = re.compile(r"\s*[;,|/\x00]\s*")

# Genre names that are a keystone when a person picks them but not when a file's
# tag carries them. A bare "Electro" tag is what stores print for electro house,
# big room and their whole electronic shelf alike: on the local library 190 of
# the 674 flagged tracks were tagged plain "Electro", most from a folder of
# Latin tech house. As a tag it drops out like "Electronic", so it is neither
# flagged nor exported as a label. An override or a blind label of "Electro" is
# someone's judgement and keeps its meaning. Compared on ASCII letters only.
VAGUE_TAGS = {"electro"}

# /label's contested-first order interleaves this many of the largest
# tag-vs-model boundaries before the rest (see ``contested_order``).
CONTESTED_BOUNDARIES = 3


def vague_tag(part) -> bool:
    """True for one tag value (or one part of a multi-genre tag) in VAGUE_TAGS."""
    return re.sub(r"[^a-z]", "", str(part or "").casefold()) in VAGUE_TAGS


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
    ("Electronic", "Dance") or only a vague one (VAGUE_TAGS) drop out -- and
    names none if those disagree."""
    parts = [p for p in _SPLIT.split(str(tag or "")) if p.strip() and not vague_tag(p)]
    found = {keystone_for(part) for part in parts}
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


def contested_order(rows, rng=random):
    """The hashes of tracks whose file tag and the model's own read (``base_read``:
    no override, no hand adjustment) name different keystones, in the order
    /label's contested-first option offers them. ``rows`` is (hash, payload).

    Grouped by boundary -- the unordered keystone pair, so a Tech House tag read
    as Techno and a Techno tag read as House are one question -- largest first.
    The CONTESTED_BOUNDARIES largest are interleaved, a track from each in turn,
    so a couple of hundred labels cover each of them rather than only the
    biggest; then the rest, interleaved the same way. Shuffled within a
    boundary, so the labels sample it rather than follow library order."""
    groups = defaultdict(list)
    for h, payload in rows:
        read = base_read(payload or {})
        top = read[0].get("style") if read else None
        tag = file_tag_fields(payload, top).get("file_tag")
        if tag and tag["agrees"] is False:
            groups[frozenset((tag["keystone"], keystone_for(top)))].append(h)
    ranked = sorted(groups.values(), key=len, reverse=True)
    for hashes in ranked:
        hashes.sort()  # from a fixed start, so only ``rng`` decides the order
        rng.shuffle(hashes)
    out = []
    for batch in (ranked[:CONTESTED_BOUNDARIES], ranked[CONTESTED_BOUNDARIES:]):
        for i in range(max(map(len, batch), default=0)):
            out += [hashes[i] for hashes in batch if i < len(hashes)]
    return out
