"""Manual weight adjustments: nudge a track's genre blend instead of replacing it.

A manual override answers "what is this track" with a single word, and in doing
so discards everything the model got right. A track reading Techno 66% / House
17% / Tech Trance 16% is *mostly* right -- overriding it to "House" throws away
the two-thirds that was correct along with the third that wasn't.

This adjusts instead. Each genre in the read carries a **step** -- an integer you
raise or lower -- and the step scales that genre's score before the blend is
renormalised. So you can say "this is a *very* house track" by pushing House up,
or "that Tech Trance reading is wrong" by pushing it down, without flattening
everything else to zero.

**Steps are stored, multipliers are computed.** The step is your judgement ("I
said this was strongly house"); the multiplier is this module's interpretation of
it. Storing multipliers would mean that retuning the curve silently rewrites what
you meant, so ``STEP_SCALE`` can change and every past adjustment keeps its
intent.

A genre that isn't in the model's read at all can still be raised: it enters at a
fraction of the track's total weight rather than at zero, because a multiplier
applied to nothing stays nothing. That's how you add a genre the model missed
entirely.

Adjustments *bend* a read; they don't overrule it. Pushing a genre to +3 on a
track the model called 90% something else lifts it to a strong second, not to
first -- if you disagree with a read that confident, an override is the honest
tool. That ceiling is deliberate: it keeps a step from meaning "and also discard
the analysis".
"""

# Multiplier per step, tuned against a real read rather than picked: on a track
# reading Techno 66% / House 17% / Tech Trance 16%, pushing House to +3 ("very
# house") has to actually make it the track's identity. At 1.6x it reached only
# 45.8% against Techno's 43.6% -- technically ahead, but nobody would call that
# "very house". 1.9x puts it clearly in front while +1 stays a nudge.
STEP_SCALE = 1.9

# How far a step can be pushed. Beyond +/-3 the curve stops meaning anything
# finer than "yes" or "no", which is override territory.
MAX_STEP = 3

# A genre the model never read enters relative to the track's total weight, not
# at a fixed score. An absolute floor made "moderately tech house" land at 4% on
# a confident track and 30% on an uncertain one -- the same words meaning
# different things depending on how sure the model happened to be. As a fraction
# of the mass being renormalised, a step means the same thing everywhere.
#
# Sized so the *result* matches the word, since the step's multiplier lands on
# top of it: introducing a genre at "slightly more" reads ~15%, "moderately"
# ~25%, "very" ~39%. At 0.22 a "moderately" entry arrived at 44% -- louder than
# anything the model actually heard, off one press.
ENTRY_FRACTION = 0.09

# Human labels for the steps, so the UI and the API agree on what a number means.
STEP_WORDS = {
    -3: "not at all",
    -2: "barely",
    -1: "slightly less",
    0: "as read",
    1: "slightly more",
    2: "moderately",
    3: "very",
}


def clamp_step(v):
    try:
        return max(-MAX_STEP, min(MAX_STEP, int(v)))
    except (TypeError, ValueError):
        return 0


def multiplier(step):
    """The factor a step applies. 0 is identity, so an unadjusted genre is
    untouched and a track with no adjustments reads exactly as analysed."""
    return STEP_SCALE ** clamp_step(step)


def describe(step):
    return STEP_WORDS.get(clamp_step(step), "as read")


def apply(entries, steps, topk=8):
    """Apply per-genre steps to a ranked style read.

    ``entries`` is ``[{"style", "score"}, ...]`` -- salience or flat styles.
    ``steps`` is ``{style: int}``. Returns a new ranked list, renormalised so the
    scores still read as shares of one.

    Genres named in ``steps`` but absent from the read are introduced at
    ``ENTRY_FRACTION`` of the track's total weight before scaling, so "the model
    missed this entirely" is expressible. Only *raised* genres are introduced --
    lowering something that isn't there is already true, and adding it just to
    shrink it would put a genre on the track that nobody claimed was present.
    """
    steps = {k: clamp_step(v) for k, v in (steps or {}).items() if clamp_step(v) != 0}
    scored = {}
    for e in entries or []:
        style = (e or {}).get("style")
        if not style:
            continue
        try:
            scored[style] = max(0.0, float(e.get("score") or 0))
        except (TypeError, ValueError):
            continue
    # Relative to the total, not the top reading. Scaling off the top looked
    # proportional but wasn't: the result is renormalised against a sum that also
    # varies, so "moderately" landed at 43% on a confident track and 30% on an
    # unsure one. Against the sum, a step means the same thing everywhere.
    mass = sum(scored.values())
    entry = mass * ENTRY_FRACTION
    for style, step in steps.items():
        # The floor applies to anything the model didn't meaningfully hear, not
        # only to what it never listed. "Moderately tech house" on a track
        # carrying Tech House at 0.2% multiplied out to 0.6% -- the press looked
        # broken, for no reason the user could see. A trace reading and no
        # reading are the same statement, so they get the same treatment.
        if step > 0 and scored.get(style, 0.0) < entry:
            scored[style] = entry

    adjusted = {s: v * multiplier(steps.get(s, 0)) for s, v in scored.items()}
    total = sum(adjusted.values())
    if total <= 0:
        return []
    ranked = sorted(adjusted.items(), key=lambda kv: -kv[1])[:topk]
    keep = sum(v for _, v in ranked) or 1.0
    out = []
    for s, v in ranked:
        entry = {"style": s, "score": round(v / keep, 4)}
        if s in steps:
            # Carried through so the UI can show which readings you moved, and
            # by how much, rather than only the result.
            entry["step"] = steps[s]
        out.append(entry)
    return out


def read_with_steps(payload, topk=8):
    """The track's blend after its stored adjustments, or None if it has none.

    Reads the same source ``_dominant_style`` prefers, so an adjustment nudges
    whatever the track currently reads as rather than resurrecting an older
    analysis underneath it.
    """
    steps = (payload or {}).get("weights") or {}
    if not steps:
        return None
    base = (
        ((payload.get("relabel") or {}).get("styles"))
        or payload.get("salience")
        or payload.get("styles")
        or []
    )
    out = apply(base, steps, topk=topk)
    return out or None
