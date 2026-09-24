"""Preset colour schemes for the keystone palette.

``palette.py`` solves one palette against this library's real fusion pairs and
guards it with separation tests. That is the right default and the wrong
straitjacket: which colour House is has no correct answer, and a scheme that
looks right to the person reading the map beats one that measures well.

So this offers a menu. A preset is one line in the taxonomy overlay
(``"palette": "neon"``), per-genre colours override it, and switching back is a
click -- nothing here is destructive, which is what makes it safe to hand over.

**Presets are measured, not assumed.** Each carries the worst pairwise OKLab ΔE
it achieves, so the picker can say "these two will look similar" instead of
implying every scheme separates equally.

Measured *against the default*, not against an absolute floor. The obvious
framing -- pass/fail at the ΔE 15 readability line -- was tried and thrown away
because nothing passes, including the solved default: ``palette.py`` is explicit
that past three colours no arrangement separates all pairs, and its ΔE 19.3
figure covers the pairs the library actually produces, not all 28. A flag that
failed the shipped palette would be measuring the wrong thing loudly. So the
number shown is the worst all-pairs ΔE and the verdict is relative: tighter than
the default, comparable, or looser.

Nothing is blocked either way -- ``sunset`` and ``ice`` trade separation for mood
on purpose, and that is a legitimate thing to want on a map whose labels already
carry identity.

Two kinds:

* **fixed** -- a hand-authored list, used in order. ``studio`` is the solved
  default; ``okabe-ito`` is the standard colour-vision-deficiency-safe eight.
* **ramp** -- generated in OKLCH: hues spread over an arc, at one or two
  lightness levels. Generated ones scale to however many keystones exist.

**Why two lightness levels.** The first version of this spread sixteen hues
evenly at one lightness and measured a worst pair of ΔE 5.0 -- unreadable. That
is not a tuning miss, it is the same ceiling ``palette.py`` documents: at a fixed
lightness you are packing points into a chroma-limited disc, and about eight fit
before they collide. Splitting the same hues across two lightness levels doubles
the usable count, because two genres sharing a hue are then separated by
lightness instead. The eight-slot limit is a property of *fixed lightness*, not
of hand-picking.
"""

import math

# Below this OKLab ΔE (x100) two colours are hard to tell apart even with full
# colour vision. Same floor palette.py was validated against.
READABLE = 15.0

# Evenly spaced hues stop separating past about this many at one lightness --
# measured, not assumed: sixteen on one level came out at a worst pair of ΔE 5.0.
# It is the same eight ``palette.py`` arrived at by hand.
HUES_PER_LEVEL = 8


# --- OKLCH -> sRGB -----------------------------------------------------------
def _oklab_to_linear(li, aa, bb):
    l_ = li + 0.3963377774 * aa + 0.2158037573 * bb
    m_ = li - 0.1055613458 * aa - 0.0638541728 * bb
    s_ = li - 0.0894841775 * aa - 1.2914855480 * bb
    lo, mo, so = l_**3, m_**3, s_**3
    return (
        4.0767416621 * lo - 3.3077115913 * mo + 0.2309699292 * so,
        -1.2684380046 * lo + 2.6097574011 * mo - 0.3413193965 * so,
        -0.0041960863 * lo - 0.7034186147 * mo + 1.7076147010 * so,
    )


def _gamma(c):
    c = max(0.0, min(1.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def oklch_hex(li, chroma, hue_deg):
    """One OKLCH colour as ``#rrggbb``, chroma reduced until it fits in sRGB.

    Clamping the RGB channels instead would be simpler and wrong: it shifts hue,
    so an evenly spaced ramp comes out visibly uneven wherever the gamut is
    narrow (blues and greens especially). Pulling chroma in keeps the hue the
    ramp asked for and only costs saturation, which is the parameter nobody is
    counting.
    """
    h = math.radians(hue_deg)
    lo, hi = 0.0, max(0.0, chroma)
    for _ in range(24):
        mid = (lo + hi) / 2
        rgb = _oklab_to_linear(li, mid * math.cos(h), mid * math.sin(h))
        if all(-1e-4 <= c <= 1 + 1e-4 for c in rgb):
            lo = mid
        else:
            hi = mid
    rgb = _oklab_to_linear(li, lo * math.cos(h), lo * math.sin(h))
    return "#" + "".join(f"{round(_gamma(c) * 255):02x}" for c in rgb)


def _oklab_of(hx):
    """OKLab for a hex colour, for measuring separation."""

    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    h = hx.lstrip("#")
    r, g, b = (lin(int(h[i : i + 2], 16)) for i in (0, 2, 4))
    li = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    li, m, s = (x ** (1 / 3) if x > 0 else -((-x) ** (1 / 3)) for x in (li, m, s))
    return (
        0.2104542553 * li + 0.7936177850 * m - 0.0040720468 * s,
        1.9779984951 * li - 2.4285922050 * m + 0.4505937099 * s,
        0.0259040371 * li + 0.7827717662 * m - 0.8086757660 * s,
    )


def delta_e(a, b):
    return 100 * math.dist(_oklab_of(a), _oklab_of(b))


# --- the presets --------------------------------------------------------------
# Okabe-Ito, the standard eight-colour set designed to stay distinguishable
# under the common colour-vision deficiencies. Included as-published rather than
# re-tuned per mode -- retuning it is how you quietly lose the property it is
# here for.
_OKABE_ITO = [
    "#0072b2",
    "#e69f00",
    "#009e73",
    "#f0e442",
    "#cc79a7",
    "#56b4e9",
    "#d55e00",
    "#000000",
]
_OKABE_ITO_DARK = [
    "#3d9ae0",
    "#e69f00",
    "#00b386",
    "#f0e442",
    "#e08bb8",
    "#7cc7f0",
    "#f0700a",
    "#cfcfcf",  # black is invisible on a dark map; the CVD-safe neutral instead
]

PRESETS = {
    "studio": {
        "label": "Studio",
        "blurb": (
            "The solved default. Eight hues chosen against this library's real "
            "fusion pairs, so the genres that actually blend are the ones held "
            "furthest apart. Everything past the eight takes the neutral grey."
        ),
        "kind": "builtin",
    },
    "spectrum": {
        "label": "Spectrum",
        "blurb": (
            "An even hue wheel across every genre, so nothing is grey and the "
            "spacing is as good as the count allows. The more genres you have, "
            "the closer neighbours sit -- that's arithmetic, not a flaw."
        ),
        "kind": "ramp",
        "arc": (0, 360),
        "light": (0.58, 0.16, 0.80),
        "dark": (0.70, 0.15, 0.48),
    },
    "okabe-ito": {
        "label": "Okabe–Ito",
        "blurb": (
            "The standard colour-vision-deficiency-safe eight. Pick this if red "
            "and green are hard to tell apart — it is the only preset here "
            "designed for that rather than measured after the fact."
        ),
        "kind": "fixed",
        "light": _OKABE_ITO,
        "dark": _OKABE_ITO_DARK,
    },
    "neon": {
        "label": "Neon",
        "blurb": (
            "Full hue wheel pushed to maximum chroma. Loud and high-contrast on "
            "a dark map; in light mode it gets shrill, so the lightness drops to "
            "compensate."
        ),
        "kind": "ramp",
        "arc": (0, 360),
        "light": (0.52, 0.24, 0.76),
        "dark": (0.74, 0.22, 0.50),
    },
    "pastel": {
        "label": "Pastel",
        "blurb": (
            "The same even spacing at low chroma. Easier to look at for a long "
            "session, and separation drops with the saturation — hues stay "
            "correct, they just shout less."
        ),
        "kind": "ramp",
        "arc": (0, 360),
        "light": (0.72, 0.08, 0.50),
        "dark": (0.78, 0.07, 0.54),
    },
    "sunset": {
        "label": "Sunset",
        "blurb": (
            "Reds through oranges to yellow. A deliberately narrow arc: it looks "
            "like one warm family, which is the point, and neighbouring genres "
            "will be hard to tell apart. Mood first."
        ),
        "kind": "ramp",
        "arc": (20, 110),
        "light": (0.62, 0.16, 0.40),
        "dark": (0.72, 0.15, 0.46),
    },
    "ice": {
        "label": "Ice",
        "blurb": (
            "Cyan through blue to violet, the cool counterpart to Sunset. Same "
            "trade: one coherent family, neighbours close together."
        ),
        "kind": "ramp",
        "arc": (190, 300),
        "light": (0.60, 0.14, 0.38),
        "dark": (0.72, 0.14, 0.44),
    },
}

DEFAULT = "studio"


def names():
    return list(PRESETS)


def keystone_order():
    """The keystones a preset assigns colour to, in a fixed order.

    Fixed on purpose: a preset that reordered itself as the library grew would
    repaint the whole map every time a new genre appeared, and colour is supposed
    to follow the entity. Same reasoning as ``palette.KEYSTONE_SLOT``.
    """
    from . import keystone as K

    return [k for fam in K.FAMILY_ORDER for k in (K.FAMILIES.get(fam) or [])]


def colors_for(name, mode="dark", keystones=None):
    """``{keystone: hex}`` for a preset, or ``{}`` for the built-in default.

    An empty result means "fall through to palette.py", which is how ``studio``
    stays the solved assignment rather than a copy of it that could drift.
    """
    spec = PRESETS.get(name)
    if not spec or spec["kind"] == "builtin":
        return {}
    ks = list(keystones) if keystones is not None else keystone_order()
    if not ks:
        return {}
    if spec["kind"] == "fixed":
        ramp = spec.get(mode) or spec.get("dark") or []
        # A hand-authored list runs out. Recycling would put two keystones on the
        # same colour, which palette.py argues is worse than one being grey --
        # so the tail is simply left for the neutral to cover.
        return {k: ramp[i] for i, k in enumerate(ks) if i < len(ramp)}
    lo, hi = spec["arc"]
    light, chroma, light2 = spec.get(mode) or spec["dark"]
    n = len(ks)
    # Hues per lightness level. Capped at HUES_PER_LEVEL because that is roughly
    # where evenly spaced hues stop separating at a fixed lightness; past it the
    # ramp starts a second level rather than packing them tighter.
    per = min(n, HUES_PER_LEVEL) if n > HUES_PER_LEVEL else n
    out = {}
    for i, k in enumerate(ks):
        j = i % per
        # A full wheel wraps, so the last hue must not land back on the first;
        # a partial arc should reach its end, so it spans inclusively.
        frac = (j / per) if (hi - lo) >= 360 else (j / max(1, per - 1))
        out[k] = oklch_hex(light if i < per else light2, chroma, (lo + (hi - lo) * frac) % 360)
    return out


def _worst_pair(cols):
    vals = sorted(set(cols.values()))
    if len(vals) < 2:
        return None, 0
    worst, close = None, 0
    for i, a in enumerate(vals):
        for b in vals[i + 1 :]:
            d = delta_e(a, b)
            worst = d if worst is None else min(worst, d)
            if d < READABLE:
                close += 1
    return worst, close


def _default_colors(mode, keystones):
    from . import palette as P

    return {k: P.keystone_color(k, mode) for k in (keystones or keystone_order())}


def separation(name, mode="dark", keystones=None):
    """How well a preset separates, relative to the solved default.

    Reported, never enforced. The user asked for schemes they can change freely,
    so the honest move is to show what a choice costs and let them make it -- a
    picker that silently blocked ``sunset`` would be answering a question nobody
    asked.

    ``verdict`` compares to ``studio`` because an absolute pass/fail is not
    meaningful here: see the module docstring.
    """
    cols = colors_for(name, mode, keystones) or _default_colors(mode, keystones)
    worst, close = _worst_pair(cols)
    base, _ = _worst_pair(_default_colors(mode, keystones))
    verdict = "unknown"
    if worst is not None and base:
        ratio = worst / base
        verdict = "tighter" if ratio >= 1.15 else "looser" if ratio <= 0.85 else "comparable"
    return {
        "worst": None if worst is None else round(worst, 1),
        "close_pairs": close,
        "default_worst": None if base is None else round(base, 1),
        "verdict": verdict,
    }


def summarise(mode="dark"):
    """Every preset with its colours and its measured separation, for the picker."""
    ks = keystone_order()
    out = []
    for name, spec in PRESETS.items():
        cols = colors_for(name, mode, ks)
        if not cols:  # the built-in: show what it actually paints
            from . import palette as P

            cols = {k: P.keystone_color(k, mode) for k in ks}
        out.append(
            {
                "name": name,
                "label": spec["label"],
                "blurb": spec["blurb"],
                "colors": [{"keystone": k, "color": cols[k]} for k in ks if k in cols],
                "separation": separation(name, mode, ks),
            }
        )
    return out


def current():
    """The preset in force, from the taxonomy overlay."""
    from .taxonomy import load

    name = (load().get("palette") or "").strip()
    return name if name in PRESETS else DEFAULT


def apply(name):
    """Switch presets. Stores the *name*, not the colours it computes.

    Same reasoning as the weight steps: storing the output would freeze it, so a
    later fix to a ramp would never reach a library that had already chosen it,
    and there would be no way to tell a preset from sixteen hand-picked colours.
    Per-genre colours are left alone -- they are the exceptions on top.
    """
    from .taxonomy import patch

    if name not in PRESETS:
        raise ValueError(f"unknown palette {name!r}")
    patch({"palette": "" if name == DEFAULT else name})
    return current()
