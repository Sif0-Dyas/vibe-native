"""Per-keystone genre profiles: the conventional BPM range and a character
sketch for each keystone. Reference data; genres.py measures the library
against it. Moved verbatim from genres.py.
"""

# Conventional tempo ranges and a one-line character sketch per keystone.
#
# The BPM figures are the widely published DJ-reference ranges (the same numbers
# genre BPM charts converge on); they describe the genre in general, NOT this
# library. Where a keystone covers several conventional genres the range spans
# them: Hard Dance holds hardstyle (150-160) and hardcore (160-200), so it reads
# 150-200. Non-electronic keystones get no canonical range -- tempo isn't how
# those genres are defined, and inventing a number would be worse than a blank.
PROFILES = {
    "House": {
        "bpm": (115, 132),
        "blurb": "Four-on-the-floor at a walking pulse. The broadest keystone here -- "
        "deep, tech, progressive, electro and bassline all sit under it.",
        "signature": "4/4",
        "feel": "four-on-the-floor",
    },
    "Techno": {
        "bpm": (130, 150),
        "blurb": "Relentless, machine-forward, loop-driven. Darker and more rigid than "
        "house at a similar or higher tempo.",
        "signature": "4/4",
        "feel": "four-on-the-floor",
    },
    "Trance": {
        "bpm": (128, 150),
        "blurb": "Long builds and melodic breakdowns over a driving kick. Tech trance "
        "leans harder and faster; psy-trance runs its own rhythmic logic.",
        "signature": "4/4",
        "feel": "four-on-the-floor",
    },
    "Dubstep": {
        "bpm": (138, 142),
        "blurb": "Halftime feel over a 140 grid -- the kick-snare lands at half the "
        "written tempo. Sound-design led, bass as the lead instrument.",
        "signature": "4/4",
        "feel": "halftime over a 140 grid",
    },
    "Drum n Bass": {
        "bpm": (160, 180),
        "blurb": "Fast breakbeats with a sub-bass line underneath. Jungle is its "
        "ancestor and rolls up here.",
        "signature": "4/4",
        "feel": "breakbeat",
    },
    "Halftime": {
        "bpm": (140, 175),
        "blurb": "Written at DnB tempo but felt at half speed -- the drums sit where "
        "dubstep's would while the grid stays fast. Sits between its two parents.",
        "signature": "4/4",
        "feel": "halftime over a DnB grid",
    },
    "Hard Dance": {
        "bpm": (150, 200),
        "blurb": "Distorted kick as the lead. Hardstyle at the lower end, hardcore and "
        "gabber climbing from there.",
        "signature": "4/4",
        "feel": "four-on-the-floor, distorted kick",
    },
    "Breakbeat": {
        "bpm": (120, 140),
        "blurb": "Syncopated broken drums instead of four-on-the-floor, at house tempo.",
        "signature": "4/4",
        "feel": "broken beat",
    },
    "Electro": {
        "bpm": (110, 135),
        "blurb": "Machine funk built on drum-machine syncopation -- electro proper, "
        "not electro house.",
        "signature": "4/4",
        "feel": "syncopated drum machine",
    },
    "Trap": {
        "bpm": (140, 160),
        "blurb": "Halftime feel over fast hi-hats, 808 sub. Written high, felt slow -- "
        "so it often reads at half tempo.",
        "signature": "4/4",
        "feel": "halftime, fast hi-hats",
    },
    "Downtempo": {
        "bpm": (80, 115),
        "blurb": "Slow and groove-led rather than dancefloor-driven. Trip hop, "
        "chillwave, synthwave and vaporwave land here.",
        "signature": "4/4",
        "feel": "loose, groove-led",
    },
    "Ambient": {
        "bpm": (60, 120),
        "blurb": "Texture over rhythm; often effectively beatless, which makes any "
        "detected tempo unreliable by nature.",
        "signature": "free",
        "feel": "often beatless",
    },
    "Industrial": {
        "bpm": (110, 140),
        "blurb": "Abrasive, mechanical, noise-adjacent. EBM and rhythmic noise included.",
        "signature": "4/4",
        "feel": "mechanical, four-on-the-floor or broken",
    },
    "Experimental": {
        "bpm": (90, 160),
        "blurb": "IDM, glitch and abstract -- defined by refusing a fixed template, so "
        "the tempo range is wide and weakly meaningful.",
        "signature": "varies",
        "feel": "no fixed template",
    },
    "Disco": {
        "bpm": (100, 125),
        "blurb": "Live-feel four-on-the-floor with strings and funk guitar; nu-disco "
        "and italo carry it forward.",
        "signature": "4/4",
        "feel": "four-on-the-floor, live feel",
    },
    "Metal": {
        "bpm": None,
        "blurb": "Distorted guitar, the full span from doom to grindcore.",
        "signature": "4/4",
        "feel": "varies widely",
    },
    "Punk": {
        "bpm": None,
        "blurb": "Short, fast, raw guitar music; hardcore and emo included.",
        "signature": "4/4",
        "feel": "fast backbeat",
    },
    "Rock": {
        "bpm": None,
        "blurb": "Guitar-led music that isn't metal or punk.",
        "signature": "4/4",
        "feel": "backbeat",
    },
    "Hip Hop": {
        "bpm": None,
        "blurb": "Rap over sampled or programmed beats.",
        "signature": "4/4",
        "feel": "backbeat, sampled",
    },
}
