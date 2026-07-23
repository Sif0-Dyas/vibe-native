"""Phase-1 acceptance: converted ONNX models reproduce oracle predictions.

Feed each oracle track's STORED embeddings through genre400.onnx and assert the
per-frame probabilities' mean top-5 styles/scores match the oracle's recorded
styles (tolerance 1e-3 on scores). This isolates model-conversion correctness
from the (later) mel frontend. Plus a TempoCNN structural check (loads, correct
in/out shapes) — full tempo validation is Phase 3.

Skips with a clear reason on a fresh clone (no converted models / no oracle).
"""

import json
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
ORACLE = ROOT / "oracle"
TOL = 1e-3

_have_genre = (MODELS / "genre400.onnx").exists() and (ORACLE / "index.json").exists()
_have_tempo = (MODELS / "tempocnn.onnx").exists()


@pytest.mark.skipif(
    not _have_genre,
    reason="need models/genre400.onnx + oracle/ (run tools/convert_models.py; Phase 0/1)",
)
def test_genre_head_matches_oracle():
    from vibenative.onnx_engine import get_engine

    eng = get_engine()
    labels, classifier = eng["labels"], eng["classifier"]
    index = json.loads((ORACLE / "index.json").read_text())

    tested, mismatches = 0, []
    for h, meta in index.items():
        npz = ORACLE / f"{h}.npz"
        if not npz.exists():
            continue
        embeddings = np.load(npz)["embeddings"]  # (n_frames, 1280)
        mean = classifier(embeddings).mean(axis=0)  # (400,)
        top5 = np.argsort(mean)[::-1][:5]
        mine = [(*labels[i].split("---", 1), float(mean[i])) for i in top5]
        oracle = [(s["parent"], s["style"], s["score"]) for s in meta["styles"]]

        tested += 1
        for (mp, ms, msc), (op, os_, osc) in zip(mine, oracle):
            if (mp, ms) != (op, os_) or abs(msc - osc) > TOL:
                mismatches.append(
                    f"{Path(meta['file']).name}: mine={ms}={msc:.5f}  "
                    f"oracle={os_}={osc:.5f}  |Δ|={abs(msc - osc):.2e}"
                )

    assert tested >= 10, f"expected >=10 oracle tracks with embeddings, tested {tested}"
    assert not mismatches, (
        f"converted genre head diverges from the oracle ({len(mismatches)} rows, tol {TOL}):\n"
        + "\n".join(mismatches[:25])
    )


@pytest.mark.skipif(
    not _have_tempo, reason="need models/tempocnn.onnx (run tools/convert_models.py)"
)
def test_tempocnn_structural():
    """TempoCNN loads and has the expected mel-in / 256-tempo-class-out shape.
    (Numeric BPM validation against the oracle is Phase 3.)"""
    import onnxruntime as ort

    sess = ort.InferenceSession(
        str(MODELS / "tempocnn.onnx"), providers=["CPUExecutionProvider"]
    )
    (inp,), (out,) = sess.get_inputs(), sess.get_outputs()

    # Static shape: input is [batch, 40 mel, time, 1 channel]; output [batch, 256].
    in_dims = [d if isinstance(d, int) else None for d in inp.shape]
    assert len(in_dims) == 4 and in_dims[1] == 40 and in_dims[3] == 1, inp.shape

    # A dummy forward pass yields one 256-way tempo distribution per item.
    dummy = np.zeros((1, 40, 256, 1), dtype=np.float32)
    y = sess.run([out.name], {inp.name: dummy})[0]
    assert y.shape == (1, 256), f"unexpected TempoCNN output shape {y.shape}"
