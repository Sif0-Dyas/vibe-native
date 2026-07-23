"""ONNX Runtime engine: EffNet embedder + Discogs-400 head (+ TempoCNN).

Contract (Phase 1):

    get_engine() -> {"labels": [400 strs], "embedder": fn, "classifier": fn}
        embedder(audio16) -> (n_frames, 1280) float32   [uses frontend_mel]
        classifier(embeddings) -> (n_frames, 400) float32 probabilities
    Provider order: ["DmlExecutionProvider", "CPUExecutionProvider"];
    log which engaged. Mirror Vibe_Identify's analysis.get_engine() shape so
    Phase 4's port is a drop-in.

Models load from models/*.onnx (produced by tools/convert_models.py).
Tensor names for conversion are in PROJECT_PLAN.md "Risks".
"""
