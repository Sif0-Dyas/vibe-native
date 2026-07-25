"""ONNX Runtime engine: EffNet embedder + Discogs-400 head (+ TempoCNN).

Contract (Phase 1):

    get_engine() -> {"labels": [400 strs], "embedder": fn, "classifier": fn}
        embedder(audio16) -> (n_frames, 1280) float32   [uses frontend_mel]
        classifier(embeddings) -> (n_frames, 400) float32 probabilities
    Provider order: ["DmlExecutionProvider", "CPUExecutionProvider"];
    log which engaged. Mirror Vibe_Identify's analysis.get_engine() shape so
    Phase 4's port is a drop-in.

Models load from models/*.onnx (produced by tools/convert_models.py):
    effnet.onnx     melspectrogram[B,128,96] -> embeddings[B,1280]  (embedder)
    genre400.onnx   embeddings[B,1280]       -> [B,400] sigmoid      (classifier)

Phase-1 scope: sessions, provider logging, labels, and classifier() are live.
embedder() raises NotImplementedError — the audio->mel-patch step is the Phase-2
mel frontend (frontend_mel.py); the effnet.onnx session itself is loaded here so
the embedder path is one function body away once the frontend lands.
"""

import json
import logging
from pathlib import Path

import numpy as np
import onnxruntime as ort

from . import frontend_mel
from .paths import models_dir

log = logging.getLogger(__name__)

MODELS = models_dir()  # exe-adjacent models/ in a packaged build, else <repo>/models
LABELS_JSON = MODELS / "genre_discogs400-discogs-effnet-1.json"

# Preferred execution providers, highest priority first. DirectML (the RTX 5070)
# when present; CPU otherwise. Installing onnxruntime-directml makes the DML EP
# available; a plain onnxruntime install would only offer CPU (both must not be
# installed at once — they conflict).
PROVIDER_ORDER = ["DmlExecutionProvider", "CPUExecutionProvider"]

# Cap how many mel patches are fed to effnet.onnx in a single Session.run. A long
# track yields hundreds of patches; running them all at once makes the DirectML EP
# pre-allocate activation memory for the WHOLE batch, which ballooned to ~20 GB on
# an 8-minute track and OOM-crashed the process mid batch-scan. 64 matches Essentia's
# own TensorflowPredictEffnetDiscogs batchSize default and keeps peak memory flat
# regardless of track length. Per-patch inference is independent, so chunking is exact.
EMB_BATCH = 64

_engine: dict = {}


def _session(path: Path) -> ort.InferenceSession:
    if not path.exists():
        raise FileNotFoundError(f"{path.name} missing — run tools/convert_models.py")
    available = set(ort.get_available_providers())
    providers = [p for p in PROVIDER_ORDER if p in available] or ["CPUExecutionProvider"]
    return ort.InferenceSession(str(path), providers=providers)


def get_engine() -> dict:
    """Build (once) and return {labels, embedder, classifier}. Cached."""
    if _engine:
        return _engine

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
        if "DmlExecutionProvider" in available:
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

    _engine.update(
        {
            "labels": labels,
            "embedder": embedder,
            "classifier": classifier,
            # exposed for tests / later phases; not part of the public contract
            "_provider": engaged,
            "_classifier_session": clf,
            "_embedder_session": emb,
        }
    )
    return _engine
