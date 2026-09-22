"""Fit key templates discriminatively instead of by median.

The detector scores key (tonic t, mode m) as corr(pcp, roll(template_m, t)). The
median-profile recipe (Faraldo 2017) picks template_m without ever looking at the
keys it confuses. This fits the same two 12-vectors (plus a per-mode bias) by
maximising the softmax probability of the labelled key over all 24 candidates —
a transposition-equivariant multinomial logistic regression on the cached PCPs,
so it is still "template matching", just with templates that were trained to
separate keys rather than to describe them.

    python tools/train_key_templates.py --dataset giantsteps --variant base \
        --extra "band 25-400 peaks=16" --extra "band 200-1000 peaks=16" \
        --extra "band 1000-5000 peaks=16" --l2 0.001 --write      # the shipped model

Reports k-fold cross-validated MIREX categories, and with --write stores the
templates as the "edm" profile set in src/vibenative/data/key_profiles.json
(``tonality.match`` scores gain_m * pearson + bias_m when the file carries
``mode_score``, which is exactly the trained linear model).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import eval_key  # noqa: E402
from vibenative import tonality  # noqa: E402

OUT = ROOT / "src" / "vibenative" / "data" / "key_profiles.json"
MODES = ("major", "minor")


def _standardise(x: np.ndarray) -> np.ndarray:
    """Per 12-bin block: zero-mean unit-norm, so the dot product with a template
    is the Pearson correlation up to the template's own scale — the same quantity
    ``tonality.match`` computes. Rows may hold several 12-blocks (full + bass)."""
    blocks = []
    for j in range(0, x.shape[1], 12):
        blk = x[:, j:j + 12]
        blk = blk - blk.mean(axis=1, keepdims=True)
        n = np.linalg.norm(blk, axis=1, keepdims=True)
        blocks.append(blk / np.where(n > 0, n, 1.0))
    return np.concatenate(blocks, axis=1)


def _all_rotations(x: np.ndarray) -> np.ndarray:
    """(n, 12, D): row i, rotation t = every 12-block of row i rolled so tonic t
    sits at index 0."""
    def roll(t):
        return np.concatenate([np.roll(x[:, j:j + 12], -t, axis=1) for j in range(0, x.shape[1], 12)], axis=1)
    return np.stack([roll(t) for t in range(12)], axis=1)


def train(pcps: np.ndarray, keys: np.ndarray, l2: float = 1e-2, steps: int = 4000, lr: float = 1.0
          ) -> tuple[np.ndarray, np.ndarray]:
    """Gradient descent on the 24-way softmax. Returns (W (2, 12), b (2,)).
    ``keys`` are ints 0..23 = tonic + 12 * mode_index.
    logit[t, m] = <standardised pcp rolled by t, W[m]> + b[m]; the detector
    scores |W[m]| * pearson(pcp, roll(W[m], t)) + b[m], which is the same thing."""
    X = _standardise(pcps)
    R = _all_rotations(X)  # (n, 12, 12)
    n = X.shape[0]
    W = np.zeros((2, X.shape[1]))
    b = np.zeros(2)
    onehot = np.zeros((n, 24))
    onehot[np.arange(n), keys] = 1.0
    for _ in range(steps):
        logits = np.einsum("ntk,mk->ntm", R, W) + b[None, None, :]  # (n, 12, 2)
        logits = logits.transpose(0, 2, 1).reshape(n, 24)  # index t + 12 m
        logits -= logits.max(axis=1, keepdims=True)
        p = np.exp(logits)
        p /= p.sum(axis=1, keepdims=True)
        g3 = ((p - onehot) / n).reshape(n, 2, 12).transpose(0, 2, 1)  # (n, 12, 2)
        W -= lr * (np.einsum("ntm,ntk->mk", g3, R) + l2 * W)
        b -= lr * g3.sum(axis=(0, 1))
    return W, b


def predict(W: np.ndarray, b: np.ndarray, pcps: np.ndarray) -> np.ndarray:
    R = _all_rotations(_standardise(pcps))
    logits = np.einsum("ntk,mk->ntm", R, W) + b[None, None, :]
    return logits.transpose(0, 2, 1).reshape(len(pcps), 24).argmax(axis=1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="giantsteps")
    ap.add_argument("--variant", default="default")
    ap.add_argument("--extra", action="append", default=[], metavar="VARIANT",
                    help="further PCP variants (e.g. bands) to concatenate; templates become 12*(1+n) wide")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--l2", type=float, default=1e-2)
    ap.add_argument("--write", action="store_true", help="store the templates trained on ALL tracks as the edm profiles")
    args = ap.parse_args()

    index = eval_key.load_index(args.dataset)
    variants = [args.variant, *args.extra]
    for v in variants:
        eval_key.VARIANTS[v] = eval_key.variant_settings(v)
    pcps = eval_key.load_pcps(index, args.dataset, verbose=False)
    ids = [h for h in sorted(index) if all((h, v) in pcps for v in variants)]
    X = np.concatenate([np.array([eval_key.gated(pcps[(h, v)]) for h in ids]) for v in variants], axis=1)
    y = np.array([tonality.KEY_NAMES.index(index[h]["key"]) + 12 * MODES.index(index[h]["scale"]) for h in ids])

    rng = np.random.default_rng(0)
    order = rng.permutation(len(ids))
    folds = np.array_split(order, args.folds)
    cats = {}
    for k, test in enumerate(folds):
        train_idx = np.concatenate([f for j, f in enumerate(folds) if j != k])
        W, b = train(X[train_idx], y[train_idx], l2=args.l2)
        pred = predict(W, b, X[test])
        for i, p in zip(test, pred):
            c = eval_key.category((tonality.KEY_NAMES[p % 12], MODES[p // 12]),
                                  (index[ids[i]]["key"], index[ids[i]]["scale"]))
            cats[c] = cats.get(c, 0) + 1
    from collections import Counter
    eval_key.report(f"trained {args.folds}-fold", Counter(cats))

    if args.write:
        W, b = train(X, y, l2=args.l2)
        doc = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
        doc["model"] = {
            "about": "Linear key scorer trained by tools/train_key_templates.py: a transposition-"
                     "equivariant 24-way softmax over the per-block standardised PCPs of the listed "
                     "frequency-band blocks. weights[mode] is 12 per block, index 0 = tonic.",
            "fitted": date.today().isoformat(), "tracks": len(ids), "labels": args.dataset, "l2": args.l2,
            "cross_validated": {"folds": args.folds, **cats},
            "blocks": [eval_key.variant_settings(v) for v in variants],
            "block_names": variants,
            "weights": {m: [round(float(v), 5) for v in W[i]] for i, m in enumerate(MODES)},
            "bias": {m: round(float(b[i]), 5) for i, m in enumerate(MODES)},
        }
        OUT.write_text(json.dumps(doc, indent=1) + chr(10), encoding="utf-8")
        print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
