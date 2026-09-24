"""ONNX Runtime engine: EffNet embedder + Discogs-400 head, and the one
execution-provider policy every ONNX session in the app uses (TempoCNN included).

Contract:

    get_engine() -> {"labels": [400 strs], "embedder": fn, "classifier": fn}
        embedder(audio16) -> (n_frames, 1280) float32   [uses frontend_mel]
        classifier(embeddings) -> (n_frames, 400) float32 probabilities
    Built once, under a lock, and cached; logs which provider engaged.

    resolve_providers() -> the provider list to hand InferenceSession. CPU by
        default; DirectML first only when VIBE_PROVIDER=gpu (see provider_order).

Models load from models/*.onnx (produced by tools/convert_models.py):
    effnet.onnx     melspectrogram[B,128,96] -> embeddings[B,1280]  (embedder)
    genre400.onnx   embeddings[B,1280]       -> [B,400] sigmoid      (classifier)
"""

import json
import logging
import os
import threading
from pathlib import Path

import numpy as np
import onnxruntime as ort

from . import frontend_mel
from .paths import models_dir

log = logging.getLogger(__name__)

MODELS = models_dir()  # exe-adjacent models/ in a packaged build, else <repo>/models
LABELS_JSON = MODELS / "genre_discogs400-discogs-effnet-1.json"

# Execution-provider policy -- the only one in the app; tempo.py uses it too.
# Installing onnxruntime-directml makes the DML EP
# available; a plain onnxruntime install would only offer CPU (both must not be
# installed at once — they conflict).
# CPU is the default, deliberately -- DirectML is opt-in via VIBE_PROVIDER=gpu.
#
# The DML path faults inside the NVIDIA D3D driver part-way through a large batch
# scan: 0xc0000005 in nvwgf2umx.dll, three times, at a byte-identical fault
# offset (0x6f8efa) each time. It is one deterministic driver bug, and an access
# violation inside a driver DLL cannot be caught from Python -- the process dies
# outright, mid-scan, with no traceback.
#
# What makes CPU the right default rather than a grudging fallback is the
# measured cost. On a Ryzen 7 9800X3D, same models and same weights:
#
#     2.8-minute track   GPU 1.96s   CPU 2.04s   (+4%)
#     8.4-minute track   GPU 5.54s   CPU 5.91s   (+7%)
#
# Trading a ~5% speedup for a scan that survives is not a close call. Set
# VIBE_PROVIDER=gpu to opt back in -- worth retrying after an NVIDIA driver
# update, since the fault is theirs, not ours.
_GPU_VALUES = ("gpu", "dml", "directml", "dmlexecutionprovider")


def provider_order() -> list[str]:
    """Preferred execution providers, highest priority first, per VIBE_PROVIDER."""
    if os.environ.get("VIBE_PROVIDER", "").strip().lower() in _GPU_VALUES:
        return ["DmlExecutionProvider", "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]


def resolve_providers() -> list[str]:
    """provider_order() narrowed to what this onnxruntime build offers; CPU if none."""
    available = set(ort.get_available_providers())
    return [p for p in provider_order() if p in available] or ["CPUExecutionProvider"]


# Cap how many mel patches are fed to effnet.onnx in a single Session.run. A long
# track yields hundreds of patches; running them all at once makes the DirectML EP
# pre-allocate activation memory for the WHOLE batch, which ballooned to ~20 GB on
# an 8-minute track and OOM-crashed the process mid batch-scan. 64 matches Essentia's
# own TensorflowPredictEffnetDiscogs batchSize default and keeps peak memory flat
# regardless of track length. Per-patch inference is independent, so chunking is exact.
EMB_BATCH = 64

_engine: dict = {}
# Guards the one-time build. Without it a cold /batch (three workers) had every
# worker see an empty _engine and build its own pair of sessions -- triple the
# load time and memory, and the losers' sessions dropped while possibly in use.
# Double-checked: the unlocked fast path costs nothing once the engine exists.
_build_lock = threading.Lock()


def _session(path: Path) -> ort.InferenceSession:
    if not path.exists():
        raise FileNotFoundError(f"{path.name} missing — run tools/convert_models.py")
    return ort.InferenceSession(str(path), providers=resolve_providers())


def get_engine() -> dict:
    """Build (once) and return {labels, embedder, classifier}. Cached."""
    if _engine:
        return _engine
    with _build_lock:
        if not _engine:  # another thread may have built it while we waited
            _engine.update(_build())
    return _engine


def _build() -> dict:
    labels = json.loads(LABELS_JSON.read_text(encoding="utf-8"))["classes"]
    if len(labels) != 400:
        raise ValueError(f"expected 400 labels, got {len(labels)} from {LABELS_JSON.name}")

    clf = _session(MODELS / "genre400.onnx")
    emb = _session(MODELS / "effnet.onnx")

    engaged = clf.get_providers()[0]
    available = ort.get_available_providers()
    log.info("ONNX engine ready — execution provider: %s (available: %s)", engaged, available)
    # CPU fallback must be LOUD: if the DirectML EP is available but didn't engage, or
    # isn't available at all in a build that should have it, say so plainly rather than
    # silently running ~10x slower on CPU (esp. a packaged build with a missing DLL).
    if "DmlExecutionProvider" not in engaged:
        if provider_order() == ["CPUExecutionProvider"]:
            # CPU is the configured default, not a failure -- see provider_order.
            # Warning here every launch would train you to ignore the warnings
            # that do matter, like a packaged build with missing DLLs below.
            log.info(
                "Running on CPU by design (measured ~5%% slower than DirectML here, and the "
                "DML path faults in the NVIDIA driver mid-scan). Set VIBE_PROVIDER=gpu to use "
                "the GPU."
            )
        elif "DmlExecutionProvider" in available:
            log.warning(
                "GPU (DirectML) is AVAILABLE but the engine engaged %s instead — running on CPU.",
                engaged,
            )
        else:
            log.warning(
                "GPU (DirectML) NOT available — running on CPU (~10x slower). In a packaged "
                "build this usually means DirectML.dll / onnxruntime DLLs weren't collected; "
                "check the bundle's onnxruntime/capi/ folder.",
            )

    clf_in = clf.get_inputs()[0].name  # serving_default_model_Placeholder:0
    clf_out = clf.get_outputs()[0].name  # PartitionedCall:0 (sigmoid probabilities)

    def classifier(embeddings) -> np.ndarray:
        """(n_frames, 1280) embeddings -> (n_frames, 400) sigmoid probabilities.

        The graph's final Sigmoid is baked into genre400.onnx, so these are already
        probabilities — do NOT apply another activation (see CONVERSION_NOTES)."""
        x = np.asarray(embeddings, dtype=np.float32)
        if x.ndim == 1:
            x = x[None, :]
        return np.asarray(clf.run([clf_out], {clf_in: x})[0], dtype=np.float32)

    emb_in = emb.get_inputs()[0].name  # "melspectrogram" [B,128,96]

    def embedder(audio16, hop_frames: int = frontend_mel.PATCH_HOP_COARSE) -> np.ndarray:
        """16 kHz mono audio -> (n_patches, 1280) float32 embeddings.

        decode is the caller's job (decode.decode_16k_mono); this runs the Essentia-
        matched mel frontend -> 128x96 patches -> effnet.onnx 'embeddings'. hop 62 is
        coarse (the oracle's setting); a smaller hop_frames drives the app's fine mode."""
        mel = frontend_mel.melspectrogram(audio16)
        p = frontend_mel.patches(mel, hop_frames)
        if len(p) == 0:
            return np.zeros((0, 1280), dtype=np.float32)
        p = p.astype(np.float32)
        # One Session.run per EMB_BATCH patches, not one giant run over the whole
        # track — see EMB_BATCH: a long track fed all at once OOM'd the DML EP.
        outs = [
            emb.run(["embeddings"], {emb_in: p[i : i + EMB_BATCH]})[0]
            for i in range(0, len(p), EMB_BATCH)
        ]
        return np.asarray(np.concatenate(outs, axis=0), dtype=np.float32)

    return {
        "labels": labels,
        "embedder": embedder,
        "classifier": classifier,
        # exposed for tests / later phases; not part of the public contract
        "_provider": engaged,
        "_classifier_session": clf,
        "_embedder_session": emb,
    }
