"""Fake mode runs the real pipeline on stand-in engines (vibenative/fake_engine.py).

So a fake analysis must be shaped exactly like a real one: the same keys (both
come out of analysis._assemble), the same value types as real analyses --
oracle/index.json holds real results, committed -- and the real engines' value
ranges, which the old hand-written fake payload got wrong (its bpm_confidence
was 0.5-5.0; tempo.estimate's is a mean peak softmax, 0..1).
"""

import json
import re
from pathlib import Path

import numpy as np
import pytest

from vibenative import analysis

ROOT = Path(__file__).resolve().parent.parent
ORACLE = json.loads((ROOT / "oracle" / "index.json").read_text(encoding="utf-8"))


def _fake(tmp_path, name="track.wav", content=b"any bytes at all"):
    f = tmp_path / name
    f.write_bytes(content)
    return analysis.analyze(f)


def _real_assembled_keys():
    """The key set the real assembler produces, from synthetic inputs."""
    labels = [f"Electronic---S{i}" for i in range(4)]
    preds = np.array([[0.6, 0.2, 0.1, 0.1], [0.1, 0.7, 0.1, 0.1]], dtype=np.float32)
    feats = analysis._musical_features(np.zeros(44100, dtype=np.float32))
    out = analysis._assemble(
        labels, np.ones(32000, np.float32), np.ones((2, 8), np.float32), preds, feats
    )
    return set(out)


def test_same_keys_as_the_real_assembler(tmp_path, use_settings):
    fake = _fake(tmp_path)
    use_settings(fake=False)
    assert set(fake) == _real_assembled_keys()


@pytest.mark.parametrize(
    "key",
    ["bpm", "bpm_confidence", "key", "scale", "camelot", "key_strength", "duration", "styles"],
)
def test_value_types_match_a_real_analysis(tmp_path, key):
    fake = _fake(tmp_path)
    real = next(iter(ORACLE.values()))
    assert type(fake[key]) is type(real[key]), (key, fake[key], real[key])


def test_styles_entries_look_like_real_ones(tmp_path):
    fake = _fake(tmp_path)
    real = next(iter(ORACLE.values()))["styles"]
    assert len(fake["styles"]) == 8  # _assemble keeps the top 8 (the oracle stored its top 5)
    for f, r in zip(fake["styles"], real):
        assert set(f) == set(r) == {"parent", "style", "score"}
        assert all(type(f[k]) is type(r[k]) for k in r)


def test_the_rest_of_the_payload_has_real_types(tmp_path):
    fake = _fake(tmp_path)
    assert all(isinstance(s, str) for s in fake["segments"]) and fake["segments"]
    assert all(set(s) == {"style", "score"} for s in fake["salience"])
    assert all(
        isinstance(fr, list) and all(isinstance(p[0], str) and isinstance(p[1], float) for p in fr)
        for fr in fake["frames"]
    )
    assert len(fake["frames"]) == len(fake["segments"])
    assert fake["custom"] is None  # no custom head in the test's model_dir, as for a real run
    assert len(fake["emb_mean"]) == 1280 and all(isinstance(v, float) for v in fake["emb_mean"])
    assert len(fake["waveform"]) == analysis.WAVE_BINS
    assert set(fake["wave"]) == {"bins", "min", "max", "rms"}


def test_values_are_in_the_real_engines_ranges(tmp_path):
    for i in range(12):
        fake = _fake(tmp_path, f"t{i}.wav", f"content {i}".encode())
        assert 0.0 <= fake["bpm_confidence"] <= 1.0  # tempo.estimate: mean peak softmax
        assert 0.0 <= fake["key_strength"] <= 1.0
        assert fake["camelot"] == analysis.CAMELOT[(fake["key"], fake["scale"])]
        assert 60 <= fake["bpm"] <= 200


def test_deterministic_per_file_content(tmp_path):
    a = _fake(tmp_path, "a.wav", b"the same audio")
    b = _fake(tmp_path, "renamed.wav", b"the same audio")
    c = _fake(tmp_path, "c.wav", b"different audio")
    assert a == b  # the content decides, not the name
    assert a != c


def test_refine_runs_the_real_path_too(tmp_path):
    f = tmp_path / "t.wav"
    f.write_bytes(b"x")
    coarse = analysis.analyze(f)["segments"]
    segments, frames = analysis.refine_segments(f)
    assert len(segments) == len(frames) > len(coarse)  # the finer hop cuts more patches


def test_fake_mode_is_decided_in_one_place():
    """No branch on the setting outside fake_engine.py (and settings.py, which
    reads it): the rest of the package asks fake_engine.engines()."""
    pkg = ROOT / "src" / "vibenative"
    allowed = {pkg / "fake_engine.py", pkg / "settings.py"}
    pattern = re.compile(r"FAKE|\.fake\b")
    hits = [
        f"{p.relative_to(pkg).as_posix()}:{n}: {line.strip()}"
        for p in sorted(pkg.rglob("*.py"))
        if p not in allowed
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]
    assert not hits, "\n".join(hits)
