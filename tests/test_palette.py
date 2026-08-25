"""Unit tests for the keystone palette.

The colour-separation guarantees are the point of this module, so they're
asserted numerically here rather than trusted: a small OKLab implementation
reproduces the ΔE the palette was solved against, and the tests fail if an
edit to KEYSTONE_SLOT pushes any slotted pair back under the readability floor.
"""

import math

import pytest

from vibenative import palette as P

# Below this OKLab ΔE (x100) two colours are hard to tell apart even with full
# colour vision. Same floor the palette was validated against.
NORMAL_VISION_FLOOR = 15.0


def _srgb_lin(c):
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _oklab(hx):
    h = hx.lstrip("#")
    r, g, b = (_srgb_lin(int(h[i : i + 2], 16)) for i in (0, 2, 4))
    li = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    li, m, s = (x ** (1 / 3) if x > 0 else -((-x) ** (1 / 3)) for x in (li, m, s))
    return (
        0.2104542553 * li + 0.7936177850 * m - 0.0040720468 * s,
        1.9779984951 * li - 2.4285922050 * m + 0.4505937099 * s,
        0.0259040371 * li + 0.7827717662 * m - 0.8086757660 * s,
    )


def dE(a, b):
    return 100 * math.dist(_oklab(a), _oklab(b))


def sol(*keystones, **shares):
    """A minimal classify()-shaped dict."""
    return {"keystones": list(keystones), "shares": shares, "subgenres": []}


# --- the separation guarantee -------------------------------------------------
@pytest.mark.parametrize("mode", ["light", "dark"])
def test_close_pair_set_has_not_grown(mode):
    """Eight categorical hues cannot separate all 28 pairs -- that's a property
    of the colour space, not a fixable bug. What we *can* enforce is that the
    set of unreadable pairs is exactly the documented one, so a reshuffle of
    KEYSTONE_SLOT can't quietly make things worse."""
    ks = sorted(P.KEYSTONE_SLOT)
    close = {
        tuple(sorted((a, b)))
        for i, a in enumerate(ks)
        for b in ks[i + 1 :]
        if dE(P.keystone_color(a, mode), P.keystone_color(b, mode)) < NORMAL_VISION_FLOOR
    }
    documented = {tuple(sorted(p)) for p in P.KNOWN_CLOSE_PAIRS[mode]}
    assert close == documented, f"{mode}: undocumented close pairs {close - documented}"


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_most_pairs_still_separate(mode):
    """The residual must stay a minority -- if a majority of pairs collide the
    palette has stopped carrying identity at all."""
    ks = sorted(P.KEYSTONE_SLOT)
    total = len(ks) * (len(ks) - 1) // 2
    assert len(P.KNOWN_CLOSE_PAIRS[mode]) <= total // 4


def test_slots_are_unique_and_in_range():
    slots = list(P.KEYSTONE_SLOT.values())
    assert sorted(slots) == list(range(len(P._SLOTS)))


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_neutral_is_distinct_from_every_slotted_hue(mode):
    """ "Other" must not be confusable with a real keystone."""
    for k in P.KEYSTONE_SLOT:
        assert dE(P.keystone_color(k, mode), P.NEUTRAL[mode]) >= NORMAL_VISION_FLOOR


# --- paint: concentric rings --------------------------------------------------
def test_single_keystone_is_one_band():
    p = P.track_paint(sol("House", House=1.0))
    assert len(p["rings"]) == 1
    assert p["rings"][0]["frac"] == pytest.approx(1.0)


def test_second_keystone_becomes_a_ring_keeping_both_colours_pure():
    p = P.track_paint(sol("House", "Trance", House=0.6, Trance=0.4))
    assert [r["keystone"] for r in p["rings"]] == ["House", "Trance"]
    # the whole point: neither colour is mixed into the other
    assert p["rings"][1]["color"] == P.keystone_color("Trance")
    assert p["rings"][0]["color"] != p["rings"][1]["color"]


def test_keystone_is_always_the_innermost_band():
    p = P.track_paint(sol("House", "Trance", House=0.45, Trance=0.55))
    assert p["rings"][0]["keystone"] == "House"  # the label's keystone leads
    assert p["color"] == p["rings"][0]["color"]


def test_band_widths_track_the_shares():
    even = P.track_paint(sol("House", "Trance", House=0.5, Trance=0.5))
    lean = P.track_paint(sol("House", "Trance", House=0.8, Trance=0.2))
    assert lean["rings"][0]["frac"] > even["rings"][0]["frac"]


@pytest.mark.parametrize(
    "shares",
    [
        {"House": 0.5, "Trance": 0.5},
        {"House": 0.95, "Trance": 0.05},
        {"House": 0.6, "Trance": 0.25, "Techno": 0.15},
    ],
)
def test_bands_always_fill_the_radius(shares):
    p = P.track_paint(sol(*list(shares), **shares), max_rings=3)
    assert sum(r["frac"] for r in p["rings"]) == pytest.approx(1.0, abs=0.005)


def test_a_tiny_minority_still_gets_a_visible_band():
    """A 95/5 split must not render its minority as an invisible hairline."""
    p = P.track_paint(sol("House", "Trance", House=0.80, Trance=0.20))
    assert len(p["rings"]) == 2
    assert p["rings"][1]["frac"] >= P._MIN_BAND * 0.9


def test_share_below_the_ring_floor_gets_no_band():
    p = P.track_paint(sol("House", "Trance", House=0.93, Trance=0.07))
    assert len(p["rings"]) == 1


def test_two_unslotted_keystones_merge_instead_of_ringing_grey_on_grey():
    """Both bands would be the neutral -- a grey ring on a grey disc looks
    deliberate but says nothing."""
    p = P.track_paint(sol("Electro", "Disco", Electro=0.6, Disco=0.4))
    assert not (set(("Electro", "Disco")) & set(P.KEYSTONE_SLOT))  # premise
    assert len(p["rings"]) == 1


def test_one_unslotted_keystone_still_rings():
    p = P.track_paint(sol("House", "Electro", House=0.6, Electro=0.4))
    assert len(p["rings"]) == 2
    assert dE(p["rings"][0]["color"], p["rings"][1]["color"]) >= NORMAL_VISION_FLOOR


def test_every_electronic_family_owns_a_hue():
    """The allocation floor exists so a small family isn't left colourless --
    Chill and Experimental are 2% of today's library and will grow."""
    from vibenative import keystone as K

    slotted_families = {K.family_of(k) for k in P.KEYSTONE_SLOT}
    electronic = set(K.FAMILIES)
    assert electronic - slotted_families == set()
    assert K.OTHER_FAMILY not in slotted_families  # non-electronic never gets one


def test_family_lead_is_slotted_for_every_family():
    for family, lead in P.FAMILY_LEAD.items():
        assert lead in P.KEYSTONE_SLOT, f"{family} lead {lead} has no hue"


def test_max_rings_is_honoured():
    shares = {"House": 0.5, "Trance": 0.3, "Techno": 0.2}
    assert len(P.track_paint(sol(*shares, **shares), max_rings=2)["rings"]) == 2
    assert len(P.track_paint(sol(*shares, **shares), max_rings=3)["rings"]) == 3


# --- edges --------------------------------------------------------------------
def test_edge_shifts_between_the_two_keystones():
    e = P.edge_paint(sol("House", House=1.0), sol("Techno", Techno=1.0))
    assert e["from"] == P.keystone_color("House")
    assert e["to"] == P.keystone_color("Techno")
    assert e["solid"] is False


def test_edge_between_same_keystone_is_one_colour():
    e = P.edge_paint(sol("House", House=1.0), sol("House", House=1.0))
    assert e["solid"] is True and e["from"] == e["to"]


def test_edge_endpoints_match_the_nodes_they_touch():
    """A link only reads as a hue shift if each end matches the node it joins.
    The node's innermost band is a subgenre *shade*, so compare keystone hues."""
    a, b = sol("Dubstep", Dubstep=1.0), sol("Trance", Trance=1.0)
    e = P.edge_paint(a, b)
    assert e["from"] == P.keystone_color("Dubstep")
    assert e["to"] == P.keystone_color("Trance")
    # and each endpoint stays within its node's family rather than drifting
    assert dE(e["from"], P.track_paint(a)["color"]) < NORMAL_VISION_FLOOR


def test_edge_survives_a_missing_classification():
    e = P.edge_paint(None, sol("House", House=1.0))
    assert e["from"] == P.NEUTRAL["dark"]


def test_unknown_keystone_gets_the_neutral():
    assert P.keystone_color("Sea Shanty", "dark") == P.NEUTRAL["dark"]


def test_no_classification_no_paint():
    assert P.track_paint(None) is None
    assert P.track_paint({}) is None
    assert P.track_paint({"keystones": []}) is None


# --- subgenre shading ---------------------------------------------------------
def test_subgenre_shades_are_deterministic():
    a = P.subgenre_shade("House", "Deep House", "dark")
    b = P.subgenre_shade("House", "Deep House", "dark")
    assert a == b


def test_subgenre_shades_differ_within_a_keystone():
    shades = {
        P.subgenre_shade("House", s, "dark")
        for s in ("Deep House", "Tech House", "Bassline", "Speed Garage")
    }
    assert len(shades) > 1


def test_subgenre_shade_stays_in_its_family():
    """A shade must not drift so far it reads as a different keystone."""
    own = P.keystone_color("House", "dark")
    for s in ("Deep House", "Tech House", "Bassline", "Progressive House"):
        shade = P.subgenre_shade("House", s, "dark")
        nearest = min((dE(shade, P.keystone_color(k, "dark")), k) for k in P.KEYSTONE_SLOT)
        assert nearest[1] == "House", f"{s} drifted toward {nearest[1]}"
        assert dE(shade, own) < NORMAL_VISION_FLOOR


# --- css ----------------------------------------------------------------------
def test_css_shapes():
    assert P.css_for(P.track_paint(sol("House", House=1.0))).startswith("#")
    rings = P.css_for(P.track_paint(sol("House", "Trance", House=0.6, Trance=0.4)))
    assert rings.startswith("radial-gradient(circle,")
    # hard stops, so the swatch shows bands rather than a smear
    assert rings.count("%") == 4
    assert P.css_for(None) == "transparent"
    assert P.css_for({"rings": []}) == "transparent"


def test_legend_covers_every_slot_plus_other():
    leg = P.legend("dark")
    assert [e["keystone"] for e in leg][-1] == "Other"
    assert len(leg) == len(P.KEYSTONE_SLOT) + 1
    assert len({e["color"] for e in leg}) == len(leg)
