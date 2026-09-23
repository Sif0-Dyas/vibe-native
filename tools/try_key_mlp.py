"""Experiment: does a nonlinear scorer beat the linear templates?

Same transposition-equivariant setup as tools/train_key_templates.py — each of
the 24 (tonic, mode) hypotheses is scored from the feature vector rotated so the
candidate tonic is at index 0 — but the scorer is a one-hidden-layer MLP shared
across rotations instead of a dot product. If this does not win clearly, the
linear model stays and this file is just the record of the experiment.

    python tools/try_key_mlp.py --dataset both --hidden 16
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import eval_key  # noqa: E402
import train_key_templates as TKT  # noqa: E402
from vibenative import tonality  # noqa: E402

MODES = TKT.MODES


def train_mlp(X, y, hidden=16, steps=3000, lr=0.5, l2=1e-4, seed=0):
    """score[t, m] = tanh(R[t] @ V + c) @ U[:, m] + d[m], fitted by Adam-free SGD
    on the same 24-way softmax."""
    R = TKT._all_rotations(TKT._standardise(X))  # (n, 12, D)
    n, _, D = R.shape
    rng = np.random.default_rng(seed)
    V = rng.normal(0, 1.0 / np.sqrt(D), (D, hidden))
    c = np.zeros(hidden)
    U = rng.normal(0, 1.0 / np.sqrt(hidden), (hidden, 2))
    d = np.zeros(2)
    onehot = np.zeros((n, 24))
    onehot[np.arange(n), y] = 1.0
    for step in range(steps):
        H = np.tanh(np.einsum("ntd,dh->nth", R, V) + c)  # (n, 12, H)
        scores = np.einsum("nth,hm->ntm", H, U) + d  # (n, 12, 2)
        flat = scores.transpose(0, 2, 1).reshape(n, 24)
        flat = flat - flat.max(axis=1, keepdims=True)
        p = np.exp(flat)
        p /= p.sum(axis=1, keepdims=True)
        g3 = ((p - onehot) / n).reshape(n, 2, 12).transpose(0, 2, 1)  # (n, 12, 2)
        gU = np.einsum("ntm,nth->hm", g3, H) + l2 * U
        gd = g3.sum(axis=(0, 1))
        gH = np.einsum("ntm,hm->nth", g3, U) * (1.0 - H * H)
        gV = np.einsum("nth,ntd->dh", gH, R) + l2 * V
        gc = gH.sum(axis=(0, 1))
        U -= lr * gU; d -= lr * gd; V -= lr * gV; c -= lr * gc
    return V, c, U, d


def predict_mlp(model, X):
    V, c, U, d = model
    R = TKT._all_rotations(TKT._standardise(X))
    H = np.tanh(np.einsum("ntd,dh->nth", R, V) + c)
    scores = np.einsum("nth,hm->ntm", H, U) + d
    return scores.transpose(0, 2, 1).reshape(len(X), 24).argmax(axis=1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="both")
    ap.add_argument("--hidden", type=int, nargs="+", default=[8, 16, 32])
    ap.add_argument("--steps", type=int, default=3000)
    ap.add_argument("--l2", type=float, default=1e-4)
    ap.add_argument("--folds", type=int, default=5)
    args = ap.parse_args()

    variants = ["base", "band 25-400 peaks=16", "band 200-1000 peaks=16",
                "band 1000-5000 peaks=16", "band 400-1500 peaks=16"]
    for v in variants:
        eval_key.VARIANTS[v] = eval_key.variant_settings(v)
    ids, index, X, y = TKT.features_for(args.dataset, variants)
    print(f"{args.dataset}: {len(ids)} tracks, {X.shape[1]} features\n")

    rng = np.random.default_rng(0)
    folds = np.array_split(rng.permutation(len(ids)), args.folds)

    for hidden in args.hidden:
        cats: Counter = Counter()
        for k, test in enumerate(folds):
            tr = np.concatenate([f for j, f in enumerate(folds) if j != k])
            m = train_mlp(X[tr], y[tr], hidden=hidden, steps=args.steps, l2=args.l2)
            cats += TKT.score(predict_mlp(m, X[test]), [ids[i] for i in test], index)
        eval_key.report(f"MLP h={hidden}", cats)


if __name__ == "__main__":
    main()
