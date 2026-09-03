"""Tests for manual weight adjustments.

The point of this feature is that it *preserves* the model's read while bending
it, so most of these check what stays true rather than what changes: an
unadjusted genre keeps its relative standing, the analysed read underneath is
never rewritten, and clearing the adjustments restores exactly what the model
said.

The tuned constants are asserted against the real read they were tuned on --
Techno 66 / House 17 / Tech Trance 16 -- so a future retune has to stay
defensible against the case that motivated it.
"""

import pytest

from vibenative import weights as W

# The read that motivated the tuning, from a real track.
REAL = [
    {"style": "Techno", "score": 0.656},
    {"style": "House", "score": 0.168},
    {"style": "Tech Trance", "score": 0.155},
    {"style": "Electro House", "score": 0.005},
]


def by_style(entries):
    return {e["style"]: e["score"] for e in entries}


# --- the core promise ---------------------------------------------------------
def test_no_adjustments_leaves_the_read_alone():
    """A track nobody has touched must read exactly as analysed."""
    out = by_style(W.apply(REAL, {}))
    assert out["Techno"] == pytest.approx(0.656 / 0.984, abs=0.002)
    assert list(out) == ["Techno", "House", "Tech Trance", "Electro House"]


def test_a_zero_step_is_the_same_as_no_step():
    assert W.apply(REAL, {"House": 0}) == W.apply(REAL, {})


def test_raising_one_genre_does_not_reorder_the_others():
    """Only the adjusted genre moves; everything else keeps its relative order,
    which is the whole difference from an override."""
    out = W.apply(REAL, {"House": 3})
    rest = [e["style"] for e in out if e["style"] != "House"]
    assert rest == ["Techno", "Tech Trance", "Electro House"]


def test_scores_always_form_a_blend():
    for steps in ({}, {"House": 3}, {"Tech Trance": -3}, {"House": 2, "Tech House": 2}):
        total = sum(e["score"] for e in W.apply(REAL, steps))
        assert total == pytest.approx(1.0, abs=0.005)


# --- the tuning, against the case it was tuned on ------------------------------
def test_very_house_actually_makes_it_house():
    """At the first curve this reached 45.8% against Techno's 43.6% -- ahead, but
    nobody would call that "very house"."""
    out = by_style(W.apply(REAL, {"House": 3}))
    assert out["House"] > 0.5
    assert out["House"] > out["Techno"] * 1.5


def test_a_single_step_is_only_a_nudge():
    """+1 must not flip the track, or the scale has no low end."""
    out = by_style(W.apply(REAL, {"House": 1}))
    assert out["Techno"] > out["House"]


def test_pushing_a_misread_down_suppresses_without_erasing():
    out = by_style(W.apply(REAL, {"Tech Trance": -3}))
    assert 0 < out["Tech Trance"] < 0.05
    assert out["Techno"] > 0.7  # the rest absorbs the freed weight


def test_a_genre_the_model_missed_enters_at_the_strength_you_named():
    """ "Moderately" has to read as moderate. Sized before the multiplier, a +2
    entry arrived at 44% -- louder than anything the model actually heard."""
    out = by_style(W.apply(REAL, {"Tech House": 2}))
    assert 0.18 < out["Tech House"] < 0.32
    assert out["Techno"] > out["Tech House"]  # still the track's main read


def test_introduced_strength_tracks_the_step():
    at = lambda k: by_style(W.apply(REAL, {"Tech House": k}))["Tech House"]  # noqa: E731
    assert at(1) < at(2) < at(3)
    assert at(1) < 0.2  # a nudge
    assert at(3) > 0.3  # a real claim


def test_introducing_is_proportional_to_the_track_not_absolute():
    """An absolute floor made the same words mean different things depending on
    how confident the model happened to be."""
    confident = [{"style": "Techno", "score": 0.95}, {"style": "House", "score": 0.05}]
    unsure = [{"style": "Techno", "score": 0.35}, {"style": "House", "score": 0.30}]
    a = by_style(W.apply(confident, {"Tech House": 2}))["Tech House"]
    b = by_style(W.apply(unsure, {"Tech House": 2}))["Tech House"]
    assert a == pytest.approx(b, abs=0.06)


def test_a_trace_reading_is_treated_as_absent():
    """The model listing Tech House at 0.2% is not meaningfully different from
    not listing it. Multiplying the trace instead made "moderately tech house"
    land at 0.6% -- a press that looked broken, for no visible reason."""
    trace = REAL + [{"style": "Tech House", "score": 0.002}]
    on_trace = by_style(W.apply(trace, {"Tech House": 2}))["Tech House"]
    on_absent = by_style(W.apply(REAL, {"Tech House": 2}))["Tech House"]
    assert on_trace == pytest.approx(on_absent, abs=0.01)


def test_a_genre_the_model_did_hear_is_not_dragged_down_to_the_floor():
    """The floor lifts what was never heard; it must not flatten a real reading."""
    out = by_style(W.apply(REAL, {"Techno": 1}))
    assert out["Techno"] > 0.6


def test_lowering_an_absent_genre_does_not_invent_it():
    """Adding a genre just to shrink it would put it on the track."""
    assert "Tech House" not in by_style(W.apply(REAL, {"Tech House": -3}))


# --- steps are the stored form ------------------------------------------------
def test_steps_are_clamped_and_junk_is_neutral():
    assert W.clamp_step(99) == W.MAX_STEP
    assert W.clamp_step(-99) == -W.MAX_STEP
    assert W.clamp_step("banana") == 0
    assert W.clamp_step(None) == 0


def test_the_step_is_reported_back_not_the_multiplier():
    """Storing multipliers would mean retuning the curve silently rewrote what
    the user meant."""
    out = {e["style"]: e for e in W.apply(REAL, {"House": 2})}
    assert out["House"]["step"] == 2
    assert "step" not in out["Techno"]


def test_step_zero_is_identity_by_construction():
    assert W.multiplier(0) == 1.0


# --- reading a payload --------------------------------------------------------
def test_read_with_steps_returns_none_when_untouched():
    assert W.read_with_steps({"salience": REAL}) is None
    assert W.read_with_steps({}) is None


def test_read_with_steps_nudges_the_read_that_is_actually_in_effect():
    """It must bend the current read, not resurrect an older analysis under it."""
    payload = {
        "salience": [{"style": "Techno", "score": 1.0}],
        "relabel": {"styles": [{"style": "House", "score": 1.0}]},
        "weights": {"Trance": 3},
    }
    styles = [e["style"] for e in W.read_with_steps(payload)]
    assert "House" in styles and "Techno" not in styles


def test_adjustments_outrank_automatic_reads_but_not_an_override():
    from vibenative.routes._shared import _dominant_style

    base = {"salience": REAL}
    assert _dominant_style(base)[0] == "Techno"
    adjusted = dict(base, weights={"House": 3})
    assert _dominant_style(adjusted)[0] == "House"
    assert _dominant_style(dict(adjusted, override="Trance"))[0] == "Trance"


def test_keystone_follows_the_adjustment_too():
    """The map and the label must agree about a track you just adjusted -- and
    the keystone has to roll up, so pushing Deep House reads as House."""
    from vibenative import keystone as K

    p = {"salience": [{"style": "Techno", "score": 0.7}, {"style": "Deep House", "score": 0.3}]}
    assert K.classify(p)["keystones"][0] == "Techno"
    assert K.classify(dict(p, weights={"Deep House": 3}))["keystones"][0] == "House"


def test_an_adjustment_bends_a_confident_read_without_overruling_it():
    """+3 against a 90/10 read makes a strong second, not a winner. Disagreeing
    with a read that confident is what the override is for -- if a step could win
    here it would mean "and also discard the analysis"."""
    lopsided = [{"style": "Techno", "score": 0.9}, {"style": "House", "score": 0.1}]
    out = by_style(W.apply(lopsided, {"House": 3}))
    assert out["Techno"] > out["House"] > 0.35


# --- the HTTP surface ---------------------------------------------------------
def seed(payload, h="wt1"):
    """Put one analysed track in the scratch DB."""
    from vibenative.db import cache_put

    cache_put(h, f"{h}.mp3", "", h, payload, None)
    return h


def test_get_returns_the_read_and_the_vocabulary(client):
    h = seed({"salience": REAL})
    body = client.get(f"/weights/{h}").get_json()
    assert body["steps"] == {}
    assert body["adjusted"] == body["base"]  # untouched track: nothing bent
    # The UI must not hardcode the scale or the wording.
    assert body["max_step"] == W.MAX_STEP
    assert body["words"]["3"] == "very"


def test_post_stores_steps_and_returns_the_new_blend(client):
    h = seed({"salience": REAL})
    body = client.post(f"/weights/{h}", json={"steps": {"House": 3}}).get_json()
    assert body["steps"] == {"House": 3}
    assert body["adjusted"][0]["style"] == "House"
    assert client.get(f"/weights/{h}").get_json()["steps"] == {"House": 3}


def test_the_analysed_read_survives_underneath(client):
    """Adjusting must be undoable, which means never writing over salience."""
    h = seed({"salience": REAL})
    client.post(f"/weights/{h}", json={"steps": {"House": 3}})
    assert client.get(f"/weights/{h}").get_json()["base"] == REAL


def test_clearing_restores_the_model_read(client):
    h = seed({"salience": REAL})
    client.post(f"/weights/{h}", json={"steps": {"House": 3}})
    client.post(f"/weights/{h}", json={"steps": {}})
    body = client.get(f"/weights/{h}").get_json()
    assert body["steps"] == {}
    assert body["adjusted"] == REAL


def test_zero_steps_are_dropped_not_stored(client):
    """ "No opinion" and "explicitly neutral" are the same thing, so the payload
    must not accumulate dead entries as the user toggles."""
    h = seed({"salience": REAL})
    body = client.post(f"/weights/{h}", json={"steps": {"House": 0, "Techno": 2}}).get_json()
    assert body["steps"] == {"Techno": 2}


def test_out_of_range_and_junk_steps_are_survivable(client):
    h = seed({"salience": REAL})
    body = client.post(
        f"/weights/{h}", json={"steps": {"House": 99, "Techno": "x", "  ": 3}}
    ).get_json()
    assert body["steps"] == {"House": W.MAX_STEP}


def test_bad_requests_are_rejected(client):
    h = seed({"salience": REAL})
    assert client.post(f"/weights/{h}", json={"steps": "House"}).status_code == 400
    assert client.post(f"/weights/{h}", json={}).status_code == 400
    assert client.get("/weights/nosuchtrack").status_code == 404
    assert client.post("/weights/nosuchtrack", json={"steps": {"House": 1}}).status_code == 404


def test_the_map_shows_the_adjusted_genre(client):
    """The whole point: the adjustment has to reach the view the user is looking
    at, not just the endpoint that stored it."""
    h = seed({"salience": REAL})
    node = next(n for n in client.get("/map").get_json()["nodes"] if n["hash"] == h)
    assert node["style"] == "Techno"
    client.post(f"/weights/{h}", json={"steps": {"House": 3}})
    node = next(n for n in client.get("/map").get_json()["nodes"] if n["hash"] == h)
    assert node["style"] == "House"


# --- removing a genre outright -------------------------------------------------
# A drop is not a stronger -3. "Not at all" says the track is barely this and
# leaves it in the read; a drop says the genre isn't on the track. These check
# that the two stay distinguishable, and that a removal is always undoable.
def test_dropping_takes_a_genre_off_the_read():
    out = by_style(W.apply(REAL, {}, ["Tech Trance"]))
    assert "Tech Trance" not in out
    assert set(out) == {"Techno", "House", "Electro House"}


def test_a_drop_is_not_the_same_as_the_lowest_step():
    """-3 suppresses; a drop removes. If they were the same press there would be
    no reason for both to exist."""
    pushed_down = by_style(W.apply(REAL, {"Tech Trance": -3}))
    dropped = by_style(W.apply(REAL, {}, ["Tech Trance"]))
    assert 0 < pushed_down["Tech Trance"] < 0.05
    assert "Tech Trance" not in dropped


def test_the_freed_share_is_redistributed_not_left_as_a_hole():
    before = by_style(W.apply(REAL, {}))
    after = by_style(W.apply(REAL, {}, ["Tech Trance"]))
    assert sum(after.values()) == pytest.approx(1.0, abs=0.005)
    assert after["Techno"] > before["Techno"]


def test_dropping_preserves_the_order_of_what_is_left():
    out = [e["style"] for e in W.apply(REAL, {}, ["House"])]
    assert out == ["Techno", "Tech Trance", "Electro House"]


def test_a_drop_and_a_step_on_the_same_genre_cannot_both_hold():
    """"More of this" and "none of this" are not both what you meant; the removal
    is the more explicit statement, so it takes the name."""
    out = by_style(W.apply(REAL, {"House": 3}, ["House"]))
    assert "House" not in out


def test_dropping_everything_leaves_the_track_with_an_identity():
    """A track with no read at all is not something a per-genre remove should be
    able to say -- and the empty result falls back to the unedited read, so the
    last press would look like it undid every press before it."""
    out = W.apply(REAL, {}, ["Techno", "House", "Tech Trance", "Electro House"])
    assert out and out[0]["style"] == "Techno"


def test_drops_are_cleaned_the_way_they_are_stored():
    assert W.clean_drops([" House ", "House", "", None, "Techno"]) == ["House", "Techno"]


def test_dropping_a_genre_the_model_never_read_is_harmless():
    assert W.apply(REAL, {}, ["Polka"]) == W.apply(REAL, {})


def test_read_with_steps_applies_a_drop_with_no_steps_at_all():
    """A track whose only edit is a removal still has an edited read."""
    out = W.read_with_steps({"salience": REAL, "drops": ["Tech Trance"]})
    assert out is not None
    assert "Tech Trance" not in by_style(out)


def test_a_dropped_top_read_changes_what_the_track_is():
    from vibenative.routes._shared import _dominant_style

    p = {"salience": REAL}
    assert _dominant_style(p)[0] == "Techno"
    assert _dominant_style(dict(p, drops=["Techno"]))[0] == "House"


# --- the HTTP surface ----------------------------------------------------------
def test_post_stores_drops_and_returns_the_new_blend(client):
    h = seed({"salience": REAL})
    body = client.post(f"/weights/{h}", json={"drops": ["Techno"]}).get_json()
    assert body["drops"] == ["Techno"]
    assert body["adjusted"][0]["style"] == "House"
    assert client.get(f"/weights/{h}").get_json()["drops"] == ["Techno"]


def test_the_removed_genre_is_still_named_in_base_so_it_can_come_back(client):
    """Hiding it from `base` too would make a removal the one edit with no way
    back -- the panel needs the name to offer it."""
    h = seed({"salience": REAL})
    client.post(f"/weights/{h}", json={"drops": ["Techno"]})
    assert "Techno" in [e["style"] for e in client.get(f"/weights/{h}").get_json()["base"]]


def test_restoring_a_drop_restores_the_model_read(client):
    h = seed({"salience": REAL})
    client.post(f"/weights/{h}", json={"drops": ["Techno"]})
    client.post(f"/weights/{h}", json={"drops": []})
    body = client.get(f"/weights/{h}").get_json()
    assert body["drops"] == []
    assert body["adjusted"] == REAL


def test_each_kind_of_edit_survives_the_other_being_sent(client):
    """Removing a genre must not silently discard the steps set on the others,
    which is what a whole-payload write would have done."""
    h = seed({"salience": REAL})
    client.post(f"/weights/{h}", json={"steps": {"House": 2}})
    client.post(f"/weights/{h}", json={"drops": ["Tech Trance"]})
    body = client.get(f"/weights/{h}").get_json()
    assert body["steps"] == {"House": 2}
    assert body["drops"] == ["Tech Trance"]


def test_dropping_a_genre_clears_the_step_already_stored_on_it(client):
    """Otherwise the old judgement comes back the moment it is restored -- one
    the user made before deciding the genre wasn't on the track at all."""
    h = seed({"salience": REAL})
    client.post(f"/weights/{h}", json={"steps": {"House": 3}})
    client.post(f"/weights/{h}", json={"drops": ["House"]})
    assert client.get(f"/weights/{h}").get_json()["steps"] == {}


def test_drops_only_requests_are_accepted_but_empty_ones_are_not(client):
    h = seed({"salience": REAL})
    assert client.post(f"/weights/{h}", json={"drops": ["House"]}).status_code == 200
    assert client.post(f"/weights/{h}", json={"drops": "House"}).status_code == 400
    assert client.post(f"/weights/{h}", json={}).status_code == 400


def test_the_map_shows_a_track_with_its_top_genre_removed(client):
    h = seed({"salience": REAL})
    client.post(f"/weights/{h}", json={"drops": ["Techno"]})
    node = next(n for n in client.get("/map").get_json()["nodes"] if n["hash"] == h)
    assert node["style"] == "House"
