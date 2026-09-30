"""The built-in genre tables: Discogs style -> keystone, keystone ->
archgenre -> family, fusion names, and the names only a manual override uses.

Data only; taxonomy/classify.py reads it (and the user's overlay on top of it).
Moved verbatim from keystone.py.
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
# lives on the keystone and not here -- see keystone_colors.py.
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
