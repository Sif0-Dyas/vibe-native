"""The shown genre set against two other opinions of a track: the model's own
read under an override (style.identity_fields' model_read), and the file's
genre tag (tagcheck), flagged when it names a different keystone."""

import pytest

from conftest import seed_track
from vibenative.style import identity_fields
from vibenative.tagcheck import file_tag_fields, tag_keystone

# What "Known You Before (Original Mix)" looks like in the library: tagged
# Trance, read House 72% / Jungle 28%.
KNOWN_YOU_BEFORE = {
    "salience": [{"style": "House", "score": 0.72}, {"style": "Jungle", "score": 0.28}],
    "styles": [{"style": "House", "score": 0.6}, {"style": "Jungle", "score": 0.3}],
    "tags": {"tag": {"genre": "Trance"}},
}


@pytest.mark.parametrize(
    "tag, keystone",
    [
        ("Trance", "Trance"),
        ("trance", "Trance"),
        ("Trance; Electronic", "Trance"),  # the umbrella part drops out
        ("Drum & Bass", "Drum n Bass"),  # "&" folded to the taxonomy's spelling
        ("Tech House", "House"),
        ("Riddim", "Dubstep"),
        ("Electronic", None),  # a shelf, not a genre
        ("House, Techno", None),  # two families: no single answer
        ("", None),
    ],
)
def test_tag_keystone(tag, keystone):
    assert tag_keystone(tag) == keystone


def test_a_tag_from_another_family_is_flagged():
    assert file_tag_fields(KNOWN_YOU_BEFORE, "House") == {
        "file_tag": {"text": "Trance", "keystone": "Trance", "agrees": False}
    }


def test_a_tag_in_the_same_family_agrees():
    p = {**KNOWN_YOU_BEFORE, "tags": {"tag": {"genre": "Tech House"}}}
    assert file_tag_fields(p, "House")["file_tag"]["agrees"] is True


def test_a_tag_with_no_keystone_is_shown_without_a_verdict():
    p = {**KNOWN_YOU_BEFORE, "tags": {"tag": {"genre": "Electronic"}}}
    assert file_tag_fields(p, "House") == {
        "file_tag": {"text": "Electronic", "keystone": None, "agrees": None}
    }


def test_no_tag_no_field():
    p = {k: v for k, v in KNOWN_YOU_BEFORE.items() if k != "tags"}
    assert file_tag_fields(p, "House") == {}
    assert "file_tag" not in identity_fields(p)


def test_the_model_read_comes_with_an_override_only():
    plain = identity_fields(KNOWN_YOU_BEFORE)
    assert plain["dominant_source"] == "salience" and "model_read" not in plain

    over = identity_fields({**KNOWN_YOU_BEFORE, "override": "Trance"})
    assert over["dominant_style"] == "Trance" and over["dominant_source"] == "override"
    assert [(e["style"], e["score"]) for e in over["model_read"]] == [
        ("House", 0.72),
        ("Jungle", 0.28),
    ]
    # the override agrees with the tag, so nothing is flagged
    assert over["file_tag"]["agrees"] is True


def test_the_model_read_ignores_hand_adjustments():
    # Balance is your judgement, not the model's: model_read is the read before it.
    p = {**KNOWN_YOU_BEFORE, "override": "Trance", "weights": {"Jungle": 3}}
    assert identity_fields(p)["model_read"][0]["style"] == "House"


def test_the_track_route_carries_both(client):
    h = seed_track("k" * 40, dict(KNOWN_YOU_BEFORE))
    body = client.get(f"/api/v1/track/{h}").get_json()
    assert body["file_tag"] == {"text": "Trance", "keystone": "Trance", "agrees": False}
    assert "model_read" not in body

    over = client.post(f"/api/v1/override/{h}", json={"genre": "Trance"}).get_json()
    assert readline(over["model_read"]) == "House 72% / Jungle 28%"
    assert over["file_tag"]["agrees"] is True


def readline(read):
    return " / ".join(f"{e['style']} {round(e['score'] * 100)}%" for e in read)
