"""Keystone palette: a colour per keystone, shaded per subgenre, ringed per track.

Colour here answers two questions at once -- *which* keystone a track belongs to,
and *how much* of each when it straddles two. Those two goals fight, and the
resolution below is the only one that measured out honestly.

**Why a track is concentric rings and not a blended colour.** Averaging two hues
lands in a third hue's territory. Measured on this palette: House green + Trance
violet averages into territory nearer a third keystone than either parent -- a
flat blend silently relabels the track. So a track paints as **rings**: the
keystone fills the centre, each further keystone is a band around it, and band
width carries the share. Every colour stays a discrete, unmixed patch, so no
mixing artefact can invent a genre that isn't there, and the ratio is still
visible as ring thickness.

This also softens the close-pair problem below: two similar hues sitting in
separate bands are far easier to separate than the same two averaged together.

**Why only eight keystones get a hue.** Categorical colour tops out at eight
slots, and a scatter plot is the hard case -- every mark can sit beside every
other, so all pairs must separate, and past three slots that's unachievable at
any ordering. Eight validates on *adjacent* pairs in both modes (worst CVD ΔE 9.1
light / 8.4 dark; worst normal-vision ΔE 19.6 / 19.3). Beyond eight, hues would
have to be recycled or invented, and two keystones sharing a colour is worse than
one of them being grey. Which eight, and which hue each gets, is solved against
the library -- see ``KEYSTONE_SLOT``. The tail gets a neutral and leans on its
label, which the map already draws.

Colour is therefore never the *only* carrier of identity here -- the node label
is. That's also what makes the sub-3:1 contrast slots legal in light mode.

Palette values are the validated default categorical ramp; both modes are
selected steps, not an automatic flip.
"""

# Categorical slots, in validated order. Light and dark are separate selected
# steps -- do not derive one from the other.
_SLOTS = [
    ("blue", "#2a78d6", "#3987e5"),
    ("orange", "#eb6834", "#d95926"),
    ("aqua", "#1baf7a", "#199e70"),
    ("yellow", "#eda100", "#c98500"),
    ("magenta", "#e87ba4", "#d55181"),
    ("green", "#008300", "#008300"),
    ("violet", "#4a3aa7", "#9085e9"),
    ("red", "#e34948", "#e66767"),
]

# Which keystone gets which slot. NOT ordered by library size -- that was tried
# and it put orange beside red for Dubstep + Hard Dance, the second most common
# fusion, at ΔE 7.1 (unreadable). What matters is which keystones actually get
# *fused*, because a fusion puts two hues in direct contact as adjacent bands.
#
# So the assignment is solved against the real blend list: maximise the worst
# separation over every fusion pair that occurs, tie-broken on the
# frequency-weighted mean. Slotted keystones are the eight *electronic* ones with
# the highest involvement (appearances in any keystone set, not just as the
# dominant read).
#
# Electronic only, deliberately. Metal held a slot until families landed; this is
# a tool for an electronic library, so a non-electronic keystone earning a hue
# over Breakbeat (47 tracks that actually get sorted) was backwards. Everything in
# the Other family takes the neutral.
#
# That swap costs something and it's worth knowing: Metal barely fused with
# anything, while Breakbeat fuses with six other keystones, so it adds
# constraints the solver has to satisfy. Worst pair went 19.3 -> 13.0
# (Dubstep + Trance, 2 tracks). Still well clear of the ΔE 8 "indistinguishable"
# line, and rings keep the two as separate bands rather than merging them.
#
# Re-solve this if the library's blend profile shifts a lot; the assignment is
# tuned to the collection, not to genre convention. Colour follows the entity --
# filtering the view must never repaint the survivors.
#
# Hue is the *keystone's* encoding, not the family's: 93% of the library is two
# families, so colouring by family would paint almost the whole map two colours.
# Family reads from position on the map instead -- see keystone.FAMILIES.
#
# Allocation runs a **floor of one slot per electronic family** before handing
# the rest out by involvement. Without that floor the top eight were all Dance
# and Bass, leaving Chill and Experimental entirely grey -- which read as "these
# don't matter" when it only meant "these are small in today's library". The
# floor also happens to separate better (worst real-blend pair ΔE 23.4 vs 13.0),
# because the keystones it drops -- Hard Dance, Breakbeat -- were the ones
# fusing with everything and over-constraining the solver.
#
# Grouping a family into *neighbouring* hues was tried and abandoned: putting
# Dance on warm and Bass on cool made a family legible at a glance but its
# members indistinguishable from each other (orange/red ΔE 7.1, seven pairs under
# floor). Family-at-a-glance and keystone-discrimination want opposite things
# from hue, so family reads from position and tint instead -- never from hue.
KEYSTONE_SLOT = {
    "House": 0,  # blue     [Dance]
    "Downtempo": 1,  # orange   [Chill]
    "Industrial": 2,  # aqua     [Experimental]
    "Drum n Bass": 3,  # yellow   [Bass]
    "Techno": 4,  # magenta  [Dance]
    "Dubstep": 5,  # green    [Bass]
    "Halftime": 6,  # violet   [Bass]
    "Trance": 7,  # red      [Dance]
}

# Everything past the eight slots. Not a failure state -- a deliberate "Other".
# Chosen to be *recessive* (a catch-all shouldn't be the loudest thing on the
# map) while still clearing the ΔE 15 floor against all eight hues: the obvious
# mid-greys sit inside the hues' own lightness band and only differ in chroma,
# which measured at ΔE 12.7 -- confusable with Hard Dance. These step outside the
# band instead. Worst separation: 18.0 light, 22.7 dark.
NEUTRAL = {"light": "#cccccc", "dark": "#454545"}

# Pairs that do NOT clear the readability floor, by mode. This is the honest
# residual of using eight categorical hues on a scatter: a fusion can pair any
# two keystones, and past three slots no ordering separates all 28 pairs -- the
# palette was solved against the pairs the library *actually* produces (worst
# ΔE 19.3, all clear), not against every pair that could ever occur.
#
# Rings make this much less damaging than blending did -- the two colours stay
# separate bands rather than merging into a third -- but a close pair still reads
# as one fat band instead of two, so the ratio is lost even though the identity
# survives on the label. Listed rather than hidden so it's visible when it bites;
# the test suite pins the set so an edit to KEYSTONE_SLOT can't quietly enlarge it.
KNOWN_CLOSE_PAIRS = {
    "light": {
        ("Downtempo", "Trance"),
        ("Downtempo", "Techno"),
        ("Techno", "Trance"),
        ("Downtempo", "Drum n Bass"),
    },
    "dark": {
        ("Downtempo", "Trance"),
        ("Techno", "Trance"),
        ("Halftime", "House"),
        ("Downtempo", "Drum n Bass"),
        ("Downtempo", "Techno"),
        ("Dubstep", "Industrial"),
        ("Drum n Bass", "Trance"),
    },
}

SURFACE = {"light": "#fcfcfb", "dark": "#1a1a19"}


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(c))) for c in rgb)


# The largest keystone in each family -- the one the allocation floor slots
# first, so every family owns a hue through it. Used by the UI to colour a
# family heading; NOT used to tint the family's other members (see below).
FAMILY_LEAD = {
    "Dance": "House",
    "Bass": "Dubstep",
    "Chill": "Downtempo",
    "Experimental": "Industrial",
}


def keystone_color(keystone, mode="dark"):
    """Base colour for a keystone: its categorical hue, or the neutral.

    Only eight keystones carry a hue, and the allocation floor guarantees one
    per electronic family -- so Chill and Experimental each own a colour through
    their lead, even while small.

    Everything else is the neutral. A family *tint* was tried for these (the
    family's hue muted toward grey, so a minor Chill genre would still read as
    Chill) and measured out impossible: a tint sits between its family's hue and
    the grey, so no muting level is far enough from both. Across the whole
    parameter space the best case still left a tint within ΔE 10 of a full hue --
    close enough to mistake a minor genre for a major one, which is worse than
    plain grey. Family reads from position on the map and from the label, which
    were always going to carry it.
    """
    # A user colour wins outright, including over the neutral -- claiming a hue
    # for a genre the solver left grey is a legitimate thing to want, and the
    # separation guarantees below only bind the eight slots this file solved.
    from .taxonomy import color_override

    chosen = color_override(keystone)
    if chosen:
        return chosen
    idx = KEYSTONE_SLOT.get(keystone)
    if idx is None:
        return NEUTRAL.get(mode, NEUTRAL["dark"])
    _, light, dark = _SLOTS[idx]
    return dark if mode == "dark" else light


def _stable_unit(text):
    """A repeatable value in [-1, 1] from a string.

    Python's ``hash()`` is salted per process, so using it would repaint the
    library on every restart.
    """
    acc = 0
    for ch in str(text or "").lower():
        acc = (acc * 31 + ord(ch)) % 1009
    return ((acc / 1009.0) * 2.0) - 1.0


def _nudge(color, seed, spread):
    """Shift a colour's lightness deterministically, keeping its hue."""
    factor = 1.0 + spread * _stable_unit(seed)
    return _rgb_to_hex(c * factor for c in _hex_to_rgb(color))


def subgenre_shade(keystone, style, mode="dark", spread=0.18):
    """A keystone's colour, nudged so its subgenres are distinguishable *within*
    the family without leaving it.

    Deep House and Tech House must not be the same pixel, but neither may drift
    far enough to read as a different keystone. So the nudge moves lightness
    only -- hue and chroma are the keystone's signature and stay put -- by a
    deterministic amount derived from the style name, within +/-``spread``.

    Deterministic on purpose: the same subgenre is the same colour on every
    machine and across restarts, with nothing persisted.
    """
    base = keystone_color(keystone, mode)
    return _nudge(base, style, spread) if style else base


# A keystone needs at least this share of a track to earn a ring. Lower than
# keystone.FUSION_THRESHOLD on purpose: the *label* answers "what is this track",
# which should stay decisive, while the rings show composition, where a visible
# minority is worth seeing. Measured against the library, 0.15 is also where a
# third keystone stops being real -- its median share is 0.033, so anything much
# below this paints model noise as though it were a genre.
RING_MIN_SHARE = 0.15

# Rings per node. Two is the default because a third almost never carries
# information (only ~7% of tracks have a third keystone above RING_MIN_SHARE).
MAX_RINGS = 2

# No band may be thinner than this fraction of the radius, or a 95/5 track
# renders its minority as an invisible hairline. Presence matters more than
# exact proportion at map scale.
_MIN_BAND = 0.18


def track_paint(classification, mode="dark", max_rings=MAX_RINGS):
    """How to paint one track, from a ``keystone.classify()`` result.

    Returns ``None`` for an unclassified track, otherwise a set of concentric
    bands, innermost (the keystone) first::

        {"rings": [{"keystone": "House",  "color": "#008300", "frac": 0.68},
                   {"keystone": "Trance", "color": "#9085e9", "frac": 0.32}],
         "color": "#008300",   # the keystone colour, for flat-fill callers
         "fusion": True}

    ``frac`` is each band's share of the radius, summing to 1. Bands are drawn
    outward: the first is a filled disc of radius ``frac[0]``, the rest are
    annuli. A caller that can only manage one colour uses ``color`` -- which is
    the keystone's, never an average.

    Consecutive bands that would be the same colour are merged; two unslotted
    keystones both painting the neutral would otherwise draw a grey ring on a
    grey disc, which looks deliberate but says nothing.
    """
    if not classification:
        return None
    keystones = classification.get("keystones") or []
    if not keystones:
        return None
    shares = classification.get("shares") or {}
    subs = classification.get("subgenres") or []
    top = keystones[0]

    # shares carries every keystone present, ranked -- not just the one or two
    # the label commits to -- so a visible minority can earn a ring without
    # changing what the track is called.
    ranked = sorted(shares.items(), key=lambda kv: -float(kv[1] or 0))
    picked = [(k, float(v)) for k, v in ranked[:max_rings] if float(v or 0) >= RING_MIN_SHARE]
    if not picked or picked[0][0] != top:
        picked = [(top, float(shares.get(top, 1.0) or 1.0))] + [p for p in picked if p[0] != top][
            : max_rings - 1
        ]

    # The innermost band uses the subgenre shade so two house tracks of different
    # subgenres still differ; outer bands stay the plain keystone hue, since a
    # shaded ring would blur the family boundary it exists to mark.
    lead_style = subs[0].get("style") if subs else None
    colors = [subgenre_shade(top, lead_style, mode)] + [
        keystone_color(k, mode) for k, _ in picked[1:]
    ]

    merged = []
    for (k, share), col in zip(picked, colors):
        if merged and merged[-1]["color"] == col:
            merged[-1]["_w"] += share
            continue
        merged.append({"keystone": k, "color": col, "_w": share})

    total = sum(m["_w"] for m in merged) or 1.0
    fracs = _balance([m["_w"] / total for m in merged])
    rings = [
        {"keystone": m["keystone"], "color": m["color"], "frac": round(f, 3)}
        for m, f in zip(merged, fracs)
    ]
    return {
        "rings": rings,
        "color": rings[0]["color"],
        "fusion": bool(classification.get("fusion")),
    }


def _balance(fracs):
    """Give every band at least ``_MIN_BAND`` of the radius, keeping the sum 1."""
    if len(fracs) < 2:
        return [1.0]
    out = [max(f, _MIN_BAND) for f in fracs]
    return [f / sum(out) for f in out]


def edge_paint(a, b, mode="dark"):
    """Colour for a link between two tracks: a hue shift from one keystone to
    the other.

    Unlike a *track*, an edge has no identity of its own to protect -- it exists
    to show a relationship -- so interpolating along it is the right encoding,
    not a hazard. Both endpoints match the nodes they touch, which is what makes
    the shift readable as "these two are different genres".

    Returns ``{"from": ..., "to": ..., "solid": bool}``; ``solid`` is True when
    both ends share a keystone and the line is one colour.
    """
    ka = (a or {}).get("keystones") or [None]
    kb = (b or {}).get("keystones") or [None]
    ca = keystone_color(ka[0], mode) if ka[0] else NEUTRAL[mode]
    cb = keystone_color(kb[0], mode) if kb[0] else NEUTRAL[mode]
    return {"from": ca, "to": cb, "solid": ca == cb}


def css_for(paint):
    """A CSS ``background`` for a paint spec -- concentric rings as a
    radial-gradient with hard stops, so the swatch matches the map node."""
    if not paint or not paint.get("rings"):
        return "transparent"
    rings = paint["rings"]
    if len(rings) == 1:
        return rings[0]["color"]
    stops, at = [], 0.0
    for r in rings:
        end = min(100.0, (at + r["frac"]) * 100)
        stops.append(f"{r['color']} {at * 100:.0f}% {end:.0f}%")
        at += r["frac"]
    return f"radial-gradient(circle, {', '.join(stops)})"


def legend(mode="dark"):
    """Every slotted keystone with its colour, in slot order, for the UI legend.

    A legend is not optional: with eight hues on a scatter, colour alone can't
    carry identity, so the map must name what each one means.
    """
    out = [
        {"keystone": k, "color": keystone_color(k, mode), "slot": i}
        for k, i in sorted(KEYSTONE_SLOT.items(), key=lambda kv: kv[1])
    ]
    out.append({"keystone": "Other", "color": NEUTRAL[mode], "slot": None})
    return out
