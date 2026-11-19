"""tools/bakeoff.py -- the parts that run without the bakeoff group: the
train / test split and its disjointness, telling an unmounted drive from a
missing file, trimming thin training keystones, the CLAP windowing, the
embedding cache, and the report. The embedders and the head need torch /
TensorFlow / scikit-learn and are exercised by running the tool, not here."""

import csv
import sys
from collections import Counter
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


def test_a_blind_track_is_test_only_and_train_is_one_label_per_track(tmp_path):
    p = _csv(
        tmp_path / "labels.csv",
        [
            ("a", "X:/a.mp3", "Techno", "id3-genre"),
            ("a", "X:/a.mp3", "Deep House", "override"),
            ("b", "X:/b.mp3", "Trance", "id3-genre"),
            ("b", "X:/b.mp3", "Tech House", "blind"),  # its id3 row must not train
            ("c", "X:/c.mp3", "Dubstep", "weight"),
            ("c", "X:/c.mp3", "Techno", "id3-genre"),
            ("d", "X:/d.mp3", "Trance", "blind-contested"),
            ("e", "X:/e.mp3", "Moombahton", "blind"),  # no keystone: left out
            ("e", "X:/e.mp3", "House", "id3-genre"),  # ... and still test-only
            ("f", "X:/f.mp3", "Spoken Word", "id3-genre"),  # no keystone
        ],
    )
    train, test, info = bo.split(bo.load_rows(p))
    assert train == {
        "a": ("X:/a.mp3", "House", "override"),  # override outranks the tag
        "c": ("X:/c.mp3", "Dubstep", "weight"),  # weight outranks the tag
    }
    assert test == {
        "b": ("X:/b.mp3", "House", "blind"),
        "d": ("X:/d.mp3", "Trance", "blind-contested"),
    }
    assert not (set(train) & set(test))
    assert info == {"train_rows_of_test_tracks": 2, "test_no_keystone": 1, "train_no_keystone": 1}


def test_evaluate_refuses_a_track_in_both_sets():
    # split() cannot build an overlap; evaluate_lines re-checks the invariant on
    # whatever it is handed, so a future caller cannot leak a test track either.
    with pytest.raises(AssertionError):
        bo.evaluate_lines({}, {"a": "House"}, {"a": ("House", "blind")})


def test_unmounted_drive_is_not_a_missing_file():
    labels = {
        "on_f": ("F:/Soul Seek/x.flac", "Techno", "id3-genre"),
        "gone": ("G:/old/y.mp3", "Techno", "id3-genre"),
        "here": ("G:/new/z.mp3", "Techno", "id3-genre"),
        "nopath": ("", "Techno", "id3-genre"),
    }
    tracks, info = bo.select_tracks(
        labels,
        exists=lambda p: p.startswith("G:/new"),
        mounted=lambda p: not p.startswith("F:"),
    )
    assert set(tracks) == {"here"}
    assert info["unavailable"] == {"F:": 1}
    assert info["missing"] == 1
    assert info["no_path"] == 1
    assert info["sources"] == {"id3-genre": 1}
    assert info["keystones"] == {"Techno": 1}


def test_thin_training_keystones_are_dropped():
    train = {f"h{i}": (f"G:/{i}.mp3", "Techno", "id3-genre") for i in range(5)}
    train["t"] = ("G:/t.mp3", "Trance", "id3-genre")
    kept, dropped = bo.trim_train(train, 5)
    assert {ks for _, ks, _ in kept.values()} == {"Techno"}
    assert dropped == {"Trance": 1}


def test_centre_cut():
    a = np.arange(100, dtype=np.float32)
    assert bo.centre_cut(a, 10, 4).tolist() == list(range(30, 70))
    assert len(bo.centre_cut(a, 10, 0)) == 100  # 0 = whole track
    assert len(bo.centre_cut(a, 10, 60)) == 100  # shorter than the cut


@pytest.mark.parametrize(
    "length, starts",
    [
        (3, [0]),  # shorter than a window: one window, the processor pads
        (10, [0]),
        (14, [0, 4]),  # the tail is covered by a window aligned to the end
        (20, [0, 10]),
        (25, [0, 10, 15]),
        (60, [0, 10, 20, 30, 40, 50]),
        (65, [0, 10, 20, 30, 40, 50, 55]),
    ],
)
def test_clap_windows_cover_the_audio_and_never_exceed_the_window(length, starts):
    n = 10
    got = bo.CLAP.windows(length, n)
    assert got == starts
    assert all(s + n >= min(length, n) for s in got)
    if length > n:
        assert got[-1] + n == length  # nothing dropped
        assert all(s + n <= length for s in got)  # no window the processor would crop


class _Fake:
    name, sr = "fake", bo.DECODE_SR

    def __init__(self):
        self.calls = 0

    def embed(self, audio):
        self.calls += 1
        return np.array([audio.mean(), len(audio)], dtype=np.float32)


def test_extract_caches_skips_failures_and_counts_what_it_timed(tmp_path):
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
    assert timing["fake_n"] == 2 and timing["decode_n"] == 2
    assert (tmp_path / "fake.npz").exists()

    again = _Fake()
    embs2, timing2, _ = bo.extract(tracks, [again], tmp_path, 1, decode=decode, log=lambda m: 0)
    assert again.calls == 0  # everything that worked came from the cache
    assert "fake_n" not in timing2
    assert np.array_equal(embs2["fake"]["b"], embs["fake"]["b"])


def _score(n_house=12, n_trance=3):
    return {
        "n": n_house + n_trance,
        "accuracy": 0.7,
        "macro_f1": 0.6,
        "per_keystone": {"House": {"precision": 0.9, "recall": 0.8, "n": n_house}},
        "confusion": {f"{a}->{b}": 1 for a, b in bo.CONFUSION_PAIRS},
        "support": {"House": n_house, "Trance": n_trance},
    }


def _results():
    return {
        n: {"blind": _score(), "blind-contested": _score(20, 5), "fit_s": 1.5}
        for n in (bo.REFERENCE, bo.MODEL_READ, "x")
    }


def _info(n):
    return {
        "labels": n + 2,
        "no_path": 1,
        "unavailable": Counter({"F:": 1}),
        "missing": 0,
        "sources": Counter({"id3-genre": n}),
        "keystones": Counter({"House": n}),
    }


def _report(smoke):
    return bo.report(
        _results(),
        {"train_rows_of_test_tracks": 3},
        _info(40),
        _info(15),
        {"Disco": 2},
        {"x": 10.0, "x_n": 4, "decode": 8.0, "decode_n": 4},
        smoke=smoke,
    )


def test_report_marks_the_model_read_as_selected_against_only_on_the_contested_table():
    text = _report(smoke=False)
    blind, contested = text.split("== blind-contested")
    assert "SELECTED AGAINST THIS MODEL" in contested
    assert "model-read*" in contested
    assert "SELECTED AGAINST" not in blind
    assert "model-read*" not in blind
    assert "train and test share no track (asserted)" in text
    assert "3 training rows dropped because their track is a test track" in text
    assert "dropped from training (too few tracks): {'Disco': 2}" in text
    assert "1 on an unmounted drive" in text
    assert "House->Techno" in text and "Trance->House" in text
    assert "2.50 (4)" in text  # x: 10 s over 4 new tracks
    assert "SMOKE" not in text


def test_smoke_report_is_stamped_on_every_line():
    text = _report(smoke=True)
    lines = [ln for ln in text.splitlines() if ln and not set(ln) <= {"="}]
    assert lines[0].startswith("SMOKE TEST -- NOT A RESULT")
    assert all("SMOKE TEST" in ln or ln.startswith("set is not") for ln in lines)


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
