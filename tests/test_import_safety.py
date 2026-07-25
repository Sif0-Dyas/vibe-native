"""Regression guard: the suite must COLLECT even when onnxruntime is absent.

Why this exists
---------------
CI installs neither onnxruntime nor the ONNX models (onnxruntime-directml is a
Windows-only wheel), and runs everything in FAKE mode. pytest imports every test
module during its *collection* phase, before running anything. If ANY module
reachable by collection imports onnxruntime at module top level, that import
ImportErrors on CI and aborts the ENTIRE suite before a single test runs.

That is precisely what happened from Phase 3 until it was fixed: tempo.py imported
onnxruntime at module top, and tests/test_analysis.py imports tempo, so collection
ImportErrored on CI and pytest never executed — silently, for months. This test
would have caught it on the first CI run.

The check simulates onnxruntime's absence (a stub that raises ImportError on import,
shadowing the real wheel via PYTHONPATH) and runs `pytest --collect-only` in a
subprocess, asserting collection still succeeds. It is cheap: collection is ~0.2s,
no models, no network. If it fails, some collection-reachable module imports
onnxruntime (or another optional/Windows-only dep) at top level — make that import
lazy, as tempo.py and routes/library.py already do.
"""

import os
import subprocess  # nosec B404  # runs this repo's own pytest with a fixed arg list, no shell
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_suite_collects_without_onnxruntime(tmp_path):
    # a fake `onnxruntime` that explodes on import, first on sys.path so it shadows
    # the real (locally-installed) wheel — reproducing CI, where it isn't installed.
    (tmp_path / "onnxruntime.py").write_text(
        'raise ImportError("simulated: onnxruntime absent, as on CI")', encoding="utf-8"
    )
    env = {
        **os.environ,
        "PYTHONPATH": str(tmp_path) + os.pathsep + os.environ.get("PYTHONPATH", ""),
        "FAKE_ANALYZER": "1",
    }
    proc = subprocess.run(  # nosec B603  # sys.executable + literal args, no shell, trusted input
        [sys.executable, "-m", "pytest", "-q", "--collect-only", "-p", "no:cacheprovider"],
        cwd=str(_REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, (
        "pytest COLLECTION failed with onnxruntime absent — a module reachable by "
        "collection imports it (or another optional dep) at module top level. Make "
        "that import lazy. Tail of the failing run:\n"
        + (proc.stdout or "")[-3000:]
        + (proc.stderr or "")[-2000:]
    )
