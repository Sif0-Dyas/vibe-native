"""Phase-1 acceptance: converted ONNX models reproduce oracle predictions.

Feed each oracle track's STORED embeddings through genre400.onnx and assert
the resulting per-frame probabilities' top-5 styles/scores match the oracle's
recorded styles (tolerance 1e-3 on scores). This isolates model conversion
from the (later) mel frontend. Skips until models/ + oracle/ exist.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(
    not list((ROOT / "models").glob("*.onnx")),
    reason="no converted models -- Session A (Phase 1)",
)
def test_genre_head_matches_oracle():
    pytest.skip("Phase 1 not implemented yet -- see PROJECT_PLAN.md")
