"""Embedder bake-off: which audio embedding best supports a keystone-level genre head.

Phase 4 prep for retiring the MTG EffNet embedder. For each candidate embedder it
extracts one embedding per labelled track, trains a logistic-regression head with
stratified k-fold cross-validation at the keystone level, and reports per-keystone
precision / recall / F1 and macro-F1 -- with the current EffNet embeddings, read
from the library database, as the reference line. Every candidate is scored on the
same tracks and the same folds.

    uv run python tools/export_labels.py C:/tmp/genre_v2_copy.db --out labels.csv
    UV_PROJECT_ENVIRONMENT=.venv-bakeoff uv run --group bakeoff \\
        python tools/bakeoff.py labels.csv --db C:/tmp/genre_v2_copy.db --smoke

The ``bakeoff`` dependency group (torch, TensorFlow, ...) is kept out of the
runtime and dev installs; give it its own environment as above so the PyInstaller
build environment never holds it. Licences of every candidate's code and weights,
and why each is allowed here: docs/PROVENANCE.md, "Candidate embedders (not
shipped)". A candidate whose weights are non-commercial or of unclear licence is
not in CANDIDATES and must not be added.

Labels: one per track, from labels.csv, by source priority manual > override >
weight > id3-genre (``--sources``), mapped to its keystone. Overrides and weights
were set looking at EffNet's read, so they favour the reference line; only
``manual`` labels are blind (see export_labels.py). Keystones with fewer tracks
than folds are dropped and listed.

Files: a track counts only if its file exists. A file on a drive that is not
mounted is reported as unavailable, separately from a file that is missing.

Audio: decoded once per track at 48 kHz mono (vibenative.decode), cut to the
centred ``--seconds`` (0 = whole track), resampled per candidate. The EffNet
reference is the stored whole-track embedding, so with a cut the candidates see
less audio than the reference. Embeddings are mean-pooled over time and cached
in ``--work`` (an .npz per candidate, keyed by track hash), so a re-run or a new
candidate costs only what is new.

``--smoke`` stamps every line of the report as a smoke test. Use it whenever the
labelled set is not the one the benchmark is meant to run on -- e.g. while most
of the library sits on an unmounted drive and the reachable labels are mostly
one keystone.
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

from vibenative.taxonomy.classify import keystone_of  # noqa: E402

SOURCE_PRIORITY = ("manual", "override", "weight", "id3-genre")
DECODE_SR = 48000
REFERENCE = "effnet"


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

    def embed(self, audio):
        import torch

        n = self.sr * self.WINDOW_S
        chunks = [audio[i : i + n] for i in range(0, max(len(audio) - n // 2, 1), n)]
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


def load_labels(csv_path, sources=SOURCE_PRIORITY):
    """{hash: (filepath, genre, source)} -- one label per track, the first of
    ``sources`` (in that priority) that labels it."""
    rank = {s: i for i, s in enumerate(sources)}
    best = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            r = rank.get(row["source"])
            if r is None:
                continue
            h = row["hash"]
            if h not in best or r < best[h][0]:
                best[h] = (r, row["filepath"], row["genre"], row["source"])
    return {h: v[1:] for h, v in best.items()}


def select_tracks(labels, folds, exists=os.path.exists, mounted=drive_mounted):
    """(tracks, info): tracks is {hash: (filepath, keystone)} for the tracks the
    harness can use; info counts what was left out and why."""
    info = {
        "labels": len(labels),
        "no_keystone": 0,
        "no_path": 0,
        "unavailable": Counter(),  # drive not mounted, by drive
        "missing": 0,  # drive mounted, file not there
        "dropped_keystones": {},
        "sources": Counter(),
    }
    kept = {}
    for h, (fp, genre, source) in labels.items():
        ks = keystone_of(genre)
        if not ks:
            info["no_keystone"] += 1
        elif not fp:
            info["no_path"] += 1
        elif not mounted(fp):
            info["unavailable"][ntpath.splitdrive(fp)[0] or "?"] += 1
        elif not exists(fp):
            info["missing"] += 1
        else:
            kept[h] = (fp, ks, source)
    counts = Counter(ks for _, ks, _ in kept.values())
    small = {ks: n for ks, n in counts.items() if n < folds}
    info["dropped_keystones"] = small
    tracks = {h: (fp, ks) for h, (fp, ks, src) in kept.items() if ks not in small}
    info["sources"] = Counter(kept[h][2] for h in tracks)
    return tracks, info


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
    """{candidate: {hash: embedding}} and {candidate: seconds spent embedding}
    ("decode" holds the shared decode time). Cached embeddings are reused; only
    new ones are timed."""
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
            for c in candidates:
                if h in caches[c.name]:
                    continue
                t0 = time.perf_counter()
                try:
                    caches[c.name][h] = np.asarray(
                        c.embed(resample(audio, DECODE_SR, c.sr)), dtype=np.float32
                    )
                except Exception as e:
                    failed[c.name] += 1
                    log(f"  {c.name} failed on {tracks[h][0]}: {e}")
                timing[c.name] += time.perf_counter() - t0
    finally:  # also on Ctrl+C, so an interrupted run resumes where it stopped
        save()
    return caches, timing, failed


# --- evaluation ---------------------------------------------------------------------


def evaluate(X, y, folds, seed=0):
    """Per-keystone precision / recall / F1 / support and macro-F1 for a
    standardised logistic-regression head under stratified k-fold CV."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import f1_score, precision_recall_fscore_support
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    head = make_pipeline(
        StandardScaler(),
        LogisticRegression(max_iter=5000, class_weight="balanced"),
    )
    cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed)
    pred = cross_val_predict(head, X, y, cv=cv)
    classes = sorted(set(y))
    p, r, f, s = precision_recall_fscore_support(y, pred, labels=classes, zero_division=0)
    return {
        "macro_f1": float(f1_score(y, pred, labels=classes, average="macro", zero_division=0)),
        "accuracy": float(np.mean(np.asarray(pred) == np.asarray(y))),
        "per_keystone": {
            c: {"precision": float(p[i]), "recall": float(r[i]), "f1": float(f[i]), "n": int(s[i])}
            for i, c in enumerate(classes)
        },
    }


def report(results, info, n_tracks, timing, smoke):
    tag = "SMOKE TEST -- NOT A RESULT | " if smoke else ""
    out = []
    if smoke:
        out += [
            "=" * 78,
            "SMOKE TEST -- NOT A RESULT. Proves the harness runs end to end; the label",
            "set is not the benchmark set, so these numbers must not be quoted or compared.",
            "=" * 78,
        ]
    unavailable = sum(info["unavailable"].values())
    out += [
        f"{tag}{info['labels']} labelled tracks -> {n_tracks} scored",
        f"{tag}  left out: {info['no_keystone']} no keystone, {info['no_path']} no path, "
        f"{unavailable} on an unmounted drive {dict(info['unavailable']) or ''}, "
        f"{info['missing']} missing on a mounted drive",
    ]
    if info["dropped_keystones"]:
        out.append(f"{tag}  keystones with too few tracks, dropped: {info['dropped_keystones']}")
    out.append(f"{tag}  label sources: {dict(info['sources'])}")
    names = list(results)
    first = results[names[0]]["per_keystone"]
    support = {ks: v["n"] for ks, v in first.items()}
    top = max(support.values()) / max(sum(support.values()), 1)
    out.append(
        f"{tag}  largest keystone is {top:.0%} of the set"
        + ("  (unbalanced: macro-F1 is the number to read)" if top > 0.4 else "")
    )
    out.append("")
    out.append(f"{tag}{'':<22}" + "".join(f"{n:>14}" for n in names))
    out.append(
        f"{tag}{'macro-F1':<22}" + "".join(f"{results[n]['macro_f1']:>14.3f}" for n in names)
    )
    out.append(
        f"{tag}{'accuracy':<22}" + "".join(f"{results[n]['accuracy']:>14.3f}" for n in names)
    )
    out.append(f"{tag}per keystone: precision/recall")
    for ks in sorted(support, key=lambda k: -support[k]):
        cells = "".join(
            f"{results[n]['per_keystone'][ks]['precision']:>8.2f}/"
            f"{results[n]['per_keystone'][ks]['recall']:<5.2f}"
            for n in names
        )
        out.append(f"{tag}  {ks:<16}{support[ks]:>4}{cells}")
    out.append("")
    out.append(
        f"{tag}embedding time (s): "
        + ", ".join(f"{k} {v:.0f}" for k, v in timing.items())
        + "  (only newly embedded tracks; decode is shared)"
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
        "--sources", default=",".join(SOURCE_PRIORITY), help="label sources, in priority order"
    )
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--seconds", type=float, default=60, help="centred cut; 0 = whole track")
    ap.add_argument("--limit", type=int, default=0, help="first N usable tracks only")
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

    labels = load_labels(args.labels, [s.strip() for s in args.sources.split(",")])
    tracks, info = select_tracks(labels, args.folds)
    ref = reference_embeddings(args.db, tracks)
    tracks = {h: v for h, v in tracks.items() if h in ref}
    if args.limit:
        tracks = dict(list(tracks.items())[: args.limit])
    print(f"{len(tracks)} tracks to score; candidates: {', '.join(names)}")

    candidates = []
    load_time = {}
    for n in names:
        t0 = time.perf_counter()
        c = CANDIDATES[n]()
        c.load()
        load_time[n] = time.perf_counter() - t0
        candidates.append(c)
        print(f"  loaded {n} in {load_time[n]:.1f} s")

    t0 = time.perf_counter()
    embs, timing, failed = extract(tracks, candidates, Path(args.work), args.seconds)
    wall = time.perf_counter() - t0
    if failed:
        print(f"  failures: {dict(failed)}")

    # Same tracks for every line: those every candidate embedded.
    hashes = [h for h in tracks if all(h in embs[c.name] for c in candidates)]
    y = [tracks[h][1] for h in hashes]
    small = {ks for ks, n in Counter(y).items() if n < args.folds}
    hashes = [h for h in hashes if tracks[h][1] not in small]
    y = [tracks[h][1] for h in hashes]

    results, cv_time = {}, {}
    for name, table in [(REFERENCE, ref)] + [(c.name, embs[c.name]) for c in candidates]:
        t0 = time.perf_counter()
        results[name] = evaluate(np.stack([table[h] for h in hashes]), y, args.folds)
        cv_time[name] = time.perf_counter() - t0

    print()
    print(report(results, info, len(hashes), timing, args.smoke))
    print(f"load (s): {', '.join(f'{k} {v:.1f}' for k, v in load_time.items())}")
    print(f"cv (s): {', '.join(f'{k} {v:.1f}' for k, v in cv_time.items())}")
    print(f"extraction wall time: {wall:.0f} s")
    if args.out:
        Path(args.out).write_text(
            json.dumps(
                {
                    "smoke_test": args.smoke,
                    "tracks": len(hashes),
                    "seconds": args.seconds,
                    "folds": args.folds,
                    "results": results,
                    "timing_s": {
                        "load": load_time,
                        "embed": dict(timing),
                        "cv": cv_time,
                        "extraction_wall": wall,
                    },
                    "left_out": {
                        **{k: v for k, v in info.items() if k not in ("unavailable", "sources")},
                        "unavailable": dict(info["unavailable"]),
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
