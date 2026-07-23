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

Checked <https://essentia.upf.edu/models/> on 2026-07-22 — a download beats a
conversion (addendum §2):

| Model | Ready-made `.onnx` in the zoo? | Decision |
| --- | --- | --- |
| EffNet embedder | **Yes** — `discogs-effnet-bsdynamic-1.onnx` (dynamic batch; `melspectrogram[B,128,96]` → `embeddings[B,1280]` + `activations[B,400]`) | **Downloaded** → `models/effnet.onnx`; no conversion |
| genre_discogs400 head (EffNet variant) | **No** — only MAEST variants ship `.onnx` | **Converted** `genre_discogs400-discogs-effnet-1.pb` |
| TempoCNN `deeptemp-k16` | **No** — only `.pb` / `.json` / `.tfjs` | **Converted** `deeptemp-k16-3.pb` |

The SavedModel→ONNX path for the embedder (plan Task 3a) is retained as a fallback
in `convert_models.py` (`_convert_effnet_from_savedmodel`), used only if the
ready-made download is unavailable.

## Source models + conversion results (Task 3)

`opset = 17`; tf2onnx `--graphdef` (frozen-graph) path for the two `.pb` heads.

| Output | Source | Input node → Output node | Result |
| --- | --- | --- | --- |
| `effnet.onnx` | zoo `discogs-effnet-bsdynamic-1.onnx` | `melspectrogram[B,128,96]` → `embeddings[B,1280]` | downloaded, 18.0 MB |
| `genre400.onnx` | `genre_discogs400-discogs-effnet-1.pb` | `serving_default_model_Placeholder:0[B,1280]` → `PartitionedCall:0[B,400]` (Sigmoid) | converted, 2.05 MB |
| `tempocnn.onnx` | `deeptemp-k16-3.pb` | `input:0[B,40,T,1]` → `output:0[B,256]` (Softmax) | converted, 1.28 MB |

**Genre-head fidelity vs the oracle (Phase-1 acceptance):** feeding every oracle
track's stored 1280-d embeddings through `genre400.onnx` and comparing the
mean-over-frames top-5 to `index.json` — **all 121 tracks match names exactly;
worst |Δscore| = 5.96e-08** (tolerance 1e-3). The baked-in Sigmoid converted
cleanly — no double activation, wrong output node, or transposed input.

## Execution provider that engaged on this machine

`get_engine()` logs the provider it selected; on this machine (RTX 5070) it
engaged **`DmlExecutionProvider`** (DirectML). onnxruntime-directml 1.24.4 reports
available providers: `DmlExecutionProvider`, `CPUExecutionProvider`.
