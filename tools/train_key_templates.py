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
from collections import Counter
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


def _logits(R: np.ndarray, W: np.ndarray, b: np.ndarray) -> np.ndarray:
    """(n, 12, 2, K) raw scores: rotation t, mode m, sub-template k."""
    return np.einsum("ntd,mkd->ntmk", R, W) + b[None, None, :, :]


def _pool(sub: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Soft-max pool over the K sub-templates: returns (logit (n,12,2), the
    responsibility of each sub-template (n,12,2,K)). With K=1 this is the
    identity and the model is the plain linear one."""
    mx = sub.max(axis=3, keepdims=True)
    e = np.exp(sub - mx)
    tot = e.sum(axis=3, keepdims=True)
    return (mx + np.log(tot))[..., 0], e / tot


def train(pcps: np.ndarray, keys: np.ndarray, l2: float = 1e-2, steps: int = 4000, lr: float = 1.0,
          subclasses: int = 1, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Gradient descent on the 24-way softmax. Returns (W (2, K, D), b (2, K)).
    ``keys`` are ints 0..23 = tonic + 12 * mode_index.

    logit[t, m] = logsumexp_k(<standardised pcp rolled by t, W[m,k]> + b[m,k]).
    With K = 1 that is the classic single template per mode; K > 1 lets a mode
    be a mixture — Faraldo 2017 found many EDM minor tracks carry a major third,
    which one minor template cannot describe and two can. The sub-templates are
    latent: nothing labels which one a track belongs to, the fit decides."""
    X = _standardise(pcps)
    R = _all_rotations(X)  # (n, 12, D)
    n, D = X.shape
    rng = np.random.default_rng(seed)
    # symmetry breaking: identical sub-templates would stay identical forever
    W = rng.normal(0, 1e-2, (2, subclasses, D)) if subclasses > 1 else np.zeros((2, subclasses, D))
    b = np.zeros((2, subclasses))
    onehot = np.zeros((n, 24))
    onehot[np.arange(n), keys] = 1.0
    for _ in range(steps):
        logit, resp = _pool(_logits(R, W, b))  # (n,12,2), (n,12,2,K)
        flat = logit.transpose(0, 2, 1).reshape(n, 24)  # index t + 12 m
        flat -= flat.max(axis=1, keepdims=True)
        p = np.exp(flat)
        p /= p.sum(axis=1, keepdims=True)
        g3 = ((p - onehot) / n).reshape(n, 2, 12).transpose(0, 2, 1)  # (n, 12, 2)
        g4 = g3[..., None] * resp  # chain rule through the pool
        W -= lr * (np.einsum("ntmk,ntd->mkd", g4, R) + l2 * W)
        b -= lr * g4.sum(axis=(0, 1))
    return W, b


def predict(W: np.ndarray, b: np.ndarray, pcps: np.ndarray) -> np.ndarray:
    R = _all_rotations(_standardise(pcps))
    logit, _ = _pool(_logits(R, W, b))
    return logit.transpose(0, 2, 1).reshape(len(pcps), 24).argmax(axis=1)


def features_for(dataset: str, variants: list[str], min_confidence: int | None = None):
    """(ids, index, X, y) for a dataset: the concatenated block PCPs and labels."""
    index = eval_key.load_index(dataset)
    pcps = eval_key.load_pcps(index, dataset, verbose=False)
    ids = [h for h in sorted(index) if all((h, v) in pcps for v in variants)]
    if min_confidence is not None:
        ids = [h for h in ids if (index[h].get("confidence") is None
                                  or index[h]["confidence"] >= min_confidence)]
    X = np.concatenate([np.array([eval_key.gated(pcps[(h, v)]) for h in ids]) for v in variants], axis=1)
    y = np.array([tonality.KEY_NAMES.index(index[h]["key"]) + 12 * MODES.index(index[h]["scale"]) for h in ids])
    return ids, index, X, y


def score(pred, ids, index) -> Counter:
    cats: Counter = Counter()
    for i, pr in enumerate(pred):
        cats[eval_key.category((tonality.KEY_NAMES[pr % 12], MODES[pr // 12]),
                               (index[ids[i]]["key"], index[ids[i]]["scale"]))] += 1
    return cats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="giantsteps")
    ap.add_argument("--variant", default="default")
    ap.add_argument("--extra", action="append", default=[], metavar="VARIANT",
                    help="further PCP variants (e.g. bands) to concatenate; templates become 12*(1+n) wide")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--test-on", metavar="DATASET", help="train on --dataset, report on this one instead of k-fold")
    ap.add_argument("--augment", metavar="DATASET", help="add this dataset to every training fold (never tested on)")
    ap.add_argument("--min-confidence", type=int, metavar="N",
                    help="training tracks must carry at least this annotator confidence (Beatport: 0-2)")
    ap.add_argument("--l2", type=float, default=1e-2)
    ap.add_argument("--subclasses", type=int, default=1, metavar="K",
                    help="sub-templates per mode (K>1 = mixture; Faraldo's minor2 case)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--write", action="store_true", help="store the templates trained on ALL tracks as the edm profiles")
    args = ap.parse_args()

    index = eval_key.load_index(args.dataset)
    variants = [args.variant, *args.extra]
    for v in variants:
        eval_key.VARIANTS[v] = eval_key.variant_settings(v)
    ids, index, X, y = features_for(args.dataset, variants, args.min_confidence)

    aug = features_for(args.augment, variants, args.min_confidence)[2:] if args.augment else None
    tag = f"K={args.subclasses}" + (f"+{args.augment}" if args.augment else "")

    def fit(Xt, yt):
        if aug:
            Xt, yt = np.concatenate([Xt, aug[0]]), np.concatenate([yt, aug[1]])
        return train(Xt, yt, l2=args.l2, subclasses=args.subclasses, seed=args.seed)

    if args.test_on:  # train on everything here, score a held-out dataset
        W, b = fit(X, y)
        t_ids, t_index, tX, _ = features_for(args.test_on, variants)
        eval_key.report(f"{tag} -> {args.test_on}", score(predict(W, b, tX), t_ids, t_index))
        return

    rng = np.random.default_rng(0)
    folds = np.array_split(rng.permutation(len(ids)), args.folds)
    cats: Counter = Counter()
    per: dict[str, Counter] = __import__("collections").defaultdict(Counter)
    for k, test in enumerate(folds):
        tr = np.concatenate([f for j, f in enumerate(folds) if j != k])
        W, b = fit(X[tr], y[tr])
        cats += score(predict(W, b, X[test]), [ids[i] for i in test], index)
        for name in sorted({h.split(":", 1)[0] for h in ids if ":" in h}):  # "both": per-dataset too
            sub = [i for i in test if ids[i].startswith(f"{name}:")]
            per[name] += score(predict(W, b, X[sub]), [ids[i] for i in sub], index)
    eval_key.report(f"{tag} {args.folds}-fold", cats)
    for name, c in per.items():
        eval_key.report(f"  on {name}", c)

    if args.write:
        W, b = fit(X, y)
        doc = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
        doc["model"] = {
            "about": "Linear key scorer trained by tools/train_key_templates.py: a transposition-"
                     "equivariant 24-way softmax over the per-block standardised PCPs of the listed "
                     "frequency-band blocks. weights[mode] is a list of sub-templates (12 values per "
                     "block, index 0 = tonic); a mode's score is logsumexp over its sub-templates.",
            "fitted": date.today().isoformat(), "labels": args.dataset, "l2": args.l2,
            "tracks": len(ids) + (len(aug[1]) if aug else 0),
            "augmented_with": args.augment, "min_confidence": args.min_confidence,
            "subclasses": args.subclasses,
            "cross_validated": {"folds": args.folds, **cats},
            "blocks": [eval_key.variant_settings(v) for v in variants],
            "block_names": variants,
            "weights": {m: [[round(float(v), 5) for v in w] for w in W[i]] for i, m in enumerate(MODES)},
            "bias": {m: [round(float(v), 5) for v in b[i]] for i, m in enumerate(MODES)},
        }
        OUT.write_text(json.dumps(doc, indent=1) + chr(10), encoding="utf-8")
        print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
