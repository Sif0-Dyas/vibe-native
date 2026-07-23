"""Phase-2 acceptance: native embeddings vs the WSL oracle.

For every oracle/<hash>.npz: run the native frontend+embedder on the file
listed in oracle/index.json and assert per-track cosine(native_mean,
oracle.emb_mean) > 0.999 AND mean per-frame cosine > 0.999 with matching
frame counts. Skips (with a clear message) when oracle/ is absent so the
suite is green on a fresh clone.

Phase-1 handoff — ITERATION STRATEGY: the oracle has 121 tracks. During Phase-2
development iterate against a ~40-track subset for speed (a fast inner loop while
tuning the mel params), and run the full 121 only as the FINAL acceptance gate.
Do NOT lower the 0.999 threshold to make the subset pass.
"""

import json
from pathlib import Path

import pytest

ORACLE = Path(__file__).resolve().parent.parent / "oracle"


@pytest.mark.skipif(
    not (ORACLE / "index.json").exists(),
    reason="oracle not populated -- run tools/make_oracle.py on WSL (Phase 0)",
)
def test_embeddings_match_oracle():
    index = json.loads((ORACLE / "index.json").read_text())
    assert index, "empty oracle index"
    pytest.skip("Phase 2 not implemented yet -- see PROJECT_PLAN.md")
