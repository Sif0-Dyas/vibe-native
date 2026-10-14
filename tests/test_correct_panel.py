"""The Correct panel (static/correct.js): one way to correct a track's genre.

The panel is the only way in -- the Analyzer row and the Map popup both open it,
and the gestures and buttons it replaced (Shift-drag / Shift-click on the
waveform, separate adjust and override buttons) stay gone. The user guide
describes the three tools in the panel's own words, so the two cannot drift.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "vibenative" / "static"
CORRECT = (STATIC / "correct.js").read_text(encoding="utf-8")


def _hints():
    found = dict(re.findall(r"^\s+(whole|sections|balance): '([^']+)',$", CORRECT, re.M))
    assert set(found) == {"whole", "sections", "balance"}, found
    return {k: v.replace("\\u2014", "—") for k, v in found.items()}


def test_the_guide_uses_the_panels_words():
    guide = (ROOT / "docs" / "USAGE.md").read_text(encoding="utf-8")
    for name, hint in _hints().items():
        assert hint in guide, f"USAGE.md no longer describes {name} as the panel does: {hint!r}"
    assert "omit** the track and re-scan" not in guide  # Reset replaced the workaround


def test_both_places_open_the_one_panel():
    for name in ("app.js", "map.js"):
        src = (STATIC / name).read_text(encoding="utf-8")
        assert "wireCorrectPanel(" in src, name
        for gone in ("wireAdjustPanel", "adjustPanelHtml", "/api/v1/override/"):
            assert gone not in src, f"{name} still has its own {gone}"


def test_no_shift_gestures_on_the_waveform():
    # The row's waveform lives in app.js; the player's seek in player.js. (The
    # map's Shift-drag pans its canvas, which is not a correction.)
    for name in ("app.js", "player.js", "correct.js"):
        assert "shiftKey" not in (STATIC / name).read_text(encoding="utf-8"), name
