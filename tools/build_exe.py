"""Build the standalone Windows executable end to end:

  1. PyInstaller one-folder build from "Vibe Identify.spec"  -> dist/Vibe Identify/
  2. tools/prepare_dist.py: copy the loose, exe-adjacent resources the bundle omits
     (ONNX models + ffmpeg/ffprobe) into that folder.
  3. tools/smoke_dist.py: launch the result and check it actually serves.

Step 3 is the one that catches a build that *looks* fine — a missing hiddenimport or
an uncollected DLL produces a complete-looking dist folder that dies on the target
machine. A window flashes up while it runs; that is the app starting.

Then print the final folder path + size. MANUAL only — this is intentionally NOT in
CI (a build pulls in PyInstaller, collects hundreds of MB of native DLLs, and takes
a minute+; the CI gate stays fast).

    .venv\\Scripts\\python tools/build_exe.py            # clean build, prepare, smoke-test
    .venv\\Scripts\\python tools/build_exe.py --no-clean  # reuse the build cache
    .venv\\Scripts\\python tools/build_exe.py --no-smoke  # skip the launch check
"""

import argparse
import shutil
import subprocess  # nosec B404  # runs PyInstaller + prepare_dist via sys.executable, fixed args, no shell
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "Vibe Identify.spec"
DIST = ROOT / "dist" / "Vibe Identify"


def _dir_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the standalone Windows exe (onedir).")
    ap.add_argument("--no-clean", action="store_true", help="keep the prior build/ + dist/")
    ap.add_argument(
        "--no-smoke",
        action="store_true",
        help="skip step 3 (launching the built exe to check it serves)",
    )
    args = ap.parse_args()

    if not SPEC.is_file():
        print(f"ERROR: spec not found: {SPEC}")
        return 2

    if not args.no_clean:
        for d in (ROOT / "build", ROOT / "dist"):
            shutil.rmtree(d, ignore_errors=True)

    t0 = time.time()
    steps = 2 if args.no_smoke else 3
    print(f"[1/{steps}] PyInstaller (onedir, --windowed) ...")
    r = subprocess.run(  # nosec B603  # sys.executable + fixed args, no shell
        [
            sys.executable,
            "-m",
            "PyInstaller",
            str(SPEC),
            "--noconfirm",
            "--distpath",
            str(ROOT / "dist"),
            "--workpath",
            str(ROOT / "build"),
        ],
        cwd=str(ROOT),
    )
    if r.returncode != 0:
        print("PyInstaller FAILED — see output above.")
        return r.returncode

    print(f"\n[2/{steps}] prepare_dist (models + ffmpeg beside the exe) ...")
    r = subprocess.run(  # nosec B603  # sys.executable + fixed args, no shell
        [sys.executable, str(ROOT / "tools" / "prepare_dist.py")],
        cwd=str(ROOT),
    )
    # prepare_dist returns 1 if some models were missing; surface but don't hard-fail.
    prep_warn = r.returncode == 1
    if r.returncode not in (0, 1):
        print("prepare_dist FAILED.")
        return r.returncode

    exe = DIST / "Vibe Identify.exe"
    if not exe.is_file():
        # PyInstaller reported success but produced no exe: a broken spec (a renamed
        # EXE(name=...), a collect step that wrote elsewhere). Never a warning.
        print(f"\nERROR: PyInstaller succeeded but {exe} does not exist - check the spec.")
        return 1

    smoked = False
    if not args.no_smoke:
        print(f"\n[3/{steps}] smoke_dist (launch it and check it serves) ...")
        r = subprocess.run(  # nosec B603  # sys.executable + fixed args, no shell
            [sys.executable, str(ROOT / "tools" / "smoke_dist.py")],
            cwd=str(ROOT),
        )
        if r.returncode != 0:
            print("\nThe build produced a folder that does not run. Do not ship it.")
            return r.returncode
        smoked = True

    size = _dir_size(DIST)
    print("\n" + "=" * 60)
    print(f"Built in {time.time() - t0:.0f}s")
    print(f"  folder: {DIST}")
    print(f"  size:   {size / 1e6:.0f} MB")
    print(f"  exe:    {exe}")
    print(f"  smoke:  {'passed - it starts and serves' if smoked else 'SKIPPED (--no-smoke)'}")
    if prep_warn:
        print("  NOTE: some models were missing — run tools/convert_models.py, re-prepare.")
    print("Launch by double-clicking the exe (no venv / Python needed on the target).")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
