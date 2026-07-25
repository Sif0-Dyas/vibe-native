"""Populate a built dist/ folder with the loose, EXE-ADJACENT resources that are
deliberately NOT baked into the PyInstaller bundle:

  * the ONNX models  -> dist/Vibe Identify/models/   (models_dir() finds them there)
  * ffmpeg + ffprobe -> dist/Vibe Identify/           (decode._tool finds them there)

Keeping these loose (not in the bundle) makes the build small and lets you swap in
new models or a newer/LGPL ffmpeg without rebuilding. Run after PyInstaller;
tools/build_exe.py does both steps. Idempotent.

    python tools/prepare_dist.py
"""

import io
import os
import shutil
import sys
import urllib.request
import zipfile
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

# For redistribution we ship an LGPL ffmpeg (not the machine's likely-GPL winget build).
# BtbN's win64 "lgpl" archive is a STATIC LGPL build: just ffmpeg.exe + ffprobe.exe, no
# DLLs, small. Vendored once into vendor/ffmpeg/ (gitignored) and reused across builds.
VENDOR = ROOT / "vendor" / "ffmpeg"
FFMPEG_LGPL_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-lgpl.zip"
)

FFMPEG_NOTICE = """\
ffmpeg.exe / ffprobe.exe bundled beside this application
=========================================================
ffmpeg is a SEPARATE program invoked by command line (argv) — it is NOT linked into
"Vibe Identify.exe" — so it stays a mere aggregation, not a derivative work.

This build is an **LGPL** static ffmpeg from BtbN's FFmpeg-Builds
(ffmpeg-master-latest-win64-lgpl), chosen for redistribution: it omits the GPL-only
components (x264/x265, etc.). We only DECODE audio (mp3/flac/wav/…), which the LGPL
build does natively. ffmpeg's source and full license terms:
  https://www.ffmpeg.org/  •  https://www.ffmpeg.org/legal.html
  builds: https://github.com/BtbN/FFmpeg-Builds  (LGPL-3.0 / LGPL-2.1+ per component)

You may delete these two files and rely on a system-PATH ffmpeg instead — the app
checks PATH first, then here (exe-adjacent), then the WinGet Links dir.
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


def ensure_lgpl_ffmpeg() -> tuple[Path, Path] | tuple[None, None]:
    """Ensure a vendored LGPL static ffmpeg/ffprobe in vendor/ffmpeg (download once).
    Returns (ffmpeg, ffprobe) paths, or (None, None) if the download fails."""
    fm, fp = VENDOR / "ffmpeg.exe", VENDOR / "ffprobe.exe"
    if fm.is_file() and fp.is_file():
        return fm, fp
    VENDOR.mkdir(parents=True, exist_ok=True)
    print(f"downloading LGPL ffmpeg (BtbN static) ...\n  {FFMPEG_LGPL_URL}")
    try:
        data = urllib.request.urlopen(FFMPEG_LGPL_URL, timeout=180).read()  # nosec B310  # fixed HTTPS github release URL
    except Exception as e:  # network/download failure -> caller falls back to system ffmpeg
        print(f"  ! download failed ({e}); falling back to the system ffmpeg build.")
        return None, None
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for member in z.namelist():
            base = os.path.basename(member)
            if base in ("ffmpeg.exe", "ffprobe.exe"):
                with z.open(member) as src, open(VENDOR / base, "wb") as out:
                    shutil.copyfileobj(src, out)
    return (fm, fp) if fm.is_file() and fp.is_file() else (None, None)


def copy_ffmpeg() -> None:
    """Copy ffmpeg/ffprobe next to the exe: prefer the vendored LGPL build (small,
    redistributable), else fall back to the system build. Missing ffmpeg is NOT fatal —
    the app warns at runtime and cached-library browsing still works."""
    fm, fp = ensure_lgpl_ffmpeg()
    if fm and fp:
        shutil.copy2(fm, DIST / "ffmpeg.exe")
        shutil.copy2(fp, DIST / "ffprobe.exe")
        print(f"ffmpeg -> {DIST}: ['ffmpeg', 'ffprobe']  (LGPL static, BtbN)")
        (DIST / "ffmpeg-NOTICE.txt").write_text(FFMPEG_NOTICE, encoding="utf-8")
        print("  + ffmpeg-NOTICE.txt (LGPL note)")
        return

    # fallback: whatever ffmpeg is on the system (likely GPL) — better than none.
    sys.path.insert(0, str(ROOT / "src"))
    from vibenative.decode import find_tool

    got = []
    for tool in ("ffmpeg", "ffprobe"):
        src = find_tool(tool)
        if src:
            shutil.copy2(src, DIST / f"{tool}.exe")
            got.append(tool)
        else:
            print(
                f"  ! {tool} not found to copy — the exe warns at runtime; cached browsing still works."
            )
    print(f"ffmpeg -> {DIST}: {got or 'none copied'}  (SYSTEM build — may be GPL)")
    if got:
        (DIST / "ffmpeg-NOTICE.txt").write_text(FFMPEG_NOTICE, encoding="utf-8")


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
