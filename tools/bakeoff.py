"""Embedder bake-off: which audio embedding best supports a keystone-level genre head.

Phase 4 prep for retiring the MTG EffNet embedder. For each candidate embedder it
extracts one embedding per labelled track, trains a logistic-regression head at
the keystone level on the tracks whose labels were made looking at the model
(id3 tags, overrides, weights), and scores the head on the tracks labelled blind
on the /label page -- the random sample and the contested sample as two separate
tables, never pooled. Every line is trained on the same tracks and scored on the
same tracks.

    uv run python tools/export_labels.py C:/tmp/genre_v2_copy.db --out labels.csv
    UV_PROJECT_ENVIRONMENT=.venv-bakeoff uv run --group bakeoff \
        python tools/bakeoff.py labels.csv --db C:/tmp/genre_v2_copy.db

The ``bakeoff`` dependency group (torch, TensorFlow, ...) is kept out of the
runtime and dev installs; give it its own environment as above so the PyInstaller
build environment never holds it. Licences of every candidate's code and weights,
and why each is allowed here: docs/PROVENANCE.md, "Candidate embedders (not
shipped)". A candidate whose weights are non-commercial or of unclear licence is
not in CANDIDATES and must not be added.

Split (``split``): a track with a ``blind`` or ``blind-contested`` label is a
test track and nothing else -- its id3 row is dropped from training, and the
code asserts the two sets share no hash. Every other track with an ``override``,
``weight`` or ``id3-genre`` label is a training track, one label per track in
that priority. Labels are mapped to their keystone with tagcheck.keystone_for
(the resolver /label and the Analyzer use); a label with no keystone is left
out and counted. Training keystones with fewer than ``--min-train`` tracks are
dropped from training and listed; a test track whose keystone was never trained
stays in the test set and counts as a miss.

Lines: every candidate, plus two references -- ``effnet``, the stored EffNet
embedding under the same head trained on the same tracks, and ``model-read``,
the shipped model's own top style (weights.base_read: no override, no hand
adjustment) mapped to its keystone. The contested sample was built from the
tracks where that read and the file tag disagree, so on the contested table the
model-read line is marked "selected against this model": its score there is the
share of those disagreements the labeller settled in the model's favour, not an
accuracy.

Per line and table: keystone accuracy and macro-F1 (over the keystones in the
labels or the predictions), per-keystone precision / recall where the test set
has at least ``--min-support`` labels, the House/Techno and Trance/House
confusion counts in both directions, and wall time: embedding seconds per track
over the tracks this run embedded (cached tracks are not re-timed) and the
head's fit time.

Files: a track counts only if its file exists. A file on a drive that is not
mounted is reported as unavailable, separately from a file that is missing.

Audio: decoded once per track at 48 kHz mono (vibenative.decode), cut to the
centred ``--seconds`` (0 = whole track), resampled per candidate. The EffNet
reference is the stored whole-track embedding, so with a cut the candidates see
less audio than the reference. Embeddings are mean-pooled over time and cached
in ``--work`` (an .npz per candidate, keyed by track hash), so a re-run or a new
candidate costs only what is new. Delete a candidate's .npz when its embedding
changes (the CLAP windowing did, 2026-11-19).

``--smoke`` stamps every line of the report as a smoke test. Use it whenever the
labelled set is not the one the benchmark is meant to run on.
"""

from __future__ import annotations

import argparse
import csv
import json
import ntpath
import os
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vibenative.tagcheck import keystone_for  # noqa: E402
from vibenative.weights import base_read  # noqa: E402

TRAIN_SOURCES = ("override", "weight", "id3-genre")  # one label per track, in this priority
TEST_SOURCES = ("blind", "blind-contested")  # one table each, never pooled
DECODE_SR = 48000
REFERENCE = "effnet"
MODEL_READ = "model-read"
# (label keystone, predicted keystone) pairs the report counts, both directions.
CONFUSION_PAIRS = (
    ("House", "Techno"),
    ("Techno", "House"),
    ("Trance", "House"),
    ("House", "Trance"),
)
NO_READ = "(no read)"


# --- candidates ----------------------------------------------------------------
# Each takes mono float32 audio at its own ``sr`` and returns one 1-D embedding.
# Imports are lazy: the module loads (and its tests run) without the bakeoff group.


def _torch_device():
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


class YAMNet:
    """Google YAMNet, MobileNet v1 on AudioSet; 1024-d per 0.96 s frame.
    Weights: the Kaggle TF2 SavedModel (Apache 2.0) -- not the README's
    yamnet.h5, whose bucket states no licence."""

    name, sr = "yamnet", 16000
    HANDLE = "google/yamnet/tensorFlow2/yamnet"

    def load(self):
        import kagglehub
        import tensorflow as tf

        self.model = tf.saved_model.load(kagglehub.model_download(self.HANDLE))

    def embed(self, audio):
        _scores, emb, _spec = self.model(audio.astype(np.float32))
        return emb.numpy().mean(axis=0)


class OpenL3:
    """OpenL3 music / mel256 / 512-d, via the torchopenl3 port. Weights CC BY 4.0
    (Cramer et al.; attribution required)."""

    name, sr = "openl3", 48000
    HOP_S = 0.5

    def load(self):
        import torchopenl3

        self.lib = torchopenl3
        self.model = torchopenl3.models.load_audio_embedding_model(
            input_repr="mel256", content_type="music", embedding_size=512
        )
        self.device = _torch_device()
        self.model = self.model.to(self.device)

    def embed(self, audio):
        emb, _ts = self.lib.get_audio_embedding(
            audio, self.sr, model=self.model, hop_size=self.HOP_S, batch_size=64, verbose=False
        )
        return np.asarray(emb.detach().cpu() if hasattr(emb, "detach") else emb)[0].mean(axis=0)


class PANNs:
    """PANNs Cnn14 (Kong et al.), AudioSet; 2048-d clip embedding. Weights
    Cnn14_mAP=0.431.pth from zenodo.org/records/3987831, CC BY 4.0."""

    name, sr = "panns", 32000
    # panns_inference fetches these with `wget` through os.system, at import time
    # for the label list -- Windows has no wget, so fetch them first.
    FILES = {
        "Cnn14_mAP=0.431.pth": "https://zenodo.org/records/3987831/files/Cnn14_mAP%3D0.431.pth?download=1",
        "class_labels_indices.csv": "https://storage.googleapis.com/us_audioset/youtube_corpus/v1/csv/class_labels_indices.csv",
    }

    def load(self):
        from urllib.request import urlretrieve

        data = Path.home() / "panns_data"
        data.mkdir(exist_ok=True)
        for fname, url in self.FILES.items():
            dest = data / fname
            if not dest.exists() or dest.stat().st_size == 0:
                urlretrieve(url, dest)  # nosec B310 -- fixed https URLs above

        from panns_inference import AudioTagging

        self.model = AudioTagging(
            checkpoint_path=str(data / "Cnn14_mAP=0.431.pth"), device=_torch_device()
        )

    def embed(self, audio):
        _clip, emb = self.model.inference(audio[None, :].astype(np.float32))
        return np.asarray(emb)[0]


class CLAP:
    """LAION CLAP, music checkpoint (laion/larger_clap_music, Apache 2.0) via
    transformers; 512-d per 10 s window."""

    name, sr = "clap", 48000
    MODEL = "laion/larger_clap_music"
    WINDOW_S = 10

    def load(self):
        from transformers import ClapModel, ClapProcessor

        self.device = _torch_device()
        self.model = ClapModel.from_pretrained(self.MODEL).to(self.device).eval()
        self.proc = ClapProcessor.from_pretrained(self.MODEL)

    @staticmethod
    def windows(length, n):
        """Start offsets of the ``n``-sample windows that cover ``length`` samples:
        back to back from 0 and, when audio is left over, a last window aligned to
        the end (overlapping the one before it). Nothing is dropped -- the old
        chunker lost up to 5 s of tail -- and no window exceeds ``n``, which the
        processor would random-crop (``rand_trunc``), making the embedding
        non-deterministic. Audio shorter than one window is one window; the
        processor repeat-pads it."""
        if length <= n:
            return [0]
        starts = list(range(0, length - n + 1, n))
        if starts[-1] + n < length:
            starts.append(length - n)
        return starts

    def embed(self, audio):
        import torch

        n = self.sr * self.WINDOW_S
        chunks = [audio[s : s + n] for s in self.windows(len(audio), n)]
        inputs = self.proc(audio=chunks, sampling_rate=self.sr, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        with torch.no_grad():
            emb = self.model.get_audio_features(**inputs)
        if not torch.is_tensor(emb):  # newer transformers return a model output
            emb = emb.pooler_output
        return emb.cpu().numpy().mean(axis=0)


CANDIDATES = {c.name: c for c in (YAMNet, OpenL3, PANNs, CLAP)}


# --- labels and files ------------------------------------------------------------


def drive_mounted(path: str) -> bool:
    """False for a path on a drive letter that is not there; True otherwise."""
    drive, _ = os.path.splitdrive(path)
    return not drive or os.path.isdir(drive + os.sep)


def load_rows(csv_path):
    """Every row of labels.csv, as dicts with hash / filepath / genre / source."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def split(rows, keystone=keystone_for):
    """(train, test, info): ``{hash: (filepath, keystone, source)}`` twice.

    A track with a blind label is a test track and nothing else: every training
    row of that track is dropped (``info["train_rows_of_test_tracks"]``), so a
    file tag can never be both learnt from and scored against. A track with no
    blind label trains, under its first label in TRAIN_SOURCES order. Labels with
    no keystone are counted and left out. Asserts the two sets are disjoint."""
    test_hashes = {r["hash"] for r in rows if r["source"] in TEST_SOURCES}
    info = Counter()
    test = {}
    for r in rows:
        if r["source"] not in TEST_SOURCES:
            continue
        ks = keystone(r["genre"])
        if not ks:
            info["test_no_keystone"] += 1
            continue
        test[r["hash"]] = (r["filepath"], ks, r["source"])
    rank = {s: i for i, s in enumerate(TRAIN_SOURCES)}
    best = {}
    for r in rows:
        if r["source"] not in rank:
            if r["source"] not in TEST_SOURCES:
                info["unknown_source"] += 1
            continue
        if r["hash"] in test_hashes:
            info["train_rows_of_test_tracks"] += 1
            continue
        h = r["hash"]
        if h not in best or rank[r["source"]] < best[h][0]:
            best[h] = (rank[r["source"]], r["filepath"], r["genre"], r["source"])
    train = {}
    for h, (_, fp, genre, source) in best.items():
        ks = keystone(genre)
        if not ks:
            info["train_no_keystone"] += 1
            continue
        train[h] = (fp, ks, source)
    assert not (set(train) & set(test)), "a track is in both train and test"
    return train, test, dict(info)


def select_tracks(labels, exists=os.path.exists, mounted=drive_mounted):
    """(tracks, info): ``labels`` with the tracks the harness cannot read taken
    out; info counts what was left out and why."""
    info = {
        "labels": len(labels),
        "no_path": 0,
        "unavailable": Counter(),  # drive not mounted, by drive
        "missing": 0,  # drive mounted, file not there
    }
    kept = {}
    for h, (fp, ks, source) in labels.items():
        if not fp:
            info["no_path"] += 1
        elif not mounted(fp):
            info["unavailable"][ntpath.splitdrive(fp)[0] or "?"] += 1
        elif not exists(fp):
            info["missing"] += 1
        else:
            kept[h] = (fp, ks, source)
    info["sources"] = Counter(src for _, _, src in kept.values())
    info["keystones"] = Counter(ks for _, ks, _ in kept.values())
    return kept, info


def trim_train(train, min_n):
    """(train, dropped): training tracks of keystones with fewer than ``min_n``
    tracks are dropped -- the head cannot learn a class from a handful -- and
    ``dropped`` says which and how many."""
    counts = Counter(ks for _, ks, _ in train.values())
    small = {ks: n for ks, n in counts.items() if n < min_n}
    return {h: v for h, v in train.items() if v[1] not in small}, small


def reference_embeddings(db_path, hashes):
    """{hash: EffNet embedding} from the library database, opened read-only."""
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        rows = conn.execute("SELECT hash, embedding FROM tracks WHERE embedding IS NOT NULL")
        want = set(hashes)
        return {h: np.frombuffer(b, dtype=np.float32) for h, b in rows if h in want}
    finally:
        conn.close()


def model_reads(db_path, hashes):
    """{hash: keystone of the shipped model's own top style, or NO_READ} from
    the library database, opened read-only. The read is ``base_read``: the
    analysis as stored, under no override and no hand adjustment."""
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        want = set(hashes)
        out = {}
        for h, text in conn.execute("SELECT hash, payload FROM tracks"):
            if h not in want:
                continue
            try:
                payload = json.loads(text) if text else {}
            except ValueError:
                payload = {}
            read = base_read(payload if isinstance(payload, dict) else {})
            top = read[0].get("style") if read else None
            out[h] = keystone_for(top) or NO_READ
        return out
    finally:
        conn.close()


# --- extraction ---------------------------------------------------------------------


def centre_cut(audio, sr, seconds):
    if not seconds or len(audio) <= seconds * sr:
        return audio
    n = int(seconds * sr)
    start = (len(audio) - n) // 2
    return audio[start : start + n]


def resample(audio, sr_in, sr_out):
    if sr_in == sr_out:
        return audio
    from math import gcd

    from scipy.signal import resample_poly

    g = gcd(sr_in, sr_out)
    return resample_poly(audio, sr_out // g, sr_in // g).astype(np.float32)


def _load_cache(path):
    if not path.exists():
        return {}
    with np.load(path) as z:
        return {h: z["emb"][i] for i, h in enumerate(z["hashes"])}


def _save_cache(path, cache):
    hashes = sorted(cache)
    tmp = path.with_suffix(".tmp.npz")
    np.savez(tmp, hashes=np.array(hashes), emb=np.stack([cache[h] for h in hashes]))
    os.replace(tmp, path)


def extract(tracks, candidates, work, seconds, decode=None, log=print):
    """{candidate: {hash: embedding}}, timing and failures. ``timing`` holds, per
    candidate, the seconds spent embedding and under ``<name>_n`` how many tracks
    that covered; ``decode`` / ``decode_n`` the shared decode. Cached embeddings
    are reused and not timed."""
    if decode is None:
        from vibenative.decode import decode_mono

        def decode(fp):
            return decode_mono(fp, DECODE_SR)

    work.mkdir(parents=True, exist_ok=True)
    caches = {c.name: _load_cache(work / f"{c.name}.npz") for c in candidates}
    timing = Counter()
    failed = Counter()
    todo = [h for h in tracks if any(h not in caches[c.name] for c in candidates)]
    log(f"  {len(tracks) - len(todo)} tracks fully cached, {len(todo)} to embed")

    def save():
        for c in candidates:
            if caches[c.name]:
                _save_cache(work / f"{c.name}.npz", caches[c.name])

    try:
        for i, h in enumerate(todo, 1):
            if i % 50 == 0:
                save()
                log(f"  {i}/{len(todo)}")
            t0 = time.perf_counter()
            try:
                audio = centre_cut(decode(tracks[h][0]), DECODE_SR, seconds)
            except Exception as e:  # one bad file must not end a long run
                failed["decode"] += 1
                log(f"  decode failed: {tracks[h][0]}: {e}")
                continue
            timing["decode"] += time.perf_counter() - t0
            timing["decode_n"] += 1
            for c in candidates:
                if h in caches[c.name]:
                    continue
                t0 = time.perf_counter()
                try:
                    caches[c.name][h] = np.asarray(
                        c.embed(resample(audio, DECODE_SR, c.sr)), dtype=np.float32
                    )
                    timing[f"{c.name}_n"] += 1
                except Exception as e:
                    failed[c.name] += 1
                    log(f"  {c.name} failed on {tracks[h][0]}: {e}")
                timing[c.name] += time.perf_counter() - t0
    finally:  # also on Ctrl+C, so an interrupted run resumes where it stopped
        save()
    return caches, timing, failed


# --- evaluation ---------------------------------------------------------------------


def fit_head(X, y):
    """A standardised, class-balanced logistic-regression head on ``X`` -> ``y``."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    head = make_pipeline(
        StandardScaler(),
        LogisticRegression(max_iter=5000, class_weight="balanced"),
    )
    return head.fit(X, y)


def score(y_true, y_pred, min_support=10):
    """Keystone accuracy, macro-F1 over the keystones in the labels or the
    predictions, per-keystone precision / recall for the keystones with at least
    ``min_support`` labels, and the CONFUSION_PAIRS counts."""
    from sklearn.metrics import f1_score, precision_recall_fscore_support

    y_true, y_pred = list(y_true), list(y_pred)
    labels = sorted(set(y_true) | set(y_pred))
    support = Counter(y_true)
    if y_true:
        p, r, _f, _s = precision_recall_fscore_support(
            y_true, y_pred, labels=labels, zero_division=0
        )
        accuracy = float(np.mean([a == b for a, b in zip(y_true, y_pred)]))
        macro = float(f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0))
    else:
        p = r = []
        accuracy = macro = 0.0
    per = {
        ks: {"precision": float(p[i]), "recall": float(r[i]), "n": support[ks]}
        for i, ks in enumerate(labels)
        if support[ks] >= min_support
    }
    pairs = Counter(zip(y_true, y_pred))
    return {
        "n": len(y_true),
        "accuracy": accuracy,
        "macro_f1": macro,
        "per_keystone": per,
        "confusion": {f"{a}->{b}": pairs[(a, b)] for a, b in CONFUSION_PAIRS},
        "support": dict(support),
    }


def evaluate_lines(lines, train, test, min_support=10):
    """``lines`` is {name: {hash: embedding}} or, for a line that predicts
    directly (the shipped model's read), {name: {hash: keystone}}. Fits each
    embedding line's head on ``train`` ({hash: keystone}) and scores every line
    on each TEST_SOURCES subset of ``test`` ({hash: (keystone, source)}).
    Returns {name: {"blind": score, "blind-contested": score, "fit_s": s}}."""
    train_h = sorted(train)
    test_h = sorted(test)
    assert not (set(train_h) & set(test_h)), "a track is in both train and test"
    y_train = [train[h] for h in train_h]
    results = {}
    for name, table in lines.items():
        t0 = time.perf_counter()
        if all(isinstance(table[h], str) for h in test_h):  # a direct prediction
            pred = {h: table[h] for h in test_h}
        else:
            head = fit_head(np.stack([table[h] for h in train_h]), y_train)
            pred = dict(zip(test_h, head.predict(np.stack([table[h] for h in test_h]))))
        out = {"fit_s": time.perf_counter() - t0}
        for source in TEST_SOURCES:
            hs = [h for h in test_h if test[h][1] == source]
            out[source] = score([test[h][0] for h in hs], [pred[h] for h in hs], min_support)
        results[name] = out
    return results


def _left_out(info):
    unavailable = sum(info["unavailable"].values())
    return (
        f"{info['no_path']} no path, {unavailable} on an unmounted drive "
        f"{dict(info['unavailable']) or ''}, {info['missing']} missing on a mounted drive"
    )


def _rate(timing, name):
    n = timing.get(f"{name}_n", 0)
    if not n:
        return "-" if name in (REFERENCE, MODEL_READ) else "cached"
    return f"{timing[name] / n:.2f} ({n})"


def report(results, split_info, train_info, test_info, dropped, timing, smoke=False):
    """The text report: the split, then one table per test source."""
    tag = "SMOKE TEST -- NOT A RESULT | " if smoke else ""
    out = []
    if smoke:
        out += [
            "=" * 78,
            "SMOKE TEST -- NOT A RESULT. Proves the harness runs end to end; the label",
            "set is not the benchmark set, so these numbers must not be quoted or compared.",
            "=" * 78,
        ]
    n_train = sum(train_info["sources"].values())
    n_test = sum(test_info["sources"].values())
    out += [
        f"{tag}train: {train_info['labels']} labelled tracks -> {n_train} readable; "
        f"left out: {_left_out(train_info)}",
        f"{tag}  sources: {dict(train_info['sources'])}",
        f"{tag}  keystones: {dict(train_info['keystones'].most_common())}",
    ]
    if dropped:
        out.append(f"{tag}  dropped from training (too few tracks): {dropped}")
    out += [
        f"{tag}test: {test_info['labels']} blind-labelled tracks -> {n_test} readable; "
        f"left out: {_left_out(test_info)}",
        f"{tag}  sources: {dict(test_info['sources'])}",
        f"{tag}  keystones: {dict(test_info['keystones'].most_common())}",
        f"{tag}  {split_info.get('train_rows_of_test_tracks', 0)} training rows dropped because "
        f"their track is a test track; {split_info.get('test_no_keystone', 0)} blind and "
        f"{split_info.get('train_no_keystone', 0)} training labels had no keystone",
        f"{tag}  train and test share no track (asserted)",
    ]
    names = list(results)
    for source in TEST_SOURCES:
        first = results[names[0]][source]
        labels = dict(Counter(first["support"]).most_common())
        out += ["", f"{tag}== {source}: {first['n']} tracks, labels {labels}"]
        marked = source == "blind-contested" and MODEL_READ in names
        if marked:
            out.append(
                f"{tag}   {MODEL_READ}*: SELECTED AGAINST THIS MODEL -- these tracks are where its "
                "read and the file tag disagreed, so its score is the share the labeller settled "
                "its way, not an accuracy"
            )
        heads = [f"{n}*" if marked and n == MODEL_READ else n for n in names]
        out.append(f"{tag}{'':<26}" + "".join(f"{h:>14}" for h in heads))
        for key, label in (("accuracy", "accuracy"), ("macro_f1", "macro-F1")):
            cells = "".join(f"{results[nm][source][key]:>14.3f}" for nm in names)
            out.append(f"{tag}{label:<26}{cells}")
        per = first["per_keystone"]
        if per:
            floor = min(v["n"] for v in per.values())
            out.append(f"{tag}per keystone (>= {floor} labels): precision/recall")
            for ks in sorted(per, key=lambda k: -per[k]["n"]):
                cells = "".join(
                    f"{results[nm][source]['per_keystone'][ks]['precision']:>8.2f}/"
                    f"{results[nm][source]['per_keystone'][ks]['recall']:<5.2f}"
                    for nm in names
                )
                out.append(f"{tag}  {ks:<18}{per[ks]['n']:>5}{cells}")
        out.append(f"{tag}confusion (label->predicted), counts")
        for a, b in CONFUSION_PAIRS:
            key = f"{a}->{b}"
            cells = "".join(f"{results[nm][source]['confusion'][key]:>14d}" for nm in names)
            out.append(f"{tag}  {key:<24}{cells}")
    out += ["", f"{tag}wall time"]
    out.append(
        f"{tag}{'embed s/track (n new)':<26}" + "".join(f"{_rate(timing, nm):>14}" for nm in names)
    )
    out.append(
        f"{tag}{'head fit + predict s':<26}"
        + "".join(f"{results[nm]['fit_s']:>14.1f}" for nm in names)
    )
    if timing.get("decode_n"):
        out.append(
            f"{tag}  decode: {timing['decode'] / timing['decode_n']:.2f} s/track over "
            f"{timing['decode_n']} tracks (shared by every candidate)"
        )
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("labels", help="labels.csv from tools/export_labels.py")
    ap.add_argument("--db", required=True, help="library database copy, for the EffNet reference")
    ap.add_argument(
        "--candidates", default=",".join(CANDIDATES), help=f"subset of {','.join(CANDIDATES)}"
    )
    ap.add_argument(
        "--min-train", type=int, default=5, help="drop training keystones with fewer tracks"
    )
    ap.add_argument(
        "--min-support", type=int, default=10, help="per-keystone rows need this many test labels"
    )
    ap.add_argument("--seconds", type=float, default=60, help="centred cut; 0 = whole track")
    ap.add_argument("--limit", type=int, default=0, help="first N usable training tracks only")
    ap.add_argument(
        "--work", default=str(ROOT / "datasets" / "cache" / "bakeoff"), help="embedding cache"
    )
    ap.add_argument("--out", help="also write the results as JSON here")
    ap.add_argument("--smoke", action="store_true", help="label the report as a smoke test")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    names = [n.strip() for n in args.candidates.split(",") if n.strip()]
    unknown = [n for n in names if n not in CANDIDATES]
    if unknown:
        ap.error(f"unknown candidates {unknown}; known: {list(CANDIDATES)}")

    train, test, split_info = split(load_rows(args.labels))
    train, train_info = select_tracks(train)
    test, test_info = select_tracks(test)
    train, dropped = trim_train(train, args.min_train)
    if args.limit:
        train = dict(list(train.items())[: args.limit])
    ref = reference_embeddings(args.db, list(train) + list(test))
    no_ref = [h for h in list(train) + list(test) if h not in ref]
    train = {h: v for h, v in train.items() if h in ref}
    test = {h: v for h, v in test.items() if h in ref}
    print(
        f"{len(train)} training tracks, {len(test)} test tracks "
        f"({dict(Counter(v[2] for v in test.values()))}); {len(no_ref)} without a stored EffNet "
        f"embedding left out; candidates: {', '.join(names)}"
    )

    candidates = []
    load_time = {}
    for n in names:
        t0 = time.perf_counter()
        c = CANDIDATES[n]()
        c.load()
        load_time[n] = time.perf_counter() - t0
        candidates.append(c)
        print(f"  loaded {n} in {load_time[n]:.1f} s")

    tracks = {h: (fp, ks) for h, (fp, ks, _) in {**train, **test}.items()}
    t0 = time.perf_counter()
    embs, timing, failed = extract(tracks, candidates, Path(args.work), args.seconds)
    wall = time.perf_counter() - t0
    if failed:
        print(f"  failures: {dict(failed)}")

    # Same tracks for every line: those every candidate embedded.
    usable = {h for h in tracks if all(h in embs[c.name] for c in candidates)}
    train_y = {h: ks for h, (_, ks, _) in train.items() if h in usable}
    test_y = {h: (ks, src) for h, (_, ks, src) in test.items() if h in usable}
    lines = {REFERENCE: ref, MODEL_READ: model_reads(args.db, test_y)}
    lines.update({c.name: embs[c.name] for c in candidates})
    results = evaluate_lines(lines, train_y, test_y, args.min_support)

    print()
    print(report(results, split_info, train_info, test_info, dropped, timing, args.smoke))
    print(f"load (s): {', '.join(f'{k} {v:.1f}' for k, v in load_time.items())}")
    print(f"extraction wall time: {wall:.0f} s")
    if args.out:
        plain = {
            k: {
                **v,
                "unavailable": dict(v["unavailable"]),
                "sources": dict(v["sources"]),
                "keystones": dict(v["keystones"]),
            }
            for k, v in (("train", train_info), ("test", test_info))
        }
        plain["train"]["dropped"] = dropped
        Path(args.out).write_text(
            json.dumps(
                {
                    "smoke_test": args.smoke,
                    "train_tracks": len(train_y),
                    "test_tracks": dict(Counter(src for _, src in test_y.values())),
                    "seconds": args.seconds,
                    "min_train": args.min_train,
                    "min_support": args.min_support,
                    "results": results,
                    "split": split_info,
                    **plain,
                    "timing_s": {"load": load_time, "embed": dict(timing), "extraction_wall": wall},
                },
                indent=2,
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
