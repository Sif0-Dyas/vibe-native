"""Build the Windows installer (Inno Setup) from the packaged dist folder.

Runs Inno's `iscc` against tools/installer.iss with the app version stamped from
vibenative.__version__, and prints the resulting Setup .exe path + size. MANUAL only
(like build_exe.py) — never in CI.

    python tools/build_installer.py            # dist must already exist
    python tools/build_installer.py --build    # run tools/build_exe.py first

Needs Inno Setup 6. If iscc isn't found this prints the winget line and exits cleanly
rather than failing cryptically.
"""

import argparse
import os
import subprocess  # nosec B404  # runs iscc / build_exe via fixed arg lists, no shell
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ISS = ROOT / "tools" / "installer.iss"
DIST = ROOT / "dist" / "Vibe Identify"
OUTDIR = ROOT / "dist" / "installer"

WINGET_LINE = "winget install --id JRSoftware.InnoSetup -e"


def find_iscc() -> str | None:
    """Locate Inno's command-line compiler (PATH, then the standard install dirs)."""
    for name in ("iscc", "iscc.exe", "ISCC.exe"):
        from shutil import which

        exe = which(name)
        if exe:
            return exe
    bases = [
        os.environ.get("ProgramFiles(x86)"),
        os.environ.get("ProgramFiles"),
        # winget often installs Inno per-user under %LOCALAPPDATA%\Programs
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"),
    ]
    for base in bases:
        if base:
            for ver in ("Inno Setup 6", "Inno Setup 5"):
                cand = Path(base) / ver / "ISCC.exe"
                if cand.is_file():
                    return str(cand)
    return None


def app_version() -> str:
    sys.path.insert(0, str(ROOT / "src"))
    import vibenative

    return vibenative.__version__


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the Windows installer (Inno Setup).")
    ap.add_argument("--build", action="store_true", help="run tools/build_exe.py first")
    args = ap.parse_args()

    if args.build:
        r = subprocess.run(  # nosec B603  # sys.executable + fixed args
            [sys.executable, str(ROOT / "tools" / "build_exe.py")], cwd=str(ROOT)
        )
        if r.returncode != 0:
            return r.returncode

    if not DIST.is_dir():
        print(f"ERROR: {DIST} not found — build it first:  python tools/build_exe.py")
        return 2

    iscc = find_iscc()
    if not iscc:
        print("ERROR: Inno Setup 6 (iscc) was not found on this machine.")
        print("Install it, then re-run this script:")
        print(f"    {WINGET_LINE}")
        print("(or download from https://jrsoftware.org/isdl.php)")
        return 3

    version = app_version()
    print(f"iscc:    {iscc}")
    print(f"version: {version}  (from vibenative.__version__)")
    OUTDIR.mkdir(parents=True, exist_ok=True)

    r = subprocess.run(  # nosec B603  # iscc from find_iscc(), fixed args, no shell
        [iscc, f"/DMyAppVersion={version}", str(ISS)], cwd=str(ROOT)
    )
    if r.returncode != 0:
        print("iscc FAILED — see output above.")
        return r.returncode

    setup = OUTDIR / f"VibeIdentify-Setup-{version}.exe"
    print("\n" + "=" * 60)
    if setup.is_file():
        print(f"installer: {setup}")
        print(f"  size:    {setup.stat().st_size / 1e6:.0f} MB")
    else:
        print(f"WARNING: expected {setup.name} not found in {OUTDIR}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
