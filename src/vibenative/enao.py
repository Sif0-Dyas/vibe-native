"""Every Noise at Once genre reference: canonical colours + a 2-D genre space.

Loads the snapshot built by ``tools/build_enao.py`` and joins it to the
Discogs-400 style labels the classifier emits. Gives two things the model's own
label set can't:

* a **canonical colour** per genre -- on Every Noise a genre's colour *is* its
  map position encoded as RGB, so genres that look alike really are alike, and
* **coordinates** on that map, whose two axes have meanings you can name.

The axis orientation below was measured against this snapshot, not assumed --
electronic genres (techno, house, gabber) average y≈2200 while acoustic ones
(opera, string quartet, bebop) average y≈19000, and ambient/drone average x≈284
against ska/funk/disco at x≈914:

* **y** -- low = mechanical/electric, high = organic/acoustic. This is the
  dominant axis; the map is 22,648px tall and only 1,500 wide.
* **x** -- low = denser/more atmospheric, high = spikier/bouncier.

Purely local: reads one JSON file, never the network. If that file is absent
(it's git-ignored, like ``models/``) every lookup returns ``None`` and callers
fall back to their existing behaviour -- the app runs fine without it.

Joining the two vocabularies takes three passes, cheapest first:

1. exact match on the normalised style name,
2. spelling variants -- accents folded and hyphen/space/joined forms tried, which
   is what bridges ``Synth-pop``/``synthpop``, ``Norteño``/``norteno``,
   ``Rock & Roll``/``rock-and-roll``, ``Power Violence``/``powerviolence``,
3. a curated alias table for pairs no string rule can reach (``Bollywood`` ->
   ``filmi``, ``Fusion`` -> ``jazz fusion``).

Deliberately *not* here, both tried and rejected on measurement:

* **Prefix guessing** ("the most popular Every Noise genre starting with this
  word") picked ``military rap`` for ``Military``, ``acid rock`` for
  ``Electronic---Acid`` and ``vocal jazz`` for ``Pop---Vocal`` -- wrong about
  40% of the time, because it discards the parent half of the Discogs label.
  An unmapped style is better than a confidently wrong one.
* **Nearest-genre search over the coordinates.** Every Noise publishes a
  "related genres" list per genre, and it's tempting to reproduce it by finding
  the closest x/y. It does not work: among shoegaze's 6,290 map neighbours,
  ``dream pop`` ranks 525th, ``noise pop`` 1091st and ``slowcore`` 3977th, and
  the actual top hits are ``russian screamo`` and ``polish folk metal``.
  Normalising the axes helps only marginally (dream pop to 211th). The real
  lists come from Spotify's underlying vector space; the 2-D map is a lossy
  projection of it, fine for *placing* a genre but not for ranking similarity.
  Use the track embeddings already in the database for that instead.
"""

import json
import re
import threading
import unicodedata
from pathlib import Path

from .config import log

DATA = Path(__file__).resolve().parent / "data" / "enao.json"

# Curated Discogs style -> Every Noise genre, for pairs the string rules in
# _variants() can't bridge. Every target here was checked against the snapshot:
# a guessed-but-absent target silently disables its alias, which is why
# test_enao.py asserts the whole table still resolves. Verify before adding.
ALIASES = {
    # spelling/naming differences no rule catches
    "avantgarde": "avant-garde",
    "bossanova": "bossa nova",
    "drum n bass": "drum and bass",
    "darkwave": "dark wave",
    "italodance": "italo dance",
    "jazzy hip-hop": "jazz rap",
    "psy-trance": "psychedelic trance",
    "prog rock": "progressive rock",
    "post bop": "hard bop",
    "bop": "bebop",
    "cha-cha": "cha-cha-cha",
    # Discogs uses a bare word where Every Noise qualifies it. These are the
    # ones where the parent genre makes the intent unambiguous.
    "acid": "acid house",
    "bleep": "bleep techno",
    "crust": "crust punk",
    "bubblegum": "bubblegum pop",
    "conscious": "conscious hip hop",
    "acoustic": "acoustic pop",
    "ethereal": "ethereal wave",
    "funeral doom metal": "funeral doom",
    "glam": "glam rock",
    "goth rock": "gothic rock",
    "heavy metal": "metal",  # Every Noise has no bare "heavy metal"
    "mod": "mod revival",
    "surf": "surf music",
    "thrash": "thrash metal",
    "minimal": "minimal techno",
    "tribal": "tribal house",
    "halftime": "halftime dnb",
    "nu-disco": "nu disco",
    "italo-disco": "italo disco",
    "future jazz": "nu jazz",
    "ghetto": "ghettotech",
    "ghetto house": "ghettotech",
    "euro house": "eurodance",
    "euro-disco": "eurodance",
    "idm": "intelligent dance music",
    "fusion": "jazz fusion",
    "free funk": "free jazz",
    "p.funk": "funk",
    "psychedelic": "psychedelic rock",
    "space-age": "space age pop",
    "instrumental": "instrumental hip hop",  # Discogs scopes this under Hip Hop
    "gangsta": "gangster rap",
    "thug rap": "hardcore hip hop",
    "screw": "chopped and screwed",
    "ragga": "ragga jungle",
    "ragga hiphop": "ragga jungle",
    "reggae-pop": "reggae fusion",
    "swingbeat": "new jack swing",
    "rnb swing": "new jack swing",  # "RnB/Swing" -- the slash becomes a space
    "arena rock": "album rock",
    "aor": "album rock",
    "modern electric blues": "electric blues",
    "berlin-school": "berlin school",
    # classical
    "romantic": "late romantic era",
    "neo-romantic": "post-romantic era",
    "modern": "neo-classical",
    "modern classical": "neo-classical",
    # latin / world
    "afro-cuban": "cuban rumba",
    "afro-cuban jazz": "latin jazz",
    "guaguanco": "cuban rumba",
    "guajira": "cuban rumba",
    "descarga": "cuban rumba",
    "cubano": "cuban rumba",
    "son": "son cubano",
    "son montuno": "son cubano",
    "pachanga": "charanga",
    "baiao": "forro",
    "batucada": "samba",
    "beguine": "zouk",
    "compas": "kompa",
    "bollywood": "filmi",
    "hindustani": "hindustani classical",
    "catalan music": "musica catalana",
    "pacific": "pacific islands pop",
    "african": "afropop",
    "romani": "gypsy jazz",
    "hillbilly": "old-time",
    "beat": "merseybeat",
    "juke": "footwork",
    # stage & screen
    "musical": "show tunes",
    "score": "soundtrack",
}

# Discogs' Non-Music parent (and a few production-tool styles) describe spoken
# word and utility audio, not genres. Every Noise has no counterpart and
# shouldn't be forced to invent one -- these stay unmapped on purpose, so
# coverage numbers aren't chasing an unreachable 100%.
NON_MUSIC = frozenset(
    {
        "audiobook",
        "dialogue",
        "education",
        "educational",
        "interview",
        "monolog",
        "promotional",
        "radioplay",
        "religious",
        "political",
        "marches",
        "military",
        "nursery rhymes",
        "story",
        "speech",
        "dj battle tool",
        "cut-up dj",
        "field recording",
    }
)

_lock = threading.Lock()
_index = None  # name -> record, or {} when the snapshot is missing


def _base(style):
    """Fold a Discogs label to its comparison form.

    Discogs writes ``Electronic---Deep House``; Every Noise writes ``deep
    house``. Only the style (the part after ``---``) is compared -- the parent
    is context, not part of the name.
    """
    s = (style or "").split("---")[-1].strip().lower()
    s = s.replace("/", " ")
    return re.sub(r"\s+", " ", s).strip()


def _defold(s):
    """Strip diacritics: ``norteño`` -> ``norteno``, ``laïkó`` -> ``laiko``."""
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _variants(style):
    """Every spelling of a style worth trying, most likely first.

    Covers the two axes that actually differ between the vocabularies: accents,
    and how a compound is joined (``synth-pop`` / ``synth pop`` / ``synthpop``).
    Ampersands are tried both literally and spelled out, because Every Noise
    keeps them in ``contemporary r&b`` but spells them in ``rock-and-roll``.
    """
    seen = []
    for b in dict.fromkeys([_base(style), _defold(_base(style))]):
        for amp in dict.fromkeys([b, b.replace("&", "and")]):
            for v in (
                amp,
                amp.replace("-", " "),
                amp.replace("-", ""),
                amp.replace(" ", "-"),
                amp.replace(" ", ""),
            ):
                if v and v not in seen:
                    seen.append(v)
    return seen


def _load():
    global _index
    with _lock:
        if _index is not None:
            return _index
        try:
            raw = json.loads(DATA.read_text(encoding="utf-8"))
            _index = {r["name"]: r for r in raw["genres"]}
            log.info("enao: %d genres loaded", len(_index))
        except FileNotFoundError:
            # Expected on a fresh clone -- the snapshot is built locally.
            _index = {}
        except (OSError, ValueError, KeyError) as e:
            log.warning("enao: unusable snapshot at %s (%s); genre reference disabled", DATA, e)
            _index = {}
        return _index


def get(style):
    """Look up one Discogs style label. Returns its genre record, or None.

    None means "no confident counterpart" -- either a Non-Music style or a
    genuine gap. Callers should fall back, not substitute something arbitrary.
    """
    idx = _load()
    if not idx:
        return None
    variants = _variants(style)
    if not variants or variants[0] in NON_MUSIC:
        return None
    for v in variants:
        hit = idx.get(v)
        if hit:
            return hit
    for v in variants:
        alias = ALIASES.get(v)
        if alias and alias in idx:
            return idx[alias]
    return None


def color(style, default=None):
    """Canonical ``#rrggbb`` for a style, or ``default`` when unmapped."""
    rec = get(style)
    return rec["color"] if rec else default


def position(styles):
    """Score-weighted centroid of several styles in the 2-D genre space.

    ``styles`` is the classifier's ranked list -- ``[{"style": ..., "score":
    ...}, ...]``, the same shape ``_dominant_style`` consumes; bare strings work
    too and count equally. Unmapped styles are skipped rather than dragging the
    centroid toward an arbitrary point, so a track whose top style is unmapped
    still places using its runners-up. Returns ``(x, y)``, or None if nothing
    mapped.
    """
    sx = sy = wsum = 0.0
    for s in styles or []:
        is_dict = isinstance(s, dict)
        rec = get(s.get("style") if is_dict else s)
        if not rec:
            continue
        try:
            w = float(s.get("score", 1.0)) if is_dict else 1.0
        except (TypeError, ValueError):
            w = 1.0
        if w <= 0:
            continue
        sx += rec["x"] * w
        sy += rec["y"] * w
        wsum += w
    return (sx / wsum, sy / wsum) if wsum else None


def axes(styles):
    """The two interpretable axes for a style list, each normalised to 0.0-1.0.

    Returns ``{"organic": float, "bouncy": float}`` -- 0 = mechanical/electric
    and dense/atmospheric, 1 = organic/acoustic and spiky/bouncy -- or None if
    nothing mapped. This is the honest read of the coordinates: the axes carry
    real meaning, so a track's *placement* along them is meaningful even though
    fine-grained distances between genres are not (see the module docstring).
    """
    pos = position(styles)
    if pos is None:
        return None
    idx = _load()
    xmax = max(r["x"] for r in idx.values()) or 1
    ymax = max(r["y"] for r in idx.values()) or 1
    return {"organic": pos[1] / ymax, "bouncy": pos[0] / xmax}


def coverage(labels):
    """``(mapped, total, unmapped_labels)`` for a label set. Used by tests/tools."""
    misses = [x for x in labels if not get(x)]
    return len(labels) - len(misses), len(labels), misses
