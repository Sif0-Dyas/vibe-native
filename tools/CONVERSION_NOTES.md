# Conversion Notes — Phase 1 (TensorFlow models → ONNX)

## Interpreter constraint (why Python ≤ 3.12)

- **Conversion requires Python ≤ 3.12.** TensorFlow ships **no wheels for Python
  3.14** (`pip install tensorflow` → *"No matching distribution found"*), and
  `tf2onnx` needs TensorFlow to load SavedModels / frozen graphs. This machine had
  only 3.14 installed, so we installed **3.12.10** (`winget install
  Python.Python.3.12`) and pin it at the repo root via **`.python-version` (`3.12`)**
  so future sessions don't rediscover this.
- **Runtime is version-flexible.** `onnxruntime-directml`, `numpy`, and `pytest`
  all have 3.14 wheels — only the *conversion* half is version-locked. The produced
  `models/*.onnx` are portable and run under any supported Python.
- Dependencies are split so the heavy TF wheel never ships:
  - `requirements-convert.txt` — `tensorflow`, `tf2onnx` (conversion only, ~500 MB)
  - `requirements.txt` — `onnxruntime-directml`, `numpy`, `pytest` (runtime + tests)

## Toolchain versions (this machine)

| Tool | Version |
| --- | --- |
| Python | 3.12.10 (venv at `.venv/`) |
| tensorflow (convert-only) | 2.21.0 |
| tf2onnx | 1.17.0 |
| onnx | 1.22.0 |
| onnxruntime-directml | 1.24.4 |
| numpy | 2.5.1 |
| Execution providers present | `DmlExecutionProvider`, `CPUExecutionProvider` |

## Zoo-ONNX pre-check (Task 2)

_Filled in during conversion (a download beats a conversion — addendum §2)._

## Source models + conversion results (Task 3)

_Filled in during conversion: filenames/versions, opset, per-model input/output nodes._

## Execution provider that engaged on this machine

_Filled in from the onnx_engine session-creation log._
