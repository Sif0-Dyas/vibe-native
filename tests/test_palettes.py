"""Tests for the colour-scheme presets.

The presets are meant to be swapped freely, so what matters is that switching is
non-destructive and reversible, that a per-genre colour survives a switch, and
that the separation numbers shown in the picker are real measurements rather
than decoration.
"""

import pytest

from vibenative import palettes as PP
from vibenative import taxonomy


@pytest.fixture(autouse=True)
def tmp_overlay(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TAXONOMY", str(tmp_path / "taxonomy.json"))
    taxonomy.load(force=True)
    yield
    taxonomy.load(force=True)


# --- the colour maths ---------------------------------------------------------
def test_generated_colours_are_valid_hex():
    for name in PP.names():
        for hx in PP.colors_for(name, "dark").values():
            assert len(hx) == 7 and hx[0] == "#"
            int(hx[1:], 16)


def test_out_of_gamut_chroma_keeps_its_hue():
    """Clamping RGB instead would shift hue, so an evenly spaced ramp would come
    out visibly uneven wherever the gamut is narrow."""
    asked = 240.0
    hx = PP.oklch_hex(0.70, 0.40, asked)  # far more chroma than sRGB can hold
    li, a, b = PP._oklab_of(hx)
    import math

    got = math.degrees(math.atan2(b, a)) % 360
    assert abs(got - asked) < 3


def test_delta_e_is_zero_for_a_colour_against_itself():
    assert PP.delta_e("#3987e5", "#3987e5") == pytest.approx(0, abs=1e-9)


# --- what the picker reports --------------------------------------------------
def test_every_preset_reports_a_measured_separation():
    for p in PP.summarise("dark"):
        s = p["separation"]
        assert s["worst"] is not None and s["worst"] > 0
        assert s["verdict"] in ("tighter", "comparable", "looser")


def test_the_default_measures_comparable_to_itself():
    assert PP.separation("studio", "dark")["verdict"] == "comparable"


def test_a_narrow_arc_reports_looser_than_the_default():
    """Sunset trades separation for mood on purpose. The picker has to say so --
    that is the whole reason the number is shown."""
    assert PP.separation("sunset", "dark")["verdict"] == "looser"


def test_two_lightness_levels_beat_one():
    """Sixteen hues on a single lightness measured ΔE 5.0 -- unreadable. The
    split exists for that reason, so a regression to one level should fail."""
    ks = PP.keystone_order()
    spread = PP.colors_for("spectrum", "dark", ks)
    lightnesses = {round(PP._oklab_of(c)[0], 2) for c in spread.values()}
    assert len(lightnesses) > 1


def test_no_two_genres_share_a_colour_in_a_generated_preset():
    """Two keystones on the same colour is worse than one being grey."""
    cols = PP.colors_for("spectrum", "dark")
    assert len(set(cols.values())) == len(cols)


def test_a_hand_authored_preset_leaves_its_tail_grey_rather_than_recycling():
    cols = PP.colors_for("okabe-ito", "dark")
    assert len(cols) == 8 < len(PP.keystone_order())


# --- applying -----------------------------------------------------------------
def test_the_preset_name_is_stored_not_the_colours_it_computes():
    """Storing the output would freeze it: a later fix to a ramp would never
    reach a library that had already chosen it."""
    PP.apply("neon")
    assert taxonomy.load()["palette"] == "neon"
    assert taxonomy.load()["colors"] == {}


def test_choosing_the_default_writes_nothing():
    PP.apply("neon")
    PP.apply("studio")
    assert taxonomy.load()["palette"] == ""
    assert PP.current() == "studio"


def test_an_unknown_preset_is_refused():
    with pytest.raises(ValueError):
        PP.apply("chartreuse-dreams")


def test_a_preset_repaints_the_library():
    from vibenative import palette as P

    before = P.keystone_color("House", "dark")
    PP.apply("neon")
    assert P.keystone_color("House", "dark") != before


def test_a_per_genre_colour_survives_switching_schemes():
    """Trying a scheme out must not silently discard hand-picked colours."""
    from vibenative import palette as P

    taxonomy.patch({"colors": {"House": "#ff00aa"}})
    for name in ("neon", "pastel", "studio"):
        PP.apply(name)
        assert P.keystone_color("House", "dark") == "#ff00aa"


def test_switching_back_restores_the_solved_default():
    from vibenative import palette as P

    before = P.keystone_color("Techno", "dark")
    PP.apply("sunset")
    PP.apply("studio")
    assert P.keystone_color("Techno", "dark") == before


def test_a_junk_preset_name_in_the_file_falls_back_to_the_default():
    taxonomy.patch({"palette": "not-a-scheme"})
    assert PP.current() == PP.DEFAULT


# --- the HTTP surface ---------------------------------------------------------
def test_routes(client):
    body = client.get("/palettes").get_json()
    assert body["current"] == "studio"
    assert {p["name"] for p in body["presets"]} == set(PP.names())
    assert body["presets"][0]["colors"]  # swatches, so the picker can show them

    assert client.post("/palettes/neon").get_json()["current"] == "neon"
    assert client.get("/palettes").get_json()["current"] == "neon"

    r = client.post("/palettes/nope")
    assert r.status_code == 404 and "known" in r.get_json()


def test_light_and_dark_are_different_schemes(client):
    dark = client.get("/palettes?mode=dark").get_json()["presets"]
    light = client.get("/palettes?mode=light").get_json()["presets"]
    by = lambda ps: {p["name"]: [c["color"] for c in p["colors"]] for p in ps}  # noqa: E731
    assert by(dark)["neon"] != by(light)["neon"]
