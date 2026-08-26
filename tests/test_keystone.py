"""Unit tests for the keystone taxonomy.

Everything here runs on hand-built payloads -- no models, no database, no
snapshot -- because keystone.py is pure table lookup over the style read that
analysis.py already stores.

Two tests encode invariants that are easy to break by editing the tables:
a fusion name must never collide with a real Discogs style (or the taxonomy
contradicts itself), and every style the tables mention must be a style the
model can actually emit.
"""

import json
from pathlib import Path

import pytest

from vibenative import keystone as K

MODELS = Path(__file__).resolve().parent.parent / "models"
LABELS = MODELS / "genre_discogs400-discogs-effnet-1.json"


def sal(*pairs):
    """Build a payload with the given (style, score) salience read."""
    return {"salience": [{"style": s, "score": v} for s, v in pairs]}


# --- the rollup ---------------------------------------------------------------
@pytest.mark.parametrize(
    "style,expected",
    [
        ("Deep House", "House"),
        ("Progressive House", "House"),
        ("Bassline", "House"),
        ("UK Garage", "House"),
        ("Minimal Techno", "Techno"),
        ("Tech Trance", "Trance"),
        ("Psy-Trance", "Trance"),
        ("Grime", "Dubstep"),
        ("Jungle", "Drum n Bass"),
        ("Halftime", "Halftime"),  # standalone by choice
        ("Hardstyle", "Hard Dance"),  # standalone by choice
        ("Gabber", "Hard Dance"),
        ("Trap", "Trap"),  # overrides its Hip Hop parent
        ("Progressive Breaks", "Breakbeat"),
        ("Synthwave", "Downtempo"),
    ],
)
def test_electronic_rollup(style, expected):
    assert K.keystone_of(style) == expected


@pytest.mark.parametrize(
    "label,expected",
    [
        ("Rock---Metalcore", "Metal"),
        ("Rock---Melodic Death Metal", "Metal"),
        ("Rock---Thrash", "Metal"),
        ("Rock---Goregrind", "Metal"),
        ("Rock---Pop Punk", "Punk"),
        ("Rock---Post-Hardcore", "Punk"),
        ("Rock---Emo", "Punk"),
        ("Rock---Shoegaze", "Rock"),
        ("Rock---Alternative Rock", "Rock"),
    ],
)
def test_rock_splits_three_ways(label, expected):
    """Discogs files Slowdive and Cannibal Corpse under one parent; we don't."""
    assert K.keystone_of(label) == expected


def test_parent_used_when_it_already_reads_as_a_keystone():
    assert K.keystone_of("Jazz---Hard Bop") == "Jazz"
    assert K.keystone_of("Latin---Salsa") == "Latin"


def test_non_music_has_no_keystone():
    assert K.keystone_of("Non-Music---Dialogue") is None
    assert K.keystone_of("") is None
    assert K.keystone_of(None) is None


# --- fusion -------------------------------------------------------------------
def test_single_keystone_when_one_dominates():
    r = K.classify(sal(("Dubstep", 0.8), ("Drum n Bass", 0.2)))
    assert r["keystones"] == ["Dubstep"]
    assert r["label"] == "Dubstep"
    assert r["fusion"] is False


def test_fusion_when_runner_up_clears_the_bar():
    r = K.classify(sal(("Dubstep", 0.55), ("Drum n Bass", 0.45)))
    assert r["keystones"] == ["Dubstep", "Drum n Bass"]
    assert r["label"] == "Drumstep"
    assert r["fusion"] is True


def test_threshold_boundary_is_inclusive():
    """Exactly FUSION_THRESHOLD counts; a hair under does not."""
    t = K.FUSION_THRESHOLD
    assert K.classify(sal(("Dubstep", 1 - t), ("Trap", t)))["fusion"] is True
    assert K.classify(sal(("Dubstep", 1 - t + 0.01), ("Trap", t - 0.01)))["fusion"] is False


def test_subgenres_roll_up_so_a_family_is_not_split_against_itself():
    """Three house subgenres beat one dubstep read, even though each is smaller."""
    r = K.classify(
        sal(
            ("Progressive House", 0.3), ("Tech House", 0.2), ("Deep House", 0.15), ("Dubstep", 0.35)
        )
    )
    assert r["keystones"][0] == "House"
    assert r["shares"]["House"] == pytest.approx(0.65)


def test_unnamed_blend_falls_back_to_a_slash():
    r = K.classify(sal(("Trance", 0.55), ("House", 0.45)))
    assert r["label"] == "Trance / House"


def test_label_keeps_strength_order_but_key_does_not():
    # "Hardstyle" (a style) not "Hard Dance" (its keystone) -- only styles resolve.
    a = K.classify(sal(("Dubstep", 0.6), ("Hardstyle", 0.4)))
    b = K.classify(sal(("Hardstyle", 0.6), ("Dubstep", 0.4)))
    assert a["label"] != b["label"]  # direction is real information
    assert a["key"] == b["key"] == "Dubstep + Hard Dance"  # ...but they group together


def test_at_most_two_keystones():
    r = K.classify(sal(("Dubstep", 0.40), ("House", 0.35), ("Trance", 0.25)))
    assert len(r["keystones"]) == 2
    assert "Trance" not in r["keystones"]


# --- families: the tier above keystones ---------------------------------------
@pytest.mark.parametrize(
    "keystone,family",
    [
        ("House", "Dance"),
        ("Techno", "Dance"),
        ("Trance", "Dance"),
        ("Hard Dance", "Dance"),
        ("Dubstep", "Bass"),
        ("Drum n Bass", "Bass"),
        ("Halftime", "Bass"),
        ("Breakbeat", "Bass"),
        ("Trap", "Bass"),
        ("Ambient", "Chill"),
        ("Downtempo", "Chill"),
        ("Industrial", "Experimental"),
    ],
)
def test_electronic_keystones_have_a_family(keystone, family):
    assert K.family_of(keystone) == family


@pytest.mark.parametrize("keystone", ["Metal", "Punk", "Rock", "Hip Hop", "Jazz", "Latin"])
def test_non_electronic_collapses_to_other(keystone):
    """This is a tool for an electronic library -- everything else is one bucket."""
    assert K.family_of(keystone) == K.OTHER_FAMILY


def test_unknown_keystone_lands_in_other_rather_than_raising():
    assert K.family_of("Sea Shanty") == K.OTHER_FAMILY
    assert K.family_of(None) == K.OTHER_FAMILY


def test_every_family_member_is_reachable_as_a_keystone():
    """A typo in FAMILIES would silently orphan a keystone into Other, which
    looks like a taxonomy decision rather than the mistake it is."""
    # Keystones arrive from the electronic table, from _OVERRIDES (Trap), and
    # from the Rock split -- all three are real sources.
    produced = (
        set(K._STYLE_TO_KEYSTONE.values()) | set(K._OVERRIDES.values()) | {"Metal", "Punk", "Rock"}
    )
    listed = {k for ks in K.FAMILIES.values() for k in ks}
    assert listed - produced == set()


def test_family_order_covers_every_family():
    assert set(K.FAMILY_ORDER) == set(K.FAMILIES) | {K.OTHER_FAMILY}
    assert K.FAMILY_ORDER[-1] == K.OTHER_FAMILY  # Other sorts last


def test_classify_reports_the_family():
    r = K.classify(sal(("Deep House", 1.0)))
    assert r["family"] == "Dance"
    assert r["families"] == ["Dance"]
    assert r["cross_family"] is False


def test_a_fusion_within_one_family_is_not_cross_family():
    r = K.classify(sal(("Dubstep", 0.6), ("Drum n Bass", 0.4)))
    assert r["families"] == ["Bass"]
    assert r["cross_family"] is False


def test_a_fusion_across_families_reports_both():
    r = K.classify(sal(("Deep House", 0.6), ("Dubstep", 0.4)))
    assert r["families"] == ["Dance", "Bass"]  # dominant family first
    assert r["cross_family"] is True


def test_override_still_reports_a_family():
    r = K.classify({"override": "Techno"})
    assert r["family"] == "Dance" and r["cross_family"] is False
    assert r["key"] == "Techno"


# --- inputs -------------------------------------------------------------------
def test_override_wins_outright():
    r = K.classify({"override": "Techno", "salience": [{"style": "Dubstep", "score": 1.0}]})
    assert r["keystones"] == ["Techno"] and r["shares"] == {"Techno": 1.0}
    assert r["override"] is True and r["fusion"] is False


def test_falls_back_to_styles_when_salience_is_all_zero():
    """Salience is energy-weighted and zeroes out on very quiet tracks; the
    track must still classify rather than dropping out of the taxonomy."""
    payload = {
        "salience": [{"style": "House", "score": 0.0}],
        "styles": [{"style": "House", "score": 0.035}, {"style": "Punk", "score": 0.028}],
    }
    assert K.classify(payload)["keystones"][0] == "House"


def test_unkeystoned_styles_do_not_dilute_shares():
    """A spoken-word misread shouldn't make a pure house track read as 50%."""
    r = K.classify(sal(("Deep House", 0.5), ("Dialogue", 0.5)))
    assert r["keystones"] == ["House"]
    assert r["shares"]["House"] == pytest.approx(1.0)


def test_empty_and_junk_inputs():
    assert K.classify({}) is None
    assert K.classify(None) is None
    assert K.classify(sal(("Dialogue", 1.0))) is None
    assert K.classify({"salience": [{"style": "House", "score": "junk"}]}) is None


# --- table invariants ---------------------------------------------------------
@pytest.mark.skipif(not LABELS.is_file(), reason="model label file is built locally")
def test_no_fusion_name_collides_with_a_real_style():
    """If a fusion name is also a style, the same blend gets two different
    labels depending on which path reached it. See FUSION_NAMES."""
    styles = {x.split("---")[-1].lower() for x in json.loads(LABELS.read_text())["classes"]}
    collisions = {n for n in K.FUSION_NAMES.values() if n.lower() in styles}
    assert collisions == set()


@pytest.mark.skipif(not LABELS.is_file(), reason="model label file is built locally")
def test_every_mapped_style_is_one_the_model_can_emit():
    """Guards against typos in the tables -- a misspelled style silently never
    matches, so its whole subgenre quietly falls out of its keystone."""
    styles = {x.split("---")[-1].lower() for x in json.loads(LABELS.read_text())["classes"]}
    named = set(K._STYLE_TO_KEYSTONE) | set(K._OVERRIDES)
    assert named - styles == set()


def test_fusion_names_are_symmetric():
    for pair, name in K.FUSION_NAMES.items():
        a, b = sorted(pair)
        assert K.label_for([a, b]) == K.label_for([b, a]) == name


# --- hand-typed genre names (manual overrides) --------------------------------
@pytest.mark.parametrize(
    "typed,expected",
    [
        ("Trap Wave", "Dubstep"),  # explicit: the tracks read as bass, not wave
        ("Phonk", "Trap"),
        ("Big Room House", "House"),  # via the compound-name rule
        ("Afro House", "House"),
        ("Melodic Dubstep", "Dubstep"),
        ("Neurofunk", "Drum n Bass"),
        ("Chillhop", "Lo-Fi"),
        ("Deep Melodic Techno", "Techno"),
    ],
)
def test_hand_typed_genres_land_in_the_right_family(typed, expected):
    """Overrides are free text -- a name the model can't emit still has to find
    a keystone, or it silently falls into the non-electronic Other bucket."""
    assert K.keystone_of(typed) == expected


def test_compound_rule_never_overrides_a_real_label():
    """It runs only after every exact-match path fails."""
    assert K.keystone_of("Deep House") == "House"
    assert K.keystone_of("Rock---Metalcore") == "Metal"
    assert K.keystone_of("Hardstyle") == "Hard Dance"


def test_compound_rule_leaves_non_music_alone():
    assert K.keystone_of("Non-Music---Dialogue") is None
    assert K.keystone_of("Audiobook") is None


def test_user_aliases_are_kept_out_of_the_model_vocabulary_check():
    """_USER_ALIASES holds names the model cannot emit; _OVERRIDES holds real
    Discogs styles. Mixing them would break the invariant that every _OVERRIDES
    key is a producible label."""
    assert set(K._USER_ALIASES) & set(K._OVERRIDES) == set()
