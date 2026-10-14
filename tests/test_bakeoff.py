"""tools/bakeoff.py -- the parts that run without the bakeoff group: picking one
label per track, telling an unmounted drive from a missing file, the embedding
cache, and the smoke-test stamp. The embedders and the CV head need torch /
TensorFlow / scikit-learn and are exercised by running the tool, not here."""

import csv
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import bakeoff as bo  # noqa: E402


def _csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["hash", "filepath", "genre", "source"])
        w.writerows(rows)
    return path


def test_one_label_per_track_by_source_priority(tmp_path):
    p = _csv(
        tmp_path / "labels.csv",
        [
            ("a", "X:/a.mp3", "Techno", "id3-genre"),
            ("a", "X:/a.mp3", "Deep House", "override"),
            ("b", "X:/b.mp3", "Trance", "id3-genre"),
            ("c", "X:/c.mp3", "Dubstep", "weight"),
        ],
    )
    labels = bo.load_labels(p)
    assert labels["a"] == ("X:/a.mp3", "Deep House", "override")
    assert labels["b"][1] == "Trance"
    # A source left out of --sources is ignored entirely.
    assert "c" not in bo.load_labels(p, ["override", "id3-genre"])


def test_unmounted_drive_is_not_a_missing_file():
    labels = {
        "on_f": ("F:/Soul Seek/x.flac", "Techno", "id3-genre"),
        "gone": ("G:/old/y.mp3", "Techno", "id3-genre"),
        "here": ("G:/new/z.mp3", "Techno", "id3-genre"),
        "nopath": ("", "Techno", "id3-genre"),
        "nokey": ("G:/new/w.mp3", "Spoken Word", "id3-genre"),  # keystone_of -> None
    }
    tracks, info = bo.select_tracks(
        labels,
        folds=1,
        exists=lambda p: p.startswith("G:/new"),
        mounted=lambda p: not p.startswith("F:"),
    )
    assert set(tracks) == {"here"}
    assert info["unavailable"] == {"F:": 1}
    assert info["missing"] == 1
    assert info["no_path"] == 1
    assert info["no_keystone"] == 1


def test_keystones_with_fewer_tracks_than_folds_are_dropped():
    labels = {f"h{i}": (f"G:/{i}.mp3", "Techno", "id3-genre") for i in range(5)}
    labels["t"] = ("G:/t.mp3", "Trance", "id3-genre")
    tracks, info = bo.select_tracks(labels, folds=5, exists=lambda p: True, mounted=lambda p: True)
    assert {ks for _, ks in tracks.values()} == {"Techno"}
    assert info["dropped_keystones"] == {"Trance": 1}


def test_centre_cut():
    a = np.arange(100, dtype=np.float32)
    assert bo.centre_cut(a, 10, 4).tolist() == list(range(30, 70))
    assert len(bo.centre_cut(a, 10, 0)) == 100  # 0 = whole track
    assert len(bo.centre_cut(a, 10, 60)) == 100  # shorter than the cut


class _Fake:
    name, sr = "fake", bo.DECODE_SR

    def __init__(self):
        self.calls = 0

    def embed(self, audio):
        self.calls += 1
        return np.array([audio.mean(), len(audio)], dtype=np.float32)


def test_extract_caches_and_skips_failures(tmp_path):
    tracks = {"a": ("a.wav", "Techno"), "b": ("b.wav", "Techno"), "bad": ("bad.wav", "Techno")}

    def decode(fp):
        if fp == "bad.wav":
            raise RuntimeError("corrupt")
        return np.ones(bo.DECODE_SR * 2, dtype=np.float32)

    fake = _Fake()
    embs, timing, failed = bo.extract(tracks, [fake], tmp_path, 1, decode=decode, log=lambda m: 0)
    assert set(embs["fake"]) == {"a", "b"}
    assert embs["fake"]["a"][1] == bo.DECODE_SR  # cut to 1 s
    assert failed == {"decode": 1}
    assert (tmp_path / "fake.npz").exists()

    again = _Fake()
    embs2, _, _ = bo.extract(tracks, [again], tmp_path, 1, decode=decode, log=lambda m: 0)
    assert again.calls == 0  # everything that worked came from the cache
    assert np.array_equal(embs2["fake"]["b"], embs["fake"]["b"])


def _results():
    per = {
        "House": {"precision": 0.9, "recall": 0.8, "f1": 0.85, "n": 7},
        "Trance": {"precision": 0.5, "recall": 0.5, "f1": 0.5, "n": 3},
    }
    return {n: {"macro_f1": 0.6, "accuracy": 0.7, "per_keystone": per} for n in ("effnet", "x")}


def _info():
    return {
        "labels": 12,
        "no_keystone": 0,
        "no_path": 1,
        "unavailable": {"F:": 1},
        "missing": 0,
        "dropped_keystones": {},
        "sources": {"id3-genre": 10},
    }


def test_smoke_report_is_stamped_on_every_line():
    text = bo.report(_results(), _info(), 10, {"x": 1.0}, smoke=True)
    lines = [ln for ln in text.splitlines() if ln and not set(ln) <= {"="}]
    assert lines[0].startswith("SMOKE TEST -- NOT A RESULT")
    assert all("SMOKE TEST" in ln or ln.startswith("set is not") for ln in lines)
    assert "unbalanced" in text  # House is 70%
    assert "1 on an unmounted drive" in text


def test_real_report_is_not_stamped():
    assert "SMOKE" not in bo.report(_results(), _info(), 10, {}, smoke=False)


def test_every_candidate_is_documented_in_provenance():
    """A candidate goes into the harness only after its licences are recorded."""
    prov = (Path(__file__).resolve().parents[1] / "docs" / "PROVENANCE.md").read_text("utf-8")
    section = prov.split("## Candidate embedders (not shipped)", 1)
    assert len(section) == 2, "PROVENANCE.md lost its candidate-embedders section"
    table = section[1].split("\n## ", 1)[0].lower()
    for name in bo.CANDIDATES:
        assert f"**{name}" in table, f"{name} has no licence row in PROVENANCE.md"


@pytest.mark.parametrize("name", list(bo.CANDIDATES))
def test_candidates_import_lazily(name):
    # Constructing one must not need the bakeoff group; only load() may.
    c = bo.CANDIDATES[name]()
    assert c.sr in (16000, 32000, 48000)
