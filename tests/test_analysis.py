"""Unit tests for the analyze() decomposition helpers.

_decode_and_infer stays untested here (it needs the real ONNX models, absent in
CI — the same reason analysis.py's real path is uncovered). _musical_features and
_assemble are exercised with synthetic inputs: the former with the native
`tempo.estimate` / `key.estimate` monkeypatched (Phase-4 engine swap: BPM/key are
native now, not Essentia — the test's contract is unchanged, only the mocked
extractor is), the latter with hand-built predictions/embeddings so it runs on
pure NumPy.
"""

import numpy as np
import pytest

from vibenative import analysis
from vibenative import key as keymod
from vibenative import tempo


def test_musical_features_happy(monkeypatch):
    monkeypatch.setattr(tempo, "estimate", lambda audio, sr: (128.0, 3.0))
    monkeypatch.setattr(keymod, "estimate", lambda audio, sr: ("C", "major", 0.9))
    out = analysis._musical_features(np.ones(44100, dtype=np.float32))

    assert out["duration"] == 1.0  # 44100 / 44100
    assert out["bpm"] == 128.0
    assert out["bpm_confidence"] == 3.0
    assert (out["key"], out["scale"]) == ("C", "major")
    assert out["camelot"] == analysis.CAMELOT[("C", "major")]
    assert out["key_strength"] == 0.9
    assert len(out["waveform"]) == analysis.WAVE_BINS
    assert set(out["wave"]) == {"bins", "min", "max", "rms"}
    assert out["wave"]["bins"] == analysis.WAVE_MM_BINS


def test_musical_features_degrades_on_extractor_error(monkeypatch):
    def boom(audio, sr):
        raise RuntimeError("extractor unavailable")

    monkeypatch.setattr(tempo, "estimate", boom)
    monkeypatch.setattr(keymod, "estimate", boom)
    out = analysis._musical_features(np.zeros(22050, dtype=np.float32))

    # BPM/key are best-effort: a failing extractor degrades to None, not a crash.
    assert out["bpm"] is None and out["bpm_confidence"] is None
    assert out["key"] is None and out["scale"] is None and out["camelot"] is None
    # duration + waveform are pure-NumPy and still computed.
    assert out["duration"] == 0.5  # 22050 / 44100
    assert len(out["waveform"]) == analysis.WAVE_BINS


def test_assemble_shape_and_values(monkeypatch):
    # Force "no custom head" deterministically, independent of the dev machine's
    # ~/essentia_models/custom_head.npz.
    monkeypatch.setattr(analysis, "_custom", {"checked": True, "head": None})

    labels = ["A---House", "B---Techno", "C---Trance"]
    preds = np.array([[0.7, 0.2, 0.1], [0.1, 0.8, 0.1]], dtype=np.float32)
    embeddings = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
    audio16 = np.ones(1000, dtype=np.float32)
    features = {
        "bpm": 128.0,
        "bpm_confidence": 3.5,
        "key": "C",
        "scale": "major",
        "camelot": "8B",
        "key_strength": 0.9,
        "duration": 200.0,
        "waveform": [0.1] * analysis.WAVE_BINS,
        "wave": {"bins": 4, "min": [0.0], "max": [0.0], "rms": [0.0]},
    }

    out = analysis._assemble(labels, audio16, embeddings, preds, features)

    # exact key set + order (not a single key added, dropped, or reordered)
    assert list(out.keys()) == [
        "styles",
        "segments",
        "salience",
        "frames",
        "custom",
        "bpm",
        "bpm_confidence",
        "key",
        "scale",
        "camelot",
        "key_strength",
        "duration",
        "waveform",
        "wave",
        "emb_mean",
    ]
    # styles ranked by mean prediction: Techno (0.5) > House (0.4) > Trance (0.1)
    assert [s["style"] for s in out["styles"]] == ["Techno", "House", "Trance"]
    assert out["styles"][0]["parent"] == "B"
    assert out["styles"][0]["score"] == pytest.approx(0.5)
    # per-frame winners -> segment labels
    assert out["segments"] == ["House", "Techno"]
    assert len(out["frames"]) == 2
    assert out["salience"]  # non-empty salience read
    assert out["custom"] is None
    assert out["emb_mean"] == [2.0, 3.0]
    # musical features spliced through unchanged (same objects)
    assert out["bpm"] == 128.0
    assert out["key"] == "C" and out["camelot"] == "8B"
    assert out["duration"] == 200.0
    assert out["waveform"] is features["waveform"]
    assert out["wave"] is features["wave"]
