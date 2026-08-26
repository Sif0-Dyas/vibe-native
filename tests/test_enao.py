"""Unit tests for the Every Noise genre reference and its offline builder.

The parser is tested against canned markup in both the forms the page comes in:
as served (unquoted attributes) and as a browser writes it back out on "Save as"
(quoted). Everything else runs against a small synthetic index injected into
``enao._index``, so the suite never needs the real snapshot -- which is
git-ignored and absent in CI.

One test *does* use the real snapshot when it happens to be present, to guard
the alias table against rot: every alias must point at a genre that exists.
"""

import importlib.util
import json
from pathlib import Path

import pytest

from vibenative import enao

TOOLS = Path(__file__).resolve().parent.parent / "tools"


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_enao", TOOLS / "build_enao.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# The page as everynoise.com serves it: bare, unquoted attributes.
SERVED = (
    '<div class=canvas role=main style="width: 1610px">\n'
    '<div id=item1 preview_url="https://p.scdn.co/x" class="genre scanme" scan=true '
    'style="color: #ad8907; top: 4997px; left: 783px; font-size: 160%" '
    'onclick="playx(&quot;1V6gIisPpYqgFeWbMLI0bA&quot;, &quot;pop&quot;, this);" '
    'title="e.g. Demi Lovato &quot;Heart Attack&quot;">pop</div>\n'
)

# The same node after a browser round-trips it through the DOM serializer.
SAVED = (
    '<div id="item1" preview_url="https://p.scdn.co/x" class="genre scanme" scan="true" '
    'style="color: #ad8907; top: 4997px; left: 783px; font-size: 160%" '
    'onclick="playx(&quot;1V6gIisPpYqgFeWbMLI0bA&quot;, &quot;pop&quot;, this);" '
    'title="e.g. Demi Lovato &quot;Heart Attack&quot;">pop</div>\n'
)


@pytest.mark.parametrize("markup", [SERVED, SAVED], ids=["as-served", "as-saved"])
def test_parse_handles_both_quotings(markup):
    """Whichever way the user saved the page, the same record comes out."""
    (rec,) = _load_builder().parse(markup)
    assert rec == {
        "name": "pop",
        "x": 783,
        "y": 4997,
        "color": "#ad8907",
        "size": 160,
        "track_id": "1V6gIisPpYqgFeWbMLI0bA",
        "example": {"artist": "Demi Lovato", "title": "Heart Attack"},
    }


def test_parse_rejects_a_saved_shortcut():
    """A .url shortcut (or any non-page) yields nothing rather than half-data."""
    assert _load_builder().parse("[InternetShortcut]\nURL=https://everynoise.com/") == []


@pytest.fixture
def index(monkeypatch):
    """A synthetic genre index, so tests don't need the real snapshot."""
    fake = {
        "techno": {"name": "techno", "x": 1180, "y": 1048, "color": "#ba89c8", "size": 130},
        "synthpop": {"name": "synthpop", "x": 900, "y": 5000, "color": "#b57929", "size": 120},
        "norteno": {"name": "norteno", "x": 988, "y": 12000, "color": "#988e03", "size": 110},
        "rock-and-roll": {
            "name": "rock-and-roll",
            "x": 840,
            "y": 16000,
            "color": "#84800e",
            "size": 115,
        },
        "contemporary r&b": {
            "name": "contemporary r&b",
            "x": 998,
            "y": 8000,
            "color": "#998707",
            "size": 118,
        },
        "metal": {"name": "metal", "x": 500, "y": 11000, "color": "#dc4e3c", "size": 125},
        "opera": {"name": "opera", "x": 315, "y": 22648, "color": "#315000", "size": 100},
    }
    monkeypatch.setattr(enao, "_index", fake)
    return fake


def test_exact_and_parent_stripping(index):
    assert enao.get("Electronic---Techno")["name"] == "techno"
    assert enao.get("techno")["name"] == "techno"


@pytest.mark.parametrize(
    "label,expected",
    [
        ("Electronic---Synth-pop", "synthpop"),  # hyphen dropped
        ("Latin---Norteño", "norteno"),  # diacritic folded
        ("Rock---Rock & Roll", "rock-and-roll"),  # "&" spelled, spaces hyphenated
        ("Funk / Soul---Contemporary R&B", "contemporary r&b"),  # "&" kept literal
    ],
)
def test_spelling_variants(index, label, expected):
    assert enao.get(label)["name"] == expected


def test_alias_table(index):
    # Every Noise has no bare "heavy metal"; the curated alias redirects it.
    assert enao.get("Rock---Heavy Metal")["name"] == "metal"


def test_non_music_is_unmapped_on_purpose(index):
    for label in ("Non-Music---Dialogue", "Non-Music---Audiobook", "Hip Hop---DJ Battle Tool"):
        assert enao.get(label) is None


def test_unknown_style_returns_none_not_a_guess(index):
    assert enao.get("Rock---Entirely Made Up Genre") is None
    assert enao.color("Rock---Entirely Made Up Genre") is None
    assert enao.color("Rock---Entirely Made Up Genre", "#ccc") == "#ccc"


def test_missing_snapshot_disables_lookups_quietly(monkeypatch, tmp_path):
    monkeypatch.setattr(enao, "_index", None)
    monkeypatch.setattr(enao, "DATA", tmp_path / "absent.json")
    assert enao.get("Electronic---Techno") is None
    assert enao.color("Electronic---Techno", "#fallback") == "#fallback"
    assert enao.position([{"style": "Electronic---Techno", "score": 1.0}]) is None


def test_position_is_score_weighted(index):
    near_techno = enao.position(
        [
            {"style": "Electronic---Techno", "score": 0.9},
            {"style": "Classical---Opera", "score": 0.1},
        ]
    )
    assert near_techno[1] == pytest.approx(1048 * 0.9 + 22648 * 0.1)


def test_position_skips_unmapped_rather_than_dragging_the_centroid(index):
    """An unmapped top style must not pull the result toward the origin."""
    only_techno = enao.position([{"style": "Electronic---Techno", "score": 1.0}])
    with_junk = enao.position(
        [
            {"style": "Non-Music---Dialogue", "score": 0.9},
            {"style": "Electronic---Techno", "score": 0.1},
        ]
    )
    assert with_junk == only_techno


def test_position_ignores_nonpositive_and_bad_scores(index):
    assert enao.position([{"style": "Electronic---Techno", "score": 0}]) is None
    assert enao.position([{"style": "Electronic---Techno", "score": "oops"}])[0] == 1180


def test_position_accepts_bare_strings(index):
    assert enao.position(["Electronic---Techno"])[0] == 1180


def test_axes_orientation(index):
    """0 = mechanical/dense, 1 = organic/bouncy. Measured, not assumed."""
    techno = enao.axes(["Electronic---Techno"])
    opera = enao.axes(["Classical---Opera"])
    assert techno["organic"] < 0.2 < 0.9 < opera["organic"]
    assert techno["bouncy"] > opera["bouncy"]
    assert enao.axes(["Non-Music---Dialogue"]) is None


def test_coverage_reports_misses(index):
    mapped, total, misses = enao.coverage(["Electronic---Techno", "Non-Music---Dialogue"])
    assert (mapped, total) == (1, 2)
    assert misses == ["Non-Music---Dialogue"]


@pytest.mark.skipif(not enao.DATA.is_file(), reason="enao.json snapshot is built locally")
def test_every_alias_target_exists_in_the_real_snapshot():
    """Guards the curated table: a typo'd target silently disables its alias."""
    names = {r["name"] for r in json.loads(enao.DATA.read_text(encoding="utf-8"))["genres"]}
    assert {k: v for k, v in enao.ALIASES.items() if v not in names} == {}
