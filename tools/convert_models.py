#!/usr/bin/env python3
"""Produce models/*.onnx for the native engine (Phase 1).

Re-runnable: every step skips when its output already exists, so this is safe to
run repeatedly and on a fresh clone (it re-downloads what the .gitignore keeps
local). Requires the CONVERSION venv (Python <=3.12 + requirements-convert.txt);
TensorFlow has no 3.14 wheels — see tools/CONVERSION_NOTES.md.

MODEL-ZOO CHECK (Task 2, https://essentia.upf.edu/models/, checked 2026-07-22)
    A download beats a conversion (addendum §2). What the zoo publishes today:

    * EffNet embedder  -> discogs-effnet-bsdynamic-1.onnx EXISTS (ready-made ONNX,
      dynamic batch; input melspectrogram[B,128,96] -> embeddings[B,1280] +
      activations[B,400]). We DOWNLOAD it rather than convert the SavedModel.
      (The Task-3a SavedModel path is kept as _convert_effnet_from_savedmodel()
      below, used only if the download is unavailable.)
    * genre_discogs400 head (EffNet variant) -> NO .onnx. Only MAEST variants ship
      .onnx. So genre_discogs400-discogs-effnet-1.pb must be CONVERTED here.
    * TempoCNN deeptemp-k16 -> NO .onnx (only .pb / .json / .tfjs). CONVERTED here
      from deeptemp-k16-3.pb.

Node names (from each model's Essentia .json schema + Vibe_Identify analysis.py):
    genre head : in  serving_default_model_Placeholder:0  [B,1280]
                 out PartitionedCall:0                     [B,400] (Sigmoid)
    tempocnn   : in  input:0   [B,256,40]     out output:0  [B,256] (Softmax)

Outputs (all git-ignored as binaries): models/effnet.onnx, models/genre400.onnx,
models/tempocnn.onnx.
"""

import subprocess
import sys
import urllib.request
from pathlib import Path

MODELS = Path(__file__).resolve().parent.parent / "models"
ZOO = "https://essentia.upf.edu/models"
OPSET = 17  # basic ops (MatMul/Conv/Sigmoid/Softmax); onnxruntime 1.24 supports it

# Files fetched from the zoo (skip if present). *.json are small metadata the code
# reads and are git-tracked; the .onnx/.pb binaries stay local (git-ignored).
DOWNLOADS = {
    # ready-made EffNet embedder ONNX -> our canonical effnet.onnx
    "effnet.onnx": f"{ZOO}/feature-extractors/discogs-effnet/discogs-effnet-bsdynamic-1.onnx",
    # AUTHORITATIVE input spec for effnet.onnx (the bsdynamic variant we ship):
    # input serving_default_melspectrogram[n,128,96], sample_rate 16000, embeddings
    # at PartitionedCall:1[n,1280]. Phase 2's frontend_mel reads THIS before the
    # Essentia source. (bs64 metadata kept too — same input family.)
    "discogs-effnet-bsdynamic-1.json": f"{ZOO}/feature-extractors/discogs-effnet/discogs-effnet-bsdynamic-1.json",
    "discogs-effnet-bs64-1.json": f"{ZOO}/feature-extractors/discogs-effnet/discogs-effnet-bs64-1.json",
    # TempoCNN source graph + metadata (no .onnx published)
    "deeptemp-k16-3.pb": f"{ZOO}/tempo/tempocnn/deeptemp-k16-3.pb",
    "deeptemp-k16-3.json": f"{ZOO}/tempo/tempocnn/deeptemp-k16-3.json",
}


def download(name: str, url: str) -> Path:
    dest = MODELS / name
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  [skip] {name} exists ({dest.stat().st_size:,} B)")
        return dest
    print(f"  [get ] {name} <- {url}")
    urllib.request.urlretrieve(url, dest)  # noqa: S310  # fixed HTTPS zoo URL, not user input
    print(f"         {dest.stat().st_size:,} B")
    return dest


def convert_graphdef(pb: Path, out: Path, inputs: str, outputs: str) -> None:
    """Convert a frozen TF GraphDef (.pb) to ONNX via the tf2onnx CLI."""
    if out.exists() and out.stat().st_size > 0:
        print(f"  [skip] {out.name} exists ({out.stat().st_size:,} B)")
        return
    print(f"  [conv] {pb.name} -> {out.name}  (in={inputs} out={outputs} opset={OPSET})")
    cmd = [
        sys.executable, "-m", "tf2onnx.convert",
        "--graphdef", str(pb),
        "--output", str(out),
        "--inputs", inputs,
        "--outputs", outputs,
        "--opset", str(OPSET),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        raise SystemExit(
            f"tf2onnx failed for {pb.name} (rc={r.returncode}).\n"
            f"--- stdout ---\n{r.stdout[-2000:]}\n--- stderr ---\n{r.stderr[-2000:]}"
        )
    print(f"         {out.stat().st_size:,} B")


def _convert_effnet_from_savedmodel() -> None:
    """FALLBACK (Task 3a) — only if the ready-made embedder ONNX can't be fetched.

    tf2onnx handles a SavedModel without manual --inputs/--outputs (addendum §2);
    the frozen .pb + explicit tensor names (PartitionedCall:1 etc.) are the
    fallback-of-the-fallback from the plan's Risks section. Unused while the zoo
    ships discogs-effnet-bsdynamic-1.onnx."""
    import zipfile

    out = MODELS / "effnet.onnx"
    if out.exists():
        return
    zip_path = MODELS / "discogs-effnet-bs64-1-savedmodel.zip"
    sm_dir = MODELS / "_effnet_savedmodel"
    if not sm_dir.exists():
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(sm_dir)
    # a SavedModel dir has saved_model.pb at its root (possibly one level down)
    root = sm_dir if (sm_dir / "saved_model.pb").exists() else next(sm_dir.glob("**/saved_model.pb")).parent
    cmd = [sys.executable, "-m", "tf2onnx.convert", "--saved-model", str(root),
           "--output", str(out), "--opset", str(OPSET)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        raise SystemExit(f"SavedModel conversion failed:\n{r.stderr[-2000:]}")


def main() -> int:
    MODELS.mkdir(exist_ok=True)
    print("== downloads ==")
    try:
        for name, url in DOWNLOADS.items():
            download(name, url)
    except Exception as e:  # noqa: BLE001
        print(f"  download failed ({e}); trying SavedModel fallback for the embedder")
        _convert_effnet_from_savedmodel()

    print("== conversions ==")
    # genre_discogs400 EffNet head: embeddings[1280] -> 400 sigmoid probabilities
    convert_graphdef(
        MODELS / "genre_discogs400-discogs-effnet-1.pb",
        MODELS / "genre400.onnx",
        inputs="serving_default_model_Placeholder:0",
        outputs="PartitionedCall:0",
    )
    # TempoCNN deeptemp-k16: mel[256,40] -> 256 tempo-class softmax
    convert_graphdef(
        MODELS / "deeptemp-k16-3.pb",
        MODELS / "tempocnn.onnx",
        inputs="input:0",
        outputs="output:0",
    )

    print("== done ==")
    for f in ("effnet.onnx", "genre400.onnx", "tempocnn.onnx"):
        p = MODELS / f
        print(f"  {f}: {'OK ' + format(p.stat().st_size, ',') + ' B' if p.exists() else 'MISSING'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
