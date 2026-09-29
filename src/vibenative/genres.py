"""Per-keystone genre profiles: what a genre *is*, and what it looks like here.

Backs the Genres view. Each profile carries two BPM ranges side by side and they
are deliberately not merged:

* **canonical** -- the tempo the genre conventionally runs at, a fixed reference.
* **observed** -- what this library's own analysed tracks actually measure.

Keeping both is the point. Where they disagree, the disagreement is the finding.
Drum n Bass is canonically 160-180 but 60% of the DnB here measures in the 80s,
because tempo detection resolves an octave down -- the same octave ambiguity the
engine's own validation allowed for ("within 2% *or an octave*"). A single
merged number would hide that; two numbers and a flag surface it.

Everything observed is computed from the library on demand -- no cached column,
no migration, and it re-reflects the moment a track is re-analysed or a keystone
mapping changes.
"""

import json
import statistics

from . import palette as P
from .repo import tracks as tracks_repo
from .taxonomy import classify as K
from .taxonomy import overlay
from .taxonomy import tables as T
from .taxonomy.profiles import PROFILES

# An observed median this far from the canonical band, by roughly a factor of
# two, means tempo was resolved an octave off rather than the genre being
# unusual. 1.7-2.3x brackets the real cases without catching genuine outliers.
_OCTAVE_LO, _OCTAVE_HI = 1.7, 2.3


def _octave_flag(observed_median, canonical):
    """Whether the observed tempo looks like a half/double-time misread."""
    if not observed_median or not canonical:
        return None
    lo, hi = canonical
    mid = (lo + hi) / 2
    if observed_median <= 0:
        return None
    if _OCTAVE_LO <= mid / observed_median <= _OCTAVE_HI:
        return "half"  # detected at half the conventional tempo
    if _OCTAVE_LO <= observed_median / mid <= _OCTAVE_HI:
        return "double"
    return None


def _rows():
    return tracks_repo.summary_rows()


def summarise(top_n=5, mode="dark"):
    """Build a profile for every keystone present in the library.

    Returns a list, largest keystone first::

        {"keystone": "House", "count": 662, "share": 0.348,
         "color": "#008300", "blurb": "...",
         "bpm": {"canonical": [115, 132],
                 "observed": {"p10": 120, "median": 125, "p90": 129,
                              "min": 80, "max": 738, "n": 662},
                 "octave_flag": None},
         "self_count": 210,
             -- tracks whose dominant read is plain "House", no subgenre,
         "subgenres": [{"style": "Progressive House", "count": 167}, ...],
             -- counts are TRACKS whose dominant subgenre is that style, so they
             plus self_count sum to at most the keystone's own count and agree
             with the map; the keystone's own name is never in this list,
         "top": [{"hash": ..., "title": ..., "share": 1.0}, ...]}

    ``top`` is the most *representative* tracks -- highest share of this
    keystone, tie-broken by how confident the underlying style read was, so a
    track that is 100% house on a strong read outranks one that is 100% house on
    a weak one.
    """
    # One taxonomy overlay for the whole pass: every track classified and
    # painted against the same file, and one stat() instead of one per lookup.
    with overlay.pinned():
        buckets = {}
        for h, title, filename, payload in _rows():
            try:
                p = json.loads(payload) if isinstance(payload, str) else (payload or {})
            except (TypeError, ValueError):
                continue
            cls = K.classify(p)
            if not cls:
                continue
            primary = cls["keystones"][0]
            b = buckets.setdefault(
                primary,
                {
                    "bpm": [],
                    "subgenres": {},
                    "tracks": [],
                    "count": 0,
                    # Per-subgenre tempo and tracks. A standalone archgenre (House,
                    # Techno, Trance) has exactly one keystone -- itself -- so its
                    # subgenres are the only genres it has to show, and a bare count is
                    # not enough to build a card from.
                    "sub_bpm": {},
                    "sub_tracks": {},
                },
            )
            b["count"] += 1
            bpm = p.get("bpm")
            if bpm:
                try:
                    b["bpm"].append(float(bpm))
                except (TypeError, ValueError):
                    pass
            # ONE subgenre per track: the strongest read within this keystone.
            #
            # This used to increment every subgenre a track read as, which is a
            # different quantity entirely -- "tracks that contain any Progressive
            # House" rather than "tracks that ARE Progressive House". Displayed
            # beside the keystone's track count it read as nonsense: House holds
            # 1,437 tracks and its top five subgenres summed to 3,380. It also
            # disagreed with the map legend, which has always counted the dominant
            # style, so the same label carried two different numbers in one app.
            #
            # cls["subgenres"] is ordered by score, so the first entry belonging to
            # this keystone is its dominant subgenre.
            s = K.dominant_subgenre(cls)
            if s:
                style = s["style"]
                b["subgenres"][style] = b["subgenres"].get(style, 0) + 1
                if bpm:
                    try:
                        b["sub_bpm"].setdefault(style, []).append(float(bpm))
                    except (TypeError, ValueError):
                        pass
                b["sub_tracks"].setdefault(style, []).append(
                    {
                        "hash": h,
                        "title": title or (filename or h[:8]),
                        "share": cls["shares"].get(primary, 0.0),
                        "confidence": round(float(s.get("score") or 0), 4),
                        "bpm": bpm,
                    }
                )
            lead = cls["subgenres"][0]["score"] if cls["subgenres"] else 0.0
            b["tracks"].append(
                {
                    "hash": h,
                    "title": title or (filename or h[:8]),
                    "share": cls["shares"].get(primary, 0.0),
                    "confidence": round(float(lead), 4),
                    "bpm": bpm,
                    "label": cls["label"],
                }
            )

        total = sum(b["count"] for b in buckets.values()) or 1
        out = []
        for name, b in sorted(buckets.items(), key=lambda kv: -kv[1]["count"]):
            meta = PROFILES.get(name, {})
            canonical = meta.get("bpm")
            obs = _bpm_stats(b["bpm"])
            b["tracks"].sort(key=lambda t: (-t["share"], -t["confidence"]))
            out.append(
                {
                    "keystone": name,
                    "family": K.family_of(name),
                    "count": b["count"],
                    # Tracks whose dominant read is the keystone itself -- plain
                    # "House", not any House subgenre. Reported here, not as a
                    # subgenre row: a genre is not a subgenre of itself, and
                    # every consumer of the list used to have to strip the
                    # self-named entry before "House > House" reached a screen.
                    "self_count": b["subgenres"].get(name, 0),
                    "share": round(b["count"] / total, 4),
                    "color": P.keystone_color(name, mode),
                    "slotted": name in P.KEYSTONE_SLOT,
                    "blurb": meta.get("blurb", ""),
                    # Signature is near-constant across electronic music -- almost
                    # everything here is 4/4 -- so `feel` is the field that actually
                    # separates these genres. Both are properties of the genre as
                    # conventionally played, NOT measured per track: the engine
                    # computes a single BPM and never locates beats or downbeats, so
                    # meter cannot be detected from what is stored.
                    "signature": meta.get("signature", ""),
                    "feel": meta.get("feel", ""),
                    "bpm": {
                        "canonical": list(canonical) if canonical else None,
                        "observed": obs,
                        "octave_flag": _octave_flag(obs.get("median") if obs else None, canonical),
                    },
                    "subgenres": [
                        _subgenre_profile(s, n, b, name, mode, top_n)
                        for s, n in sorted(b["subgenres"].items(), key=lambda kv: -kv[1])
                        if s != name
                    ],
                    "top": b["tracks"][:top_n],
                }
            )
        return out


def _subgenre_profile(style, count, bucket, keystone, mode, top_n):
    """One subgenre, carrying enough to render as a card rather than a chip.

    Deliberately thinner than a keystone profile. A subgenre has no entry in
    PROFILES, so there is no blurb, no canonical tempo and no conventional
    feel to state -- inventing them would be worse than leaving them out. What
    it does have is real: how many of your tracks are it, what tempo they
    actually run at, and which are the most representative.

    Colour comes from the parent keystone. The palette is solved for keystones
    only, and giving a subgenre its own hue would either collide with a
    neighbouring keystone or imply a distinction the palette never made.
    """
    tracks = sorted(
        bucket["sub_tracks"].get(style, []),
        key=lambda t: (-t["share"], -t["confidence"]),
    )
    return {
        "style": style,
        "count": count,
        "keystone": keystone,
        "color": P.keystone_color(keystone, mode),
        "bpm": {
            "canonical": None,
            "observed": _bpm_stats(bucket["sub_bpm"].get(style, [])),
            "octave_flag": None,
        },
        "top": tracks[:top_n],
    }


def _bpm_stats(values):
    """Robust summary of a keystone's tempos. p10/p90 rather than min/max as the
    headline, because a single 738 BPM misread shouldn't define the range."""
    vals = sorted(v for v in values if v and v > 0)
    if not vals:
        return None
    stats = {
        "n": len(vals),
        "median": round(statistics.median(vals)),
        "min": round(vals[0]),
        "max": round(vals[-1]),
    }
    if len(vals) >= 10:
        q = statistics.quantiles(vals, n=10)
        stats["p10"], stats["p90"] = round(q[0]), round(q[8])
    else:
        stats["p10"], stats["p90"] = stats["min"], stats["max"]
    return stats


def one(keystone, top_n=5, mode="dark"):
    """A single keystone's profile, or None if it isn't present in the library."""
    for prof in summarise(top_n=top_n, mode=mode):
        if prof["keystone"] == keystone:
            return prof
    return None


def by_family(top_n=5, mode="dark"):
    """Profiles grouped into the family tier, in FAMILY_ORDER.

    This is the shape the Genres view wants: families are the headings you scan
    first when sorting a pile of unknown files, keystones the rows inside them.
    Families with nothing in the library are omitted rather than shown empty.
    """
    profiles = summarise(top_n=top_n, mode=mode)
    grouped = {}
    for prof in profiles:
        grouped.setdefault(prof["family"], []).append(prof)
    total = sum(p["count"] for p in profiles) or 1
    return [
        {
            "family": fam,
            "count": sum(p["count"] for p in grouped[fam]),
            "share": round(sum(p["count"] for p in grouped[fam]) / total, 4),
            "keystones": grouped[fam],
        }
        for fam in T.FAMILY_ORDER
        if fam in grouped
    ]
