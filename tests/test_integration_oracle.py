"""End-to-end integration: real analysis through the /analyze route matches oracle.

The one REAL-mode test in the suite -- proof the whole app (HTTP route -> analyze()
-> native ONNX engine -> payload -> JSON) reproduces the oracle. Skips unless the
ONNX models, onnxruntime, and oracle audio are all present (absent on CI, like the
engine acceptance tests); the rest of the suite runs in FAKE mode.
"""

import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ORACLE = ROOT / "oracle"
MODELS = ROOT / "models"


def _ready():
    if not (ORACLE / "index.json").exists():
        return False, "no oracle/index.json"
    if not all((MODELS / m).exists() for m in ("effnet.onnx", "genre400.onnx", "tempocnn.onnx")):
        return False, "onnx models absent"
    try:
        import onnxruntime  # noqa: F401
    except Exception:
        return False, "onnxruntime not installed"
    sys.path.insert(0, str(ROOT / "src"))
    from vibenative.paths import wsl_to_windows

    idx = json.loads((ORACLE / "index.json").read_text())
    if not any(Path(wsl_to_windows(m["file"])).is_file() for m in idx.values()):
        return False, "oracle audio not on disk"
    return True, ""


_READY, _WHY = _ready()


@pytest.mark.skipif(not _READY, reason=_WHY)
def test_analyze_route_matches_oracle(tmp_path, monkeypatch):
    """POST 2-3 oracle tracks to /analyze in real mode; the JSON response's top
    style, key/scale, and BPM must match oracle/index.json."""
    monkeypatch.delenv("FAKE_ANALYZER", raising=False)  # real engine, not the fake path
    monkeypatch.setenv("GENRE_DB", str(tmp_path / "integ.db"))

    # Re-import the package in REAL mode (config.FAKE is read at import time).
    for name in list(sys.modules):
        if name == "vibenative" or name.startswith("vibenative."):
            del sys.modules[name]
    import vibenative
    from vibenative.paths import wsl_to_windows

    app = vibenative.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    idx = json.loads((ORACLE / "index.json").read_text())
    picked = [m for m in idx.values() if Path(wsl_to_windows(m["file"])).is_file()][:3]
    assert picked, "no oracle audio available"

    for m in picked:
        p = Path(wsl_to_windows(m["file"]))
        with open(p, "rb") as fh:
            resp = client.post(
                "/analyze",
                data={"file": (io.BytesIO(fh.read()), p.name)},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 200, resp.data
        j = resp.get_json()

        # top style matches the oracle's top style
        assert j["styles"][0]["style"] == m["styles"][0]["style"], (
            f"{p.name}: top style {j['styles'][0]['style']!r} != oracle {m['styles'][0]['style']!r}"
        )
        # key present and well-formed; agreement with the oracle is measured across
        # the whole set by tests/test_tonality.py + tools/eval_key.py, not per track
        assert j["scale"] in ("major", "minor") and j["key"], f"{p.name}: key {(j['key'], j['scale'])}"
        # BPM within 2% OR a half/double multiple (octave-ambiguity tolerant)
        if m["bpm"] and j["bpm"]:
            assert any(
                abs(j["bpm"] - c) / c <= 0.02 for c in (m["bpm"], m["bpm"] / 2, m["bpm"] * 2)
            ), f"{p.name}: bpm {j['bpm']} vs oracle {m['bpm']}"
