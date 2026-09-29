"""Model plumbing (native ONNX EffNet + Discogs-400 head, custom head) and the
per-track analysis pipeline: genre styles, BPM, key, and the waveform envelope.

Phase 4 engine swap: the genre / tempo / key internals now run on the native
ONNX engine (``onnx_engine`` + ``frontend_mel`` + ``decode`` + ``tempo`` +
``tonality``) instead of Essentia, BEHIND the same function signatures and the same
payload shape -- everything downstream (routes, DB, frontend) is unable to tell.
Every engine -- decode, the genre models, tempo, key -- comes from
``fake_engine.engines()``: the real ones, or stand-ins with no ffmpeg or
models, so the pipeline below has one path. The onnxruntime-backed modules are
imported only when a real engine is asked for, so the app still imports on CI
without onnxruntime installed -- exactly as the old code deferred ``essentia``.
"""

import threading
from pathlib import Path

import numpy as np

from .config import log
from .fake_engine import engines
from .settings import current

# The embedder/classifier are shared inference sessions. ONNX Runtime sessions ARE
# thread-safe for concurrent Session.run(), so this lock is not required for
# correctness the way the old shared, non-thread-safe TF instances were; it is kept
# for this phase to preserve identical serialization behaviour. Relaxing it (to let
# /batch workers infer concurrently) is a later optimization with its own test.
_lock = threading.Lock()

_engine_lock = threading.Lock()  # guards the one-time custom-head load


def get_engine():
    """Return ``{labels, embedder, classifier}`` for the genre engine.

    Delegates to the active engines (``fake_engine.engines().genre``: normally
    ``onnx_engine.get_engine()``, built + cached once there). Mirrors
    the old Essentia ``get_engine()`` contract exactly, so every caller is a
    drop-in::

        eng["embedder"](audio16)       -> (n_patches, 1280) float32 embeddings
        eng["classifier"](embeddings)  -> (n_patches, 400)  float32 probabilities
        eng["labels"]                  -> the 400 Discogs-400 style labels
    """
    return engines().genre()


# --- optional custom head (trained with train_head.py) ----------------------
# (path, head) for the last custom_head_path looked at; head is None when that file
# is missing or unloadable. Keyed by path so a Settings with another model_dir
# (a test's) doesn't get the head loaded for the previous one.
_custom = (None, None)


def get_custom_head():
    """Load the settings' custom_head.npz once, if it exists. Guarded so the
    concurrent /batch workers that call this (via custom_predict) load it once."""
    global _custom
    path = current().custom_head_path
    if _custom[0] == path:
        return _custom[1]
    with _engine_lock:
        if _custom[0] == path:  # loaded while we waited on the lock
            return _custom[1]
        head = None
        if path.exists():
            try:
                d = np.load(path, allow_pickle=False)
                head = {k: d[k] for k in ("W1", "b1", "W2", "b2", "mu", "sigma")}
                head["labels"] = [str(x) for x in d["labels"]]
                acc = float(d["val_acc"]) if "val_acc" in d else None
                log.info(
                    "custom head loaded: %s%s",
                    head["labels"],
                    f"  (val acc {acc:.0%})" if acc else "",
                )
            except Exception:
                head = None
                log.warning("could not load custom head", exc_info=True)
        _custom = (path, head)  # published whole: don't try this path again either way
        return head


def custom_predict(embeddings):
    """Forward pass of the trained NumPy head; track-level probabilities."""
    head = get_custom_head()
    if head is None:
        return None
    X = (np.asarray(embeddings) - head["mu"]) / head["sigma"]
    h = np.maximum(X @ head["W1"] + head["b1"], 0.0)
    logits = h @ head["W2"] + head["b2"]
    e = np.exp(logits - logits.max(axis=1, keepdims=True))
    probs = (e / e.sum(axis=1, keepdims=True)).mean(axis=0)  # avg over frames
    order = np.argsort(probs)[::-1]
    return [{"style": head["labels"][int(i)], "score": round(float(probs[i]), 4)} for i in order]


# Tag reading lives in metadata.py (ffprobe, not the GPL mutagen -- see that
# module and docs/PROVENANCE.md). Re-exported here because this is where the rest
# of the app has always imported it from.
from .metadata import read_tags, read_title  # noqa: E402,F401  (public re-export)

CAMELOT = {  # (key, scale) -> Camelot wheel position; enharmonics included
    ("C", "major"): "8B",
    ("G", "major"): "9B",
    ("D", "major"): "10B",
    ("A", "major"): "11B",
    ("E", "major"): "12B",
    ("B", "major"): "1B",
    ("F#", "major"): "2B",
    ("Gb", "major"): "2B",
    ("C#", "major"): "3B",
    ("Db", "major"): "3B",
    ("G#", "major"): "4B",
    ("Ab", "major"): "4B",
    ("D#", "major"): "5B",
    ("Eb", "major"): "5B",
    ("A#", "major"): "6B",
    ("Bb", "major"): "6B",
    ("F", "major"): "7B",
    ("A", "minor"): "8A",
    ("E", "minor"): "9A",
    ("B", "minor"): "10A",
    ("F#", "minor"): "11A",
    ("Gb", "minor"): "11A",
    ("C#", "minor"): "12A",
    ("Db", "minor"): "12A",
    ("G#", "minor"): "1A",
    ("Ab", "minor"): "1A",
    ("D#", "minor"): "2A",
    ("Eb", "minor"): "2A",
    ("A#", "minor"): "3A",
    ("Bb", "minor"): "3A",
    ("F", "minor"): "4A",
    ("C", "minor"): "5A",
    ("G", "minor"): "6A",
    ("D", "minor"): "7A",
}

WAVE_BINS = 720  # amplitude envelope resolution; higher = finer waveform detail


def waveform_peaks(audio, bins=WAVE_BINS):
    """Downsample |audio| into `bins` peak values in 0..1 for drawing."""
    a = np.abs(np.asarray(audio))
    if a.size == 0:
        return [0.0] * bins
    edges = np.linspace(0, a.size, bins + 1, dtype=int)
    peaks = np.array(
        [a[edges[i] : edges[i + 1]].max() if edges[i + 1] > edges[i] else 0.0 for i in range(bins)]
    )
    top = peaks.max()
    if top > 0:
        peaks = peaks / top
    return [round(float(v), 3) for v in peaks]


WAVE_MM_BINS = 1600  # resolution of the DAW-style min/max/rms waveform


def waveform_minmax(audio, bins=WAVE_MM_BINS):
    """A DAW-style waveform: per time-bin minimum, maximum and RMS of the signal,
    normalized so the loudest peak reaches full scale. min/max give the peak
    outline (both rails from a center line), rms the loudness core. Returns
    ``{'bins', 'min', 'max', 'rms'}`` with each list in [-1, 1] (rms in [0, 1])."""
    a = np.asarray(audio, dtype=np.float32).ravel()
    empty = [0.0] * bins
    if a.size == 0:
        return {"bins": bins, "min": empty, "max": empty[:], "rms": empty[:]}
    edges = np.linspace(0, a.size, bins + 1, dtype=int)
    mn = np.zeros(bins, np.float32)
    mx = np.zeros(bins, np.float32)
    rms = np.zeros(bins, np.float32)
    for i in range(bins):
        seg = a[edges[i] : edges[i + 1]]
        if seg.size:
            mn[i], mx[i] = seg.min(), seg.max()
            rms[i] = np.sqrt(np.mean(seg * seg))
    peak = float(max(np.abs(mn).max(), np.abs(mx).max())) or 1.0
    return {
        "bins": bins,
        "min": [round(float(v / peak), 3) for v in mn],
        "max": [round(float(v / peak), 3) for v in mx],
        "rms": [round(float(v / peak), 3) for v in rms],
    }


def load_samples_for_waveform(path):
    """Decode an audio file to a mono float array for waveform rendering, at a low
    sample rate (fast; an envelope needs no fidelity)."""
    return engines().decode_mono(path, 11025)


def frame_topk(preds, labels, k=6):
    """Per-frame top-k predictions as [style, score] pairs -- the data the
    hysteresis and sibling-merge lenses need (winner plus near-misses)."""
    preds = np.asarray(preds)
    if preds.ndim != 2 or preds.shape[0] == 0:
        return []
    kk = min(k, preds.shape[1])
    out = []
    for row in preds:
        idx = np.argpartition(row, -kk)[-kk:]
        idx = idx[np.argsort(row[idx])[::-1]]
        out.append([[labels[int(i)].split("---", 1)[1], round(float(row[i]), 3)] for i in idx])
    return out


def salience_read(preds, audio16, labels, topk=8):
    """
    Weighted overall-genre read that mimics how an experienced listener collapses
    a whole track to one identity. Each ~2s frame's vote is scaled by three signals:
      energy     -- loud, dense sections (drops, choruses) count most; silence ~0
      confidence -- frames where one style clearly wins count more than ambiguous ones
      recurrence -- genres that keep coming back outweigh one-off moments
    Returns [{style, score}] over the salient styles (scores sum to <=1; the
    remainder is the incidental tail, shown as "Other" in the UI).
    """
    preds = np.asarray(preds)
    n = preds.shape[0]
    if n == 0:
        return []
    a = np.asarray(audio16, dtype=np.float32)

    # per-frame RMS energy, aligned to the n genre frames, normalized to 0..1
    edges = np.linspace(0, len(a), n + 1, dtype=int)
    energy = np.array(
        [
            float(np.sqrt(np.mean(a[edges[i] : edges[i + 1]] ** 2)))
            if edges[i + 1] > edges[i]
            else 0.0
            for i in range(n)
        ]
    )
    if energy.max() > 0:
        energy = energy / energy.max()

    # confidence = how peaked each frame's distribution is, relative to the track
    conf = preds.max(axis=1)
    conf_n = conf / conf.max() if conf.max() > 0 else conf

    # recurrence = how often each frame's winning genre wins across the whole track
    winners = preds.argmax(axis=1)
    counts = np.bincount(winners, minlength=preds.shape[1]).astype(np.float32)
    freq = counts / counts.sum()
    rec = freq[winners]
    rec_n = rec / rec.max() if rec.max() > 0 else rec

    # combine: energy can fully zero a silent intro; the other two modulate in [0.4,1]
    salience = energy * (0.4 + 0.6 * conf_n) * (0.4 + 0.6 * rec_n)

    tally = {}
    for i in range(n):
        g = labels[int(winners[i])].split("---", 1)[1]
        tally[g] = tally.get(g, 0.0) + float(salience[i])
    total = sum(tally.values()) or 1.0
    ranked = sorted(tally.items(), key=lambda kv: -kv[1])[:topk]
    return [{"style": g, "score": v / total} for g, v in ranked]


def _decode_and_infer(path: Path):
    """Decode the file and run the (locked) genre inference.

    Returns ``(audio16, audio44, embeddings, preds)``. One decode serves both rates
    (``decode.decode_both``: one ffprobe + one ffmpeg per track, was two of each);
    only the shared inference pass is serialized under ``_lock``, so the decode
    stays parallel across workers."""
    eng = get_engine()

    # 16 kHz for the genre model, 44.1 kHz for BPM/key -- from one native-rate decode
    audio16, audio44 = engines().decode_both(path)
    # serialize the one shared inference pass; decode/BPM/key stay parallel.
    with _lock:
        embeddings = eng["embedder"](audio16)
        preds = eng["classifier"](embeddings)
    return audio16, audio44, embeddings, preds


def _musical_features(audio44) -> dict:
    """BPM, key/scale/Camelot, duration, and waveform envelopes from the 44.1 kHz
    signal. BPM and key are best-effort (None on failure).

    Engine swap (Phase 4): BPM from the native TempoCNN (``tempo.estimate``,
    resamples 44.1k->11025 itself) and key from our own detector
    (``tonality.estimate`` at 44100; see docs/KEY_SPEC.md). Same dict shape as
    before. Note ``bpm``
    stays a plain float and ``bpm_confidence`` a plain float; the confidence is now
    the TempoCNN mean peak softmax (0..1) rather than RhythmExtractor2013's (~0..5)
    -- a value-scale change, not a shape change."""
    eng = engines()
    duration = float(len(audio44)) / 44100.0

    bpm = bpm_conf = None
    try:
        bpm_val, conf = eng.tempo(audio44, 44100)
        if bpm_val:  # 0.0 == "too short / no estimate" -> leave as None
            bpm, bpm_conf = float(bpm_val), float(conf)
    except Exception:  # nosec B110  # BPM extraction is best-effort; None on failure is fine
        pass

    key = scale = camelot = None
    key_strength = None
    try:
        k, s, strength = eng.key(audio44, 44100)
        key, scale, key_strength = str(k), str(s), float(strength)
        camelot = CAMELOT.get((key, scale))
    except Exception:  # nosec B110  # key extraction is best-effort; None on failure is fine
        pass

    return {
        "bpm": round(bpm, 1) if bpm else None,
        "bpm_confidence": bpm_conf,
        "key": key,
        "scale": scale,
        "camelot": camelot,
        "key_strength": key_strength,
        "duration": duration,
        "waveform": waveform_peaks(audio44),
        "wave": waveform_minmax(audio44),  # DAW-style; cached, not stored in payload
    }


def _assemble(labels, audio16, embeddings, preds, features) -> dict:
    """Build the analysis payload from raw predictions + embeddings: ranked styles,
    per-frame segments, the salience read, top-k frames, custom-head scores, and the
    mean embedding, spliced with the musical ``features`` dict. Takes ``labels``
    explicitly (no ``get_engine()``) so it runs on synthetic inputs without models."""
    mean = np.mean(preds, axis=0)
    order = np.argsort(mean)[::-1]
    styles = []
    for i in order[:8]:
        parent, child = labels[i].split("---", 1)
        styles.append({"parent": parent, "style": child, "score": float(mean[i])})

    # per-frame winner -> which genre dominates each ~2s patch of the track
    frame_winners = np.argmax(preds, axis=1)
    segments = [labels[int(i)].split("---", 1)[1] for i in frame_winners]

    # salience-weighted overall identity (energy x confidence x recurrence)
    salience = salience_read(preds, audio16, labels)

    # per-frame top-k predictions (for hysteresis / sibling-merge lenses)
    frames = frame_topk(preds, labels)

    # custom head (if trained) scores the SAME embeddings -- no extra audio work
    custom = custom_predict(embeddings)

    return {
        "styles": styles,
        "segments": segments,
        "salience": salience,
        "frames": frames,
        "custom": custom,
        "bpm": features["bpm"],
        "bpm_confidence": features["bpm_confidence"],
        "key": features["key"],
        "scale": features["scale"],
        "camelot": features["camelot"],
        "key_strength": features["key_strength"],
        "duration": features["duration"],
        "waveform": features["waveform"],
        "wave": features["wave"],  # DAW-style; cached, not stored in payload
        "emb_mean": [float(x) for x in np.mean(embeddings, axis=0)],
    }


def analyze(path: Path) -> dict:
    """Genre styles + BPM, key, duration, and a waveform envelope for one file."""
    # Decode + locked inference, then musical features, then the payload assembly
    # (see _decode_and_infer / _musical_features / _assemble). The same pipeline
    # in every mode: only the engines under it differ (fake_engine.engines).
    audio16, audio44, embeddings, preds = _decode_and_infer(path)
    features = _musical_features(audio44)
    labels = get_engine()["labels"]
    return _assemble(labels, audio16, embeddings, preds, features)


# The coarse genre pass hops the embedder by frontend_mel.PATCH_HOP_COARSE mel
# frames (~2.0s per patch); a 32-frame hop (~0.5s) gives ~4x overlap and thus ~4x
# finer genre-boundary resolution -- at ~4x the inference cost. In the native
# engine the hop is just a parameter of the mel frontend (embedder(hop_frames=...)),
# so "fine mode" needs no separate model instance.
FINE_HOP = 32
FINE_HOP_SECONDS = round(FINE_HOP * 256 / 16000, 2)  # 256-sample mel hop @ 16 kHz


def refine_segments(path: Path):
    """Re-run one track with overlapping patches -> (dense segments, dense frames)."""
    eng = get_engine()
    audio16 = engines().decode_16k_mono(path)
    # serialize the one shared inference pass; the fine hop is a frontend parameter.
    with _lock:
        emb = eng["embedder"](audio16, hop_frames=FINE_HOP)
        preds = eng["classifier"](emb)
    winners = np.argmax(preds, axis=1)
    labels = eng["labels"]
    segments = [labels[int(i)].split("---", 1)[1] for i in winners]
    return segments, frame_topk(preds, labels)


def build_payload(filename, filepath, title, tags, result):
    """Shared response shape for /analyze and /batch. emb_mean is stored in the
    DB, not sent to the client (1280 floats the frontend doesn't need)."""
    styles = [s for s in result["styles"] if s["score"] >= 0.02][:5] or result["styles"][:1]
    return {
        "filename": filename,
        "filepath": filepath,
        "title": title,
        "tags": tags,
        "styles": [
            {"parent": s["parent"], "style": s["style"], "score": round(s["score"], 4)}
            for s in styles
        ],
        "salience": result.get("salience"),
        "frames": result.get("frames"),
        "bpm": result.get("bpm"),
        "bpm_confidence": result.get("bpm_confidence"),
        "key": result.get("key"),
        "scale": result.get("scale"),
        "camelot": result.get("camelot"),
        "key_strength": result.get("key_strength"),
        "duration": result.get("duration"),
        "waveform": result.get("waveform"),
        "segments": result.get("segments"),
        "custom": result.get("custom"),
    }
