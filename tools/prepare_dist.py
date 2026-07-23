"""Populate a built dist/ folder with the loose, EXE-ADJACENT resources that are
deliberately NOT baked into the PyInstaller bundle:

  * the ONNX models  -> dist/Vibe Identify/models/   (models_dir() finds them there)
  * ffmpeg + ffprobe -> dist/Vibe Identify/           (decode._tool finds them there)

Keeping these loose (not in the bundle) makes the build small and lets you swap in
new models or a newer/LGPL ffmpeg without rebuilding. Run after PyInstaller;
tools/build_exe.py does both steps. Idempotent.

    python tools/prepare_dist.py
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist" / "Vibe Identify"
MODELS_SRC = ROOT / "models"
MODEL_FILES = [
    "effnet.onnx",
    "genre400.onnx",
    "tempocnn.onnx",
    "genre_discogs400-discogs-effnet-1.json",  # the 400 labels the classifier needs
]

FFMPEG_NOTICE = """\
ffmpeg.exe / ffprobe.exe bundled beside this application
=========================================================
These are the system ffmpeg build present on the machine that produced this folder.
ffmpeg is a SEPARATE program invoked by command line (argv) — it is NOT linked into
"Vibe Identify.exe" — so it stays a mere aggregation, not a derivative work.

Licensing: an ffmpeg binary is LGPL-2.1+ when built without GPL-only components, or
GPL when built with them (e.g. x264/x265). The copy here inherits whatever build was
installed (a winget "Gyan.FFmpeg" build is typically GPL). For REDISTRIBUTION prefer
an LGPL shared build (e.g. gyan.dev "shared" or BtbN LGPL releases) and ship its
license text. You may also delete these two files and rely on a system-PATH ffmpeg —
the app checks PATH first, then here, then the WinGet Links dir.
Full ffmpeg license terms: https://www.ffmpeg.org/legal.html
"""


def copy_models() -> bool:
    dst = DIST / "models"
    dst.mkdir(parents=True, exist_ok=True)
    copied, missing = [], []
    for name in MODEL_FILES:
        src = MODELS_SRC / name
        if src.is_file():
            shutil.copy2(src, dst / name)
            copied.append(name)
        else:
            missing.append(name)
    print(f"models -> {dst}")
    for n in copied:
        print(f"  + {n}")
    for n in missing:
        print(f"  ! MISSING (run tools/convert_models.py): {n}")
    return not missing


def copy_ffmpeg() -> None:
    """Copy the system ffmpeg/ffprobe next to the exe, if locatable. Missing ffmpeg is
    NOT fatal — the app warns at runtime and cached-library browsing still works."""
    sys.path.insert(0, str(ROOT / "native"))
    from vibenative.decode import find_tool

    got = []
    for tool in ("ffmpeg", "ffprobe"):
        src = find_tool(tool)
        if src:
            shutil.copy2(src, DIST / f"{tool}.exe")
            got.append(tool)
        else:
            print(
                f"  ! {tool} not found to copy — the exe will warn at runtime; cached browsing still works."
            )
    print(f"ffmpeg -> {DIST}: {got or 'none copied'}")
    if got:
        (DIST / "ffmpeg-NOTICE.txt").write_text(FFMPEG_NOTICE, encoding="utf-8")
        print("  + ffmpeg-NOTICE.txt (LGPL/GPL note)")


def main() -> int:
    if not DIST.is_dir():
        print(f'ERROR: {DIST} not found — build first (pyinstaller "Vibe Identify.spec").')
        return 2
    ok = copy_models()
    copy_ffmpeg()
    if not ok:
        print("\nWARNING: some models were missing; the exe will fail to analyze until they exist.")
        return 1
    print("\ndist prepared: models + ffmpeg are in place beside the exe.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
