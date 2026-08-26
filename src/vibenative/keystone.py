"""Keystone genres: the one-or-two labels that say what a track actually *is*.

The classifier emits up to eight weighted Discogs styles per track. That's the
right resolution for analysis and the wrong one for finding a record -- a track
reading 38% Progressive House / 22% Tech House / 14% Deep House is, to anyone
who plays it, simply **House**. A subgenre of house is still house.

So this module collapses the style read to a **keystone**: the family a DJ would
name first. Subgenres survive underneath it, ranked, as detail rather than
identity -- which is what makes sorting work at both altitudes at once.

Two keystones appear only when a track genuinely straddles a boundary. The bar
is ``FUSION_THRESHOLD`` (0.35) of the runner-up's share, chosen by measuring the
real library rather than guessing: the median track is 84% a single keystone, so
at 0.35 about 6.5% of tracks earn a second one. A 0.45 bar -- the intuitive
"nearly even split" -- fired on 1.0% of tracks, which would have made fusion
labels a curiosity instead of a category.

Where the two keystones have an established name for the blend, it's used
(Dubstep + Drum n Bass = Drumstep). Where they don't, they're simply joined with
a slash. Inventing plausible-sounding fusion names for arbitrary pairs would
produce confident nonsense, so ``FUSION_NAMES`` stays a short curated list.

Reads ``payload["salience"]`` -- the energy x confidence x recurrence weighted
identity that ``analysis.salience_read`` already stores on every track -- so
keystones are computed at *read* time and cost no re-scan. Changing the taxonomy
below re-labels the whole library on the next request.
"""

# Fraction of the keystone weight a runner-up needs before a track is a fusion.
FUSION_THRESHOLD = 0.35

# --- the electronic split -----------------------------------------------------
# Discogs files all 106 of these under one "Electronic" parent, which is useless
# for a dance library: it puts Dubstep and Deep House in the same bucket. This is
# the DJ-facing split. Everything not listed here falls back to the rules below.
_ELECTRONIC = {
    "House": [
        "house",
        "deep house",
        "tech house",
        "electro house",
        "progressive house",
        "garage house",
        "ghetto house",
        "ghetto",
        "tropical house",
        "italo house",
        "acid house",
        "hip-house",
        "speed garage",
        "uk garage",
        "bassline",
        "tribal house",
        "tribal",
        "disco polo",
        "beatdown",
        "euro house",
        "juke",
    ],
    "Techno": [
        "techno",
        "deep techno",
        "hard techno",
        "minimal techno",
        "dub techno",
        "schranz",
        "minimal",
        "acid",
        "bleep",
    ],
    "Trance": [
        "trance",
        "tech trance",
        "hard trance",
        "progressive trance",
        "goa trance",
        "psy-trance",
    ],
    "Dubstep": ["dubstep", "grime"],
    "Drum n Bass": ["drum n bass", "jungle"],
    "Halftime": ["halftime"],
    "Hard Dance": [
        "hardstyle",
        "hardcore",
        "happy hardcore",
        "gabber",
        "speedcore",
        "makina",
        "jumpstyle",
        "hands up",
        "donk",
        "hard house",
    ],
    "Breakbeat": [
        "breakbeat",
        "breaks",
        "big beat",
        "broken beat",
        "progressive breaks",
        "breakcore",
    ],
    "Electro": ["electro", "electroclash", "freestyle", "miami bass"],
    "Ambient": ["ambient", "dark ambient", "drone", "dungeon synth", "new age", "berlin-school"],
    "Downtempo": [
        "downtempo",
        "trip hop",
        "chillwave",
        "synthwave",
        "vaporwave",
        "illbient",
        "lounge",
        "future jazz",
        "jazzdance",
        "acid jazz",
        "dub",
    ],
    "Disco": [
        "disco",
        "nu-disco",
        "italo-disco",
        "euro-disco",
        "eurobeat",
        "hi nrg",
        "italodance",
        "eurodance",
    ],
    "Industrial": [
        "industrial",
        "ebm",
        "new beat",
        "power electronics",
        "rhythmic noise",
        "noise",
        "darkwave",
        "coldwave",
    ],
    "Experimental": [
        "experimental",
        "idm",
        "glitch",
        "abstract",
        "leftfield",
        "musique concrète",
        "sound collage",
        "chiptune",
    ],
}

# Styles whose keystone overrides their Discogs parent. Trap sits under Hip Hop
# in the label set but earns its own keystone here: it's a distinct thing to a
# DJ and it overlaps the halftime/bass material heavily.
_OVERRIDES = {
    "trap": "Trap",
    "hip hop": "Hip Hop",
    "new wave": "Rock",
    "neofolk": "Folk",
    "modern classical": "Classical",
    "latin": "Latin",
    # Discogs files Lo-Fi under Rock, which would send it to the Other family and
    # out of an electronic library's taxonomy entirely. In practice the label
    # covers lo-fi hip hop and lofi house -- Chill material, not rock.
    "lo-fi": "Lo-Fi",
}

# Discogs' "Rock" parent spans Slowdive and Cannibal Corpse. Split it by
# substring, which covers the ~30 metal styles without listing each. Substring
# and not \bword\b: the boundary form misses "metalcore" and "goregrind", where
# the tell is glued to the next word.
_METAL_EXTRA = {
    "thrash",
    "sludge",
    "doom",
    "deathcore",
    "mathcore",
    "noisecore",
    "djent",
    "stoner rock",
    "crossover thrash",
}
_PUNK_EXTRA = {
    "emo",
    "psychobilly",
    "oi",
    "crust",
    "hardcore",
    "post-hardcore",
    "melodic hardcore",
    "screamo",
    "powerviolence",
    "power violence",
}

# Discogs parents that already read as sensible keystones, used verbatim.
_PARENT_OK = {
    "Hip Hop",
    "Jazz",
    "Funk / Soul",
    "Pop",
    "Latin",
    "Reggae",
    "Blues",
    "Classical",
    "Stage & Screen",
    "Non-Music",
    "Brass & Military",
    "Children's",
}

# Blends with an established name. Anything not here is joined with " / " rather
# than invented. Keys are frozensets so order never matters.
#
# A fusion name must NOT also be a Discogs style, or the taxonomy contradicts
# itself: "Tech House" is tempting for House + Techno, but a track the model
# reads *as* Tech House keystones to House and would display "House" -- so the
# same blend would carry two different names depending on which path reached it.
# Tech House, Tech Trance, Hard Trance and Jungle are excluded for that reason
# and fall back to the slash form. test_keystone.py enforces this.
FUSION_NAMES = {
    frozenset({"Dubstep", "Drum n Bass"}): "Drumstep",
    frozenset({"House", "Disco"}): "Disco House",
    frozenset({"Dubstep", "Trap"}): "Hybrid Trap",
    frozenset({"House", "Breakbeat"}): "Breakbeat House",
}

_STYLE_TO_KEYSTONE = {s: k for k, styles in _ELECTRONIC.items() for s in styles}

# --- the three tiers ----------------------------------------------------------
# archgenre -> keystone -> subgenre.
#
# The archgenre is what you'd call a room at a festival; the keystone is what a
# track *is*; the subgenre is detail. House is an archgenre, not a member of a
# "Dance" grouping -- it stands on its own the way Techno and Trance do. Bass
# stays a grouping because dubstep and drum and bass are genuinely siblings under
# it, where "dance" was a category so broad it grouped almost everything.
#
# Only the archgenres that hold more than one keystone need listing; a keystone
# with no archgenre above it IS its own archgenre (House, Techno, Trance...).
# That keeps the table small and stops it drifting from _ELECTRONIC.
ARCHGENRE_OF = {
    "Dubstep": "Bass",
    "Drum n Bass": "Bass",
    "Halftime": "Bass",
    "Trap": "Bass",
    "Breakbeat": "Bass",
    "Ambient": "Chill",
    "Downtempo": "Chill",
    "Lo-Fi": "Chill",
    "Experimental": "Experimental",
    "Industrial": "Experimental",
}

# Where a keystone that stands alone sits in the display order.
STANDALONE_ARCHGENRES = ["House", "Techno", "Trance", "Hard Dance", "Electro", "Disco"]


def archgenre_of(keystone):
    """The archgenre a keystone belongs to.

    A keystone with no entry is its own archgenre -- House is not "a kind of
    Dance", it is the top of its own tree.
    """
    from .taxonomy import archgenre_override

    if not keystone:
        return OTHER_FAMILY
    if family_of(keystone) == OTHER_FAMILY:
        return OTHER_FAMILY
    # "" is a real answer here -- "I promoted this to stand on its own" -- and
    # has to be distinguishable from "no opinion", or a keystone the shipped
    # table files under something could never be lifted out of it.
    ov = archgenre_override(keystone)
    if ov is not None:
        return ov or keystone
    return ARCHGENRE_OF.get(keystone, keystone)


def archgenre_order():
    """Archgenres in display order: the standalone ones, then the groupings."""
    from .taxonomy import load as user_overlay
    from .taxonomy import order as user_order

    groups = []
    for a in ARCHGENRE_OF.values():
        if a not in groups:
            groups.append(a)
    # An overlay can name an archgenre the built-in tables have never heard of --
    # "put Halftime under Drum n Bass" makes Drum n Bass one, though it ships as
    # a keystone. Without this the group has no place in the order and every
    # track in it drops out of the Genres tab.
    for a in user_overlay()["archgenre"].values():
        if a and a not in groups:
            groups.append(a)
    built_in = STANDALONE_ARCHGENRES + groups + [OTHER_FAMILY]
    # A user ordering leads; anything it doesn't mention keeps its built-in
    # position behind it, so a partial ordering ("I only care that House is
    # first") is a usable thing to write.
    out = [a for a in user_order() if a not in (OTHER_FAMILY,)]
    out += [a for a in built_in if a not in out]
    return out


# --- families: the tier above keystones ---------------------------------------
# Three levels, widest first: family -> keystone -> subgenre. The family answers
# "what kind of set does this belong in", which is the question you're asking
# when sorting a few thousand unknown files; the keystone answers "what is it";
# the subgenre is detail.
#
# This app is for an electronic library, so everything non-electronic collapses
# into one family rather than earning its own branch. Those keystones survive as
# labels (a Metal track still says Metal) but they group under Other and don't
# consume a palette slot -- 51 tracks here, and none of them are what the tool is
# for.
#
# Measured shape of this library: Dance 50.6%, Bass 42.5%, Other 2.7%,
# Chill 2.5%, Experimental 1.8%. That 93% in two families is exactly why colour
# lives on the keystone and not here -- see palette.py.
FAMILIES = {
    "Dance": ["House", "Techno", "Trance", "Hard Dance", "Disco", "Electro"],
    "Bass": ["Dubstep", "Drum n Bass", "Halftime", "Trap", "Breakbeat"],
    "Chill": ["Ambient", "Downtempo", "Lo-Fi"],
    "Experimental": ["Experimental", "Industrial"],
}
OTHER_FAMILY = "Other"

_KEYSTONE_TO_FAMILY = {k: f for f, ks in FAMILIES.items() for k in ks}

# Family display order: the electronic families in the order a set tends to be
# built, then Other last. Not by size -- a fixed order keeps the map stable as
# the library grows.
FAMILY_ORDER = ["Dance", "Bass", "Chill", "Experimental", OTHER_FAMILY]


def family_of(keystone):
    """The family a keystone belongs to. Non-electronic keystones get "Other".

    A user overlay wins: the shipped table is one library's opinion, and this is
    where the person with the library says otherwise. See ``taxonomy``.
    """
    from .taxonomy import family_override

    return family_override(keystone) or _KEYSTONE_TO_FAMILY.get(keystone, OTHER_FAMILY)


def keystone_of(label):
    """The keystone for one style label. ``label`` may be a bare style ("Deep
    House") or a full Discogs label ("Electronic---Deep House").

    Resolution order: explicit override, then the Discogs parent if we have one
    (Rock gets the keyword split, Electronic the table above), and only for a
    bare style does the electronic table get consulted parent-blind. Returns
    None when the label carries no useful family -- Non-Music, or a bare style
    the taxonomy doesn't cover.
    """
    if not label:
        return None
    parent, _, tail = label.rpartition("---")
    style = tail.strip().lower()
    if not style:
        return None
    # A user alias outranks every built-in table: it is the one statement in
    # this chain that somebody made on purpose about their own library.
    hit = _overlay_alias(style, parent)
    if hit:
        return hit
    if style in _OVERRIDES:
        return _OVERRIDES[style]

    # The parent decides first when we have one. Several style names live under
    # two parents with unrelated meanings -- Electronic---Hardcore is gabber's
    # cousin, Rock---Hardcore is Black Flag -- so consulting the electronic
    # table before checking the parent silently mis-files the rock ones.
    if parent:
        if parent == "Non-Music":
            return None
        if parent == "Rock":
            return _rock_keystone(style)
        if parent == "Electronic":
            return _STYLE_TO_KEYSTONE.get(style)
        return parent if parent in _PARENT_OK else None

    # A bare style (salience stores these without their parent). The electronic
    # reading wins on collision, which is the right default for a dance library
    # -- payload["styles"] keeps the parent if a caller needs to disambiguate.
    if style in _STYLE_TO_KEYSTONE:
        return _STYLE_TO_KEYSTONE[style]
    if style in _USER_ALIASES:
        return _USER_ALIASES[style]
    if _looks_rock(style):
        return _rock_keystone(style)
    # The lexicon before the word heuristic: it carries 1,137 curated aliases,
    # while the heuristic is a guess at the head noun. Run the other way round,
    # "hard wave" matched the word "wave" and landed in Downtempo instead of
    # following its alias to hardwave -> Hard Dance.
    hit = _lexicon_keystone(style)
    if hit:
        return hit
    # Loosest inference, so it goes last: read the name as "a kind of <keystone>".
    return _word_keystone(style)


def _overlay_alias(style, parent):
    """A user-defined alias for this style, or None.

    Scoped to bare styles and ``Electronic---`` labels on purpose. Several style
    names live under two parents with unrelated meanings -- ``Rock---Hardcore``
    is Black Flag, ``Electronic---Hardcore`` is gabber -- so letting an overlay
    entry for "hardcore" apply parent-blind would re-introduce exactly the
    mis-filing the parent-first rule exists to prevent. Names you type in the
    override box arrive bare, which is the case this serves.
    """
    if parent and parent != "Electronic":
        return None
    from .taxonomy import alias_of

    return alias_of(style)


def _lexicon_keystone(style):
    """Resolve via the electronic-genre lexicon's parent hierarchy.

    Covers names the model cannot emit and the tables above don't list --
    ``riddim`` (parent: dubstep), ``neurofunk`` (drum and bass), ``amapiano``
    (house music). Last in the chain because it's the only source we don't
    curate: a table entry should always win over an inferred one.

    Imported lazily and tolerated if absent -- the crawl is a git-ignored
    artefact, so a fresh clone simply has one fewer resolution step.
    """
    try:
        from . import genrelex
    except ImportError:  # pragma: no cover -- defensive
        return None
    return genrelex.resolve_keystone(style, _keystone_no_lexicon)


def _keystone_no_lexicon(label):
    """``keystone_of`` minus the lexicon step, for the lexicon to call back into.

    Without this the two would recurse: the lexicon asks the taxonomy about a
    parent, the taxonomy asks the lexicon about it again, and a cycle in the
    source data becomes an infinite loop rather than a miss.
    """
    if not label:
        return None
    parent, _, tail = label.rpartition("---")
    style = tail.strip().lower()
    if not style:
        return None
    hit = _overlay_alias(style, parent)
    if hit:
        return hit
    if style in _OVERRIDES:
        return _OVERRIDES[style]
    if parent:
        if parent == "Non-Music":
            return None
        if parent == "Rock":
            return _rock_keystone(style)
        if parent == "Electronic":
            return _STYLE_TO_KEYSTONE.get(style)
        return parent if parent in _PARENT_OK else None
    if style in _STYLE_TO_KEYSTONE:
        return _STYLE_TO_KEYSTONE[style]
    if style in _USER_ALIASES:
        return _USER_ALIASES[style]
    if _looks_rock(style):
        return _rock_keystone(style)
    # No lexicon step here -- that's the whole point of this variant.
    return _word_keystone(style)


# Genre names that only ever arrive from a *manual override* -- things you typed
# because the model has no label for them. Kept apart from _OVERRIDES, which maps
# real Discogs styles: a test asserts every _OVERRIDES key is a label the model
# can actually emit, and these deliberately aren't.
_USER_ALIASES = {
    # Checked before the compound-name heuristic below, which would read the
    # rightmost word as the head noun and file "Trap Wave" under Downtempo. The
    # tracks say otherwise: they read as Dubstep/Grime/Trap at a median 140 BPM.
    "trap wave": "Dubstep",
    # Phonk is Memphis-rap derived; the model has no label for it at all and
    # hears breakcore/speedcore underneath, so this is genre knowledge, not a
    # reading of the audio.
    "phonk": "Trap",
    "drift phonk": "Trap",
    "wave": "Downtempo",
    "hardwave": "Hard Dance",
    "colour bass": "Dubstep",
    "color bass": "Dubstep",
    "melodic dubstep": "Dubstep",
    "riddim": "Dubstep",
    "tearout": "Dubstep",
    "liquid": "Drum n Bass",
    "neurofunk": "Drum n Bass",
    "jump up": "Drum n Bass",
    "afro house": "House",
    "amapiano": "House",
    "melodic techno": "Techno",
    "chillhop": "Lo-Fi",
}


def _word_keystone(style):
    """Last word in a compound name that resolves to a keystone.

    A typed genre is usually its head noun plus modifiers -- "Big Room House",
    "Trap Wave", "Melodic Drum n Bass". Reading right-to-left finds the family
    the name is a *kind of*, so a name the tables have never seen still lands
    somewhere sensible instead of in Other.

    Only used after the exact-match paths fail, so it can never override a
    genuine label; and it takes the rightmost match, because "Trap Wave" is a
    wave and "Wave Trap" would be a trap.
    """
    words = style.split()
    for i in range(len(words), 0, -1):
        for j in range(0, i):
            phrase = " ".join(words[j:i])
            if phrase == style:
                continue  # already tried as a whole
            hit = _STYLE_TO_KEYSTONE.get(phrase) or _USER_ALIASES.get(phrase)
            if hit:
                return hit
            if phrase in _OVERRIDES:
                return _OVERRIDES[phrase]
    return None


def _looks_rock(style):
    return (
        "metal" in style
        or "grind" in style
        or "punk" in style
        or style in _METAL_EXTRA
        or style in _PUNK_EXTRA
    )


def _rock_keystone(style):
    if "metal" in style or "grind" in style or style in _METAL_EXTRA:
        return "Metal"
    if "punk" in style or style in _PUNK_EXTRA:
        return "Punk"
    return "Rock"


def _tally(ranked):
    """Sum style scores onto their keystones, preserving each keystone's styles."""
    weights, styles = {}, {}
    for entry in ranked or []:
        if isinstance(entry, dict):
            style, score = entry.get("style"), entry.get("score", 0)
        else:
            style, score = entry, 0
        k = keystone_of(style)
        if not k:
            continue
        try:
            score = float(score or 0)
        except (TypeError, ValueError):
            score = 0.0
        if score <= 0:
            continue
        weights[k] = weights.get(k, 0.0) + score
        styles.setdefault(k, []).append({"style": style, "score": score})
    return weights, styles


def classify(payload):
    """Collapse a track's style read to its keystone identity.

    Returns::

        {
          "keystones": ["Dubstep", "Drum n Bass"],   # 1 or 2, strongest first
          "label":     "Drumstep",                   # what to display
          "shares":    {"Dubstep": 0.55, "Drum n Bass": 0.41},
          "subgenres": [{"style": "Dubstep", "score": 0.42, "keystone": "Dubstep"}, ...],
          "fusion":    True,
        }

    ``shares`` are normalised over the keystoned weight only, so styles the
    taxonomy doesn't cover (spoken word, a stray misread) don't dilute the
    result. Returns None when nothing in the read maps to a keystone.

    A manual override (POST /override) wins outright, exactly as it does for
    ``_dominant_style`` -- if you've told the app what a track is, that's what
    it is, and it reports as a single keystone with full confidence.
    """
    payload = payload or {}
    override = payload.get("override")
    if override:
        k = keystone_of(override) or override
        return {
            "keystones": [k],
            "archgenre": archgenre_of(k),
            "archgenres": [archgenre_of(k)],
            "family": family_of(k),
            "families": [family_of(k)],
            "cross_family": False,
            "label": k,
            "key": group_key([k]),
            "shares": {k: 1.0},
            "subgenres": [{"style": override, "score": 1.0, "keystone": k}],
            "fusion": False,
            "override": True,
        }

    # Precedence matches routes._shared._dominant_style: a retroactive re-label
    # is a newer head's judgement and outranks the original salience read.
    # Salience is otherwise the better signal, but it's energy-weighted and can
    # come back all-zero on a very quiet track, so the flat scores backstop it
    # rather than dropping the track out of the taxonomy entirely.
    from .weights import read_with_steps

    # Same precedence as routes._shared._dominant_style, or the map and the
    # label would disagree about a track you had just adjusted by hand.
    weights, styles = _tally(read_with_steps(payload))
    if not weights:
        weights, styles = _tally((payload.get("relabel") or {}).get("styles"))
    if not weights:
        weights, styles = _tally(payload.get("salience"))
    if not weights:
        weights, styles = _tally(payload.get("styles"))
    if not weights:
        return None

    total = sum(weights.values())
    order = sorted(weights.items(), key=lambda kv: -kv[1])
    primary, top_w = order[0]
    keystones = [primary]
    if len(order) > 1 and order[1][1] / total >= FUSION_THRESHOLD:
        keystones.append(order[1][0])

    subgenres = [
        dict(s, keystone=k) for k, _ in order for s in sorted(styles[k], key=lambda s: -s["score"])
    ]
    families = []
    for k in keystones:
        f = family_of(k)
        if f not in families:
            families.append(f)
    arches = []
    for k in keystones:
        a = archgenre_of(k)
        if a not in arches:
            arches.append(a)
    return {
        "keystones": keystones,
        "archgenre": arches[0],
        "archgenres": arches,
        "family": families[0],
        "families": families,
        "cross_family": len(families) > 1,
        "label": label_for(keystones),
        "key": group_key(keystones),
        "shares": {k: round(w / total, 4) for k, w in order},
        "subgenres": subgenres,
        "fusion": len(keystones) > 1,
    }


def group_key(keystones):
    """Order-independent identity for a keystone set, for grouping and sorting.

    ``label`` keeps the keystones in strength order, because "Dubstep / Hard
    Dance" and "Hard Dance / Dubstep" really do describe different tracks. But
    they belong in the *same* bin when you're browsing, and without this they'd
    split into two categories that each look half as populated as the blend
    actually is. Group on this; display ``label``.
    """
    return " + ".join(sorted(keystones))


def label_for(keystones):
    """Display label for one or two keystones: an established blend name where
    one exists, otherwise the pair joined with a slash (strongest first)."""
    if not keystones:
        return ""
    if len(keystones) == 1:
        return keystones[0]
    return FUSION_NAMES.get(frozenset(keystones)) or " / ".join(keystones)
