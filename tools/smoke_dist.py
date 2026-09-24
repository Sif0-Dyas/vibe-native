"""Prove a built dist/ folder actually runs: launch the packaged exe, wait for its
backend to answer, and check what the bundle is supposed to provide.

Everything else in the build pipeline checks that files were *produced*.  Nothing
checked that the exe *starts* -- and the ways a PyInstaller build breaks (a missing
hiddenimport, a data file that stayed in the venv, an onnxruntime DLL that did not
get collected) all produce a perfectly plausible-looking dist folder that dies the
moment it is double-clicked.  This is the difference between finding that out here
and finding it out from whoever you sent the build to.

    python tools/smoke_dist.py                 # after tools/build_exe.py
    python tools/smoke_dist.py --timeout 90    # slower machine / cold antivirus scan

Checks: the process stays up, Flask serves on the loopback port, /status reports the
packaged version, ffmpeg and ffprobe resolve *from the bundle*, the ONNX providers
list is non-empty, and the UI page and its static assets are served out of the
bundle. GPU absence is reported, not failed -- the target may genuinely lack one.

The app is launched with PATH cut back to the Windows system directories, because
the build machine is the worst possible judge of a redistributable bundle: with a
system ffmpeg installed, `decode.find_tool` finds it on PATH and the app works
perfectly here while being broken everywhere else. Stripping PATH forces the bundle
to stand on its own, the way it will have to on the machine you send it to.

Harmless by construction: it runs against a throwaway database in the temp
directory, never the real library, and kills the app afterwards.  A window will
flash up while it runs -- that IS the app starting, which is the thing being tested.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess  # nosec B404  # launches the just-built exe with a fixed arg list, no shell
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist" / "Vibe Identify"
EXE = DIST / "Vibe Identify.exe"

_ok = True


def check(label: str, got, want=True) -> None:
    """Report one expectation. Mirrors the desktop shell's --selftest output."""
    global _ok
    good = (got == want) if not callable(want) else want(got)
    _ok = _ok and good
    print(f"  [{'ok' if good else 'FAIL'}] {label}: {got!r}")


def note(label: str, got) -> None:
    """Report something worth seeing that is not a pass/fail condition."""
    print(f"  [--] {label}: {got!r}")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _get(url: str, timeout: float = 5.0):
    """(status, body) for a GET, or (None, reason) if it could not be reached."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:  # nosec B310  # fixed loopback URL
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return None, str(e)


def _make_tagged_track(path: Path, title: str, seconds: int = 12) -> bool:
    """Generate a tagged audio file with the *bundled* ffmpeg. Quiet noise rather
    than silence so the analyser has something to work on. False if it could not
    be made (then the round-trip check is skipped, not failed)."""
    exe = DIST / "ffmpeg.exe"
    if not exe.is_file():
        return False
    try:
        subprocess.run(  # nosec B603  # the bundled ffmpeg, fixed arg list, no shell
            [
                str(exe),
                "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"anoisesrc=d={seconds}:c=pink:a=0.05:r=44100",
                "-ac",
                "2",
                "-metadata",
                f"title={title}",
                str(path),
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
        return path.is_file()
    except (OSError, subprocess.SubprocessError):
        return False


def _post_file(url: str, path: Path, timeout: float = 120.0):
    """multipart/form-data upload of one file, as the UI does it."""
    boundary = "----vibesmoke" + secrets.token_hex(8)
    body = b"".join(
        [
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="{path.name}"\r\nContent-Type: audio/mpeg\r\n\r\n'.encode(),
            path.read_bytes(),
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310  # fixed loopback URL
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return None, str(e).encode()


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the app and anything it spawned. The desktop shell runs the backend
    in-process by default but can fall back to a child interpreter, so the whole
    tree has to go or a stray backend keeps the port."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(  # nosec B603 B607  # fixed args, no shell
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
        )
    else:
        proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()


def main() -> int:
    ap = argparse.ArgumentParser(description="Smoke-test the built dist/ folder.")
    ap.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="seconds to wait for the backend to answer (default 60)",
    )
    ap.add_argument(
        "--keep-open",
        action="store_true",
        help="leave the app running after the checks (for a look at the UI)",
    )
    args = ap.parse_args()

    if not EXE.is_file():
        print(f"ERROR: {EXE} not found - run tools/build_exe.py first.")
        return 2

    print("what was packaged:")
    for name in ("ffmpeg.exe", "ffprobe.exe"):
        check(f"{name} sits beside the exe", (DIST / name).is_file(), True)
    models = DIST / "models"
    check(
        "models/ folder was populated",
        sorted(p.name for p in models.glob("*.onnx")) if models.is_dir() else [],
        lambda got: len(got) >= 3,
    )

    port, token = _free_port(), secrets.token_urlsafe(24)
    with tempfile.TemporaryDirectory(prefix="vibe-smoke-") as tmp:
        env = {
            **os.environ,
            "GENRE_PORT": str(port),
            "GENRE_TOKEN": token,  # the loopback guard the shell normally sets
            "GENRE_DB": str(Path(tmp) / "smoke.db"),  # never the real library
            # a clean machine's PATH: nothing of this dev box can stand in for the
            # bundle (see the module docstring)
            "PATH": os.pathsep.join(
                [
                    os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "system32"),
                    os.environ.get("SystemRoot", r"C:\Windows"),
                ]
            ),
        }
        base = f"http://127.0.0.1:{port}"
        print(f"launching {EXE.name} on port {port} ...")
        proc = subprocess.Popen(  # nosec B603  # the exe we just built, fixed args, no shell
            [str(EXE)],
            cwd=str(DIST),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.time() + args.timeout
            status = body = None
            while time.time() < deadline:
                if proc.poll() is not None:
                    print(
                        f"FAIL: the app exited on its own (code {proc.returncode}) "
                        f"before serving a request."
                    )
                    return 1
                status, body = _get(f"{base}/status?k={token}")
                if status == 200:
                    break
                time.sleep(1.0)

            print("backend:")
            check("answers /status within the timeout", status, 200)
            if status != 200:
                print(
                    f"\nFAIL: never answered ({body!r}). The app started but its backend "
                    f"did not come up - check the backend log the shell writes."
                )
                return 1

            s = json.loads(body)
            print("what the bundle provides:")
            check("reports a version", bool(s.get("version")), True)
            note("version", s.get("version"))
            check("ffmpeg resolves with nothing on PATH", s.get("ffmpeg"), True)
            check("ffprobe resolves with nothing on PATH", s.get("ffprobe"), True)
            # and it is the bundled copy, not something the machine happened to have
            path = s.get("ffmpeg_path") or ""
            check(
                "the ffmpeg it found is the bundled one",
                path and Path(path).resolve().is_relative_to(DIST.resolve()),
                True,
            )
            note("ffmpeg_path", path)
            check(
                "onnxruntime offers at least one provider", bool(s.get("providers_available")), True
            )
            note("providers", s.get("providers_available"))
            if not s.get("gpu_available"):
                note("gpu", "no DmlExecutionProvider - CPU only on this machine")

            print("licensing:")
            # mutagen (GPL-2.0) used to be imported into the process and bundled
            # into the PYZ. Nothing copyleft may ship in a product meant to be
            # sold, and "I removed the import" is not evidence -- the archive is.
            # See docs/PROVENANCE.md.
            toc = ROOT / "build" / "Vibe Identify" / "PYZ-00.toc"
            if toc.is_file():
                bundled = toc.read_text(encoding="utf-8", errors="replace").lower()
                for pkg in ("mutagen",):
                    check(f"no {pkg} in the bundle (copyleft)", pkg in bundled, False)
            else:
                note("PYZ toc", "not found - build first to check what was bundled")

            print("reading a real file end to end:")
            # The functional counterpart to the check above: tags are read with
            # ffprobe now, and "the module imports" is not the same as "the
            # packaged app can actually read a tag off a file". Analyse a short
            # generated track and see its title come back.
            track = Path(tmp) / "smoke track.mp3"
            if _make_tagged_track(track, "Smoke Test Title"):
                st, resp = _post_file(f"{base}/analyze?k={token}", track, timeout=120)
                check("analyses an uploaded file", st, 200)
                if st == 200:
                    j = json.loads(resp)
                    check(
                        "reads the title from the file's tags", j.get("title"), "Smoke Test Title"
                    )
                    note("bpm / key", (j.get("bpm"), j.get("key"), j.get("scale")))
            else:
                note("tag round-trip", "skipped - could not generate a test file")

            print("bundled web assets:")
            ui_status, ui = _get(f"{base}/?k={token}")
            check("serves the UI page", ui_status, 200)
            check("the page is the app", b"Vibe" in (ui or b""), True)
            css_status, _ = _get(f"{base}/static/app.css?k={token}")
            check("serves static assets from the bundle", css_status, 200)

            print(
                "\n"
                + (
                    "PASS - the built exe runs."
                    if _ok
                    else "FAIL - the build produced a folder that does not work."
                )
            )
            if args.keep_open:
                input("\nleft running; press Enter to close it ...")
            return 0 if _ok else 1
        finally:
            if not args.keep_open:
                _kill_tree(proc)


if __name__ == "__main__":
    sys.exit(main())
