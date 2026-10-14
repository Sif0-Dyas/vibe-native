"""Cancelling a /batch: explicitly, by the client going away, and one job among two.

FAKE mode with a slowed analyzer, so a batch is still running when the test acts.
Each job's executor is captured (to check it was shut down) and its worker threads
are found by name (``batch-<job>_N``) to check none survive.
"""

import importlib
import io
import json
import struct
import threading
import time
import wave
from contextlib import closing

import pytest

SLOW_S = 0.15


def _wav(sample):
    buf = io.BytesIO()
    w = wave.open(buf, "w")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(8000)
    w.writeframes(struct.pack("<800h", *([sample] * 800)))
    w.close()
    return buf.getvalue()


def _folder(root, n, offset=0):
    root.mkdir(parents=True)
    for i in range(n):
        (root / f"{i:02d}.wav").write_bytes(_wav(offset + i + 1))  # distinct content each
    return root


@pytest.fixture()
def batch(client, monkeypatch):
    """The live routes.analysis module, with a slowed analyzer and a recording executor."""
    mod = importlib.import_module("vibenative.routes.analysis")
    calls, executors = [], []
    real_analyze = mod.analyze

    def slow_analyze(path):
        calls.append(path.name)
        time.sleep(SLOW_S)
        return real_analyze(path)

    class RecordingExecutor(mod.ThreadPoolExecutor):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            executors.append(self)

    monkeypatch.setattr(mod, "analyze", slow_analyze)
    monkeypatch.setattr(mod, "ThreadPoolExecutor", RecordingExecutor)
    return mod, calls, executors


def _start(client, folder):
    r = client.post("/api/v1/batch", json={"path": str(folder), "workers": 3}, buffered=False)
    assert r.status_code == 200
    lines = iter(r.response)
    job_line = json.loads(next(lines))  # {"job": id}, sent before the folder walk
    total_line = json.loads(next(lines))  # {"total": N}, once the walk is done
    assert set(job_line) == {"job"} and set(total_line) == {"total"}
    return r, lines, {**job_line, **total_line}


def _job_threads(job):
    return [t for t in threading.enumerate() if t.name.startswith(f"batch-{job}")]


def _assert_fully_stopped(mod, executors, job):
    assert executors and all(ex._shutdown for ex in executors)
    assert _job_threads(job) == []
    assert job not in mod._BATCH_JOBS


def _tracks_in_db():
    from vibenative.db import db

    with closing(db()) as conn:
        return conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]


def test_cancel_after_two_of_twenty(client, batch, tmp_path):
    mod, calls, executors = batch
    r, lines, first = _start(client, _folder(tmp_path / "lib", 20))
    job = first["job"]
    assert first["total"] == 20 and job in mod._BATCH_JOBS

    got = [json.loads(next(lines)), json.loads(next(lines))]
    assert client.post(f"/api/v1/batch/{job}/cancel").status_code == 200
    rest = [json.loads(x) for x in lines]  # drains what was already running, then ends

    final = rest[-1]
    results = got + rest[:-1]
    assert final == {"done": True, "cancelled": True, "processed": len(results), "total": 20}
    assert 2 <= final["processed"] < 20
    assert final["processed"] <= 2 + 3  # at most the 3 that were in flight finished after
    assert len(calls) == final["processed"]  # nothing else ever started
    # results that finished after the cancel were still cached
    assert _tracks_in_db() == final["processed"]
    _assert_fully_stopped(mod, executors, job)
    assert client.post(f"/api/v1/batch/{job}/cancel").status_code == 404  # gone once ended


def test_client_disconnect_shuts_the_executor_down(client, batch, tmp_path):
    mod, calls, executors = batch
    r, lines, first = _start(client, _folder(tmp_path / "lib", 20))
    job = first["job"]
    next(lines)
    next(lines)
    r.close()  # what the server does when the browser goes away: GeneratorExit at the yield

    assert 2 <= len(calls) <= 2 + 3 < 20  # only what was already in flight ran
    assert _tracks_in_db() == len(calls)  # and it finished and was cached
    _assert_fully_stopped(mod, executors, job)


def test_cancelling_one_job_leaves_a_concurrent_one_alone(client, batch, tmp_path):
    mod, calls, executors = batch
    ra, a_lines, a_first = _start(client, _folder(tmp_path / "a", 8))
    rb, b_lines, b_first = _start(client, _folder(tmp_path / "b", 6, offset=100))
    a_job, b_job = a_first["job"], b_first["job"]
    assert a_job != b_job

    next(a_lines)
    assert client.post(f"/api/v1/batch/{a_job}/cancel").status_code == 200
    b_rest = [json.loads(x) for x in b_lines]
    a_rest = [json.loads(x) for x in a_lines]

    assert b_rest[-1] == {"done": True, "cancelled": False, "processed": 6, "total": 6}
    assert all(x["ok"] for x in b_rest[:-1])
    assert a_rest[-1]["cancelled"] is True and a_rest[-1]["processed"] < 8
    assert len(executors) == 2
    _assert_fully_stopped(mod, executors, a_job)
    _assert_fully_stopped(mod, executors, b_job)


def test_cancel_of_an_unknown_job_is_404(client):
    assert client.post("/api/v1/batch/not-a-job/cancel").status_code == 404


def test_cancel_during_the_folder_walk(client, batch, tmp_path, monkeypatch):
    # The job id arrives before the walk; a cancel while walking ends the stream
    # with the cancelled line, processed 0, and no total ever sent.
    from conftest import authed

    mod, calls, executors = batch
    real = _folder(tmp_path / "lib", 1) / "00.wav"
    yielded = []

    def slow_walk(folder):
        for _ in range(5000):
            yielded.append(1)
            time.sleep(0.002)  # a big, slow tree: ~10 s if walked to the end
            yield real

    monkeypatch.setattr(mod, "_iter_folder", slow_walk)
    r = client.post("/api/v1/batch", json={"path": str(tmp_path / "lib")}, buffered=False)
    lines = iter(r.response)
    job = json.loads(next(lines))["job"]  # before the walk has started

    got = []
    reader = threading.Thread(target=lambda: got.extend(json.loads(x) for x in lines))
    reader.start()  # drives the walk
    time.sleep(0.3)  # well into the walk
    assert authed(client.application).post(f"/api/v1/batch/{job}/cancel").status_code == 200
    reader.join(timeout=10)
    assert not reader.is_alive()

    assert got == [{"done": True, "cancelled": True, "processed": 0, "total": None}]
    assert 0 < len(yielded) < 5000  # the walk stopped early
    assert calls == []  # nothing was analysed
    _assert_fully_stopped(mod, executors, job)


# --- guards: folders that are never a music library, and big batches -----------


@pytest.fixture()
def profile(tmp_path, monkeypatch):
    """A stand-in user profile with Roaming/Local app data, as the env describes it."""
    from pathlib import Path

    home = tmp_path / "Users" / "someone"
    roaming, local = home / "AppData" / "Roaming", home / "AppData" / "Local"
    for d in (roaming, local):
        d.mkdir(parents=True)
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("APPDATA", str(roaming))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    return home


@pytest.mark.parametrize(
    "which, words",
    [
        ("drive", "is the Windows drive — pick a music folder instead."),
        ("home", "whole user folder"),
        ("appdata", "application data"),
        ("localappdata", "application data"),
        ("AppData", "application data"),
    ],
)
def test_batch_refuses_folders_that_are_never_a_library(client, profile, monkeypatch, which, words):
    import os
    from pathlib import Path

    # The Windows drive is the one holding %WINDIR%: here, the profile's drive.
    monkeypatch.setenv("WINDIR", str(Path(profile.anchor) / "Windows"))

    folder = {
        "drive": Path(profile.anchor),
        "home": profile,
        "appdata": Path(os.environ["APPDATA"]),
        "localappdata": Path(os.environ["LOCALAPPDATA"]),
        "AppData": profile / "AppData",
    }[which]
    # buffered=False and no iteration: a guard that failed must not walk a drive.
    r = client.post("/api/v1/batch", json={"path": str(folder)}, buffered=False)
    assert r.status_code == 400
    assert words in json.loads(r.get_data())["error"]
    r.close()
    # the check ignores case, as Windows does
    r = client.post("/api/v1/batch", json={"path": str(folder).upper()}, buffered=False)
    assert r.status_code == 400
    r.close()


def test_a_folder_inside_app_data_is_still_allowed(client, batch, profile):
    import os
    from pathlib import Path

    inner = _folder(Path(os.environ["LOCALAPPDATA"]) / "Temp" / "unzipped", 2)
    r, lines, first = _start(client, inner)
    assert first["total"] == 2
    assert [json.loads(x) for x in lines][-1]["processed"] == 2


def _read_all(lines, into):
    for chunk in lines:
        into.append(chunk)


def test_a_big_batch_waits_for_confirm(client, batch, tmp_path, monkeypatch):
    from conftest import authed

    mod, calls, executors = batch
    monkeypatch.setattr(mod, "BATCH_CONFIRM_OVER", 3)
    monkeypatch.setattr(mod, "CONFIRM_KEEPALIVE_S", 0.1)
    r = client.post(
        "/api/v1/batch", json={"path": str(_folder(tmp_path / "lib", 5))}, buffered=False
    )
    lines = iter(r.response)
    job = json.loads(next(lines))["job"]
    assert json.loads(next(lines)) == {"total": 5, "needs_confirm": True, "stage": "count"}

    got = []
    reader = threading.Thread(target=_read_all, args=(lines, got))
    reader.start()
    time.sleep(0.6)
    assert calls == []  # waiting: nothing analysed
    assert got and all(not c.strip() for c in got)  # only keepalives so far
    other = authed(client.application)
    assert other.post(f"/api/v1/batch/{job}/confirm", json={}).status_code == 400  # must say true
    assert other.post(f"/api/v1/batch/{job}/confirm", json={"confirm": True}).status_code == 200
    reader.join(timeout=10)

    rows = [json.loads(c) for c in got if c.strip()]
    assert rows[-1] == {"done": True, "cancelled": False, "processed": 5, "total": 5}
    assert len(rows) == 6 and len(calls) == 5
    _assert_fully_stopped(mod, executors, job)


def test_cancel_at_the_confirm_prompt(client, batch, tmp_path, monkeypatch):
    from conftest import authed

    mod, calls, executors = batch
    monkeypatch.setattr(mod, "BATCH_CONFIRM_OVER", 3)
    monkeypatch.setattr(mod, "CONFIRM_KEEPALIVE_S", 0.1)
    r = client.post(
        "/api/v1/batch", json={"path": str(_folder(tmp_path / "lib", 5))}, buffered=False
    )
    lines = iter(r.response)
    job = json.loads(next(lines))["job"]
    next(lines)  # the needs_confirm total
    got = []
    reader = threading.Thread(target=_read_all, args=(lines, got))
    reader.start()
    time.sleep(0.3)
    assert authed(client.application).post(f"/api/v1/batch/{job}/cancel").status_code == 200
    reader.join(timeout=10)
    rows = [json.loads(c) for c in got if c.strip()]
    assert rows == [{"done": True, "cancelled": True, "processed": 0, "total": 5}]
    assert calls == []
    _assert_fully_stopped(mod, executors, job)


def test_confirm_of_an_unknown_job_is_404(client):
    assert client.post("/api/v1/batch/nope/confirm", json={"confirm": True}).status_code == 404


# --- a whole drive: refused if it's the Windows drive, else asked about twice ---

# Tracks the walk must find, in folders it must enter -- one of them alone in its
# folder -- and the trees it must never enter, at the top and deeper down.
DRIVE_TRACKS = ["Music/02.wav", "Music/Album/01.wav", "Single/only.wav", "a/b/c/deep.wav"]
DRIVE_SKIPPED = [
    "$RECYCLE.BIN/S-1-5-21/deleted.wav",
    "System Volume Information/x.wav",
    "Windows/Media/ding.wav",
    "Program Files/App/s.wav",
    "Program Files (x86)/App/s.wav",
    "ProgramData/s.wav",
    "Users/me/Music/u.wav",
    "Music/AppData/s.wav",
    "Music/.git/s.wav",
    "Music/node_modules/s.wav",
    "Music/__pycache__/s.wav",
    "Music/Album/Temp/t.wav",
    "pytest-of-me/p.wav",
    "a/RECYCLED/../$Recycle.Bin/r.wav",  # a different spelling of the same name
]


@pytest.fixture()
def drive(batch, tmp_path, monkeypatch):
    """tmp_path/F treated as a drive root (not the Windows one), filled with
    DRIVE_TRACKS and DRIVE_SKIPPED. Records each walk and each folder opened."""
    import os

    mod = batch[0]
    root = tmp_path / "F"
    for i, rel in enumerate(DRIVE_TRACKS + DRIVE_SKIPPED, 1):
        f = (root / rel).resolve()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(_wav(100 + i))
    monkeypatch.setattr(mod, "_is_drive_root", lambda f: mod._norm(f.resolve()) == mod._norm(root))
    monkeypatch.setenv("WINDIR", str(tmp_path / "C" / "Windows"))  # Windows lives elsewhere

    walks, opened = [], []
    real_walk, real_scandir = mod._iter_folder, os.scandir
    monkeypatch.setattr(mod, "_iter_folder", lambda f: (walks.append(f), real_walk(f))[1])
    monkeypatch.setattr(os, "scandir", lambda p=".": (opened.append(str(p)), real_scandir(p))[1])
    return root, walks, opened


def _until(got, pred, timeout=5.0):
    """The first non-blank streamed line matching ``pred``, waiting for it."""
    end = time.time() + timeout
    while time.time() < end:
        for chunk in list(got):
            if chunk.strip() and pred(json.loads(chunk)):
                return json.loads(chunk)
        time.sleep(0.05)
    raise AssertionError(f"no such line in {got!r}")


def _open_drive(client, root):
    r = client.post("/api/v1/batch", json={"path": str(root)}, buffered=False)
    assert r.status_code == 200
    lines = iter(r.response)
    job = json.loads(next(lines))["job"]
    got = []
    reader = threading.Thread(target=_read_all, args=(lines, got))
    reader.start()
    return job, got, reader


def test_a_drive_root_asks_twice_and_walks_it_all(client, batch, drive, monkeypatch):
    from conftest import authed

    mod, calls, executors = batch
    root, walks, opened = drive
    monkeypatch.setattr(mod, "CONFIRM_KEEPALIVE_S", 0.1)
    job, got, reader = _open_drive(client, root)
    other = authed(client.application)

    # 1. Before any walking: "the whole of F:\ -- continue?"
    first = _until(got, lambda d: d.get("stage") == "drive")
    assert first == {"needs_confirm": True, "stage": "drive", "drive": str(root)}
    time.sleep(0.3)
    assert walks == [] and calls == []
    # an answer to the other question is not a yes to this one
    assert (
        other.post(
            f"/api/v1/batch/{job}/confirm", json={"confirm": True, "stage": "count"}
        ).status_code
        == 409
    )
    assert (
        other.post(
            f"/api/v1/batch/{job}/confirm", json={"confirm": True, "stage": "drive"}
        ).status_code
        == 200
    )

    # 2. After the walk, the count -- asked for a drive however few files it holds.
    second = _until(got, lambda d: d.get("stage") == "count")
    assert second == {"total": len(DRIVE_TRACKS), "needs_confirm": True, "stage": "count"}
    assert len(walks) == 1
    time.sleep(0.3)
    assert calls == []
    assert (
        other.post(
            f"/api/v1/batch/{job}/confirm", json={"confirm": True, "stage": "drive"}
        ).status_code
        == 409
    )
    assert (
        other.post(
            f"/api/v1/batch/{job}/confirm", json={"confirm": True, "stage": "count"}
        ).status_code
        == 200
    )
    reader.join(timeout=10)

    rows = [json.loads(c) for c in got if c.strip()]
    assert rows[-1] == {"done": True, "cancelled": False, "processed": 4, "total": 4}
    assert sorted(calls) == sorted(rel.rsplit("/", 1)[1] for rel in DRIVE_TRACKS)
    _assert_fully_stopped(mod, executors, job)


def test_the_walk_never_enters_a_skipped_folder(client, batch, drive, monkeypatch):
    from conftest import authed

    mod = batch[0]
    root, walks, opened = drive
    job, got, reader = _open_drive(client, root)
    other = authed(client.application)
    _until(got, lambda d: d.get("stage") == "drive")
    other.post(f"/api/v1/batch/{job}/confirm", json={"confirm": True, "stage": "drive"})
    _until(got, lambda d: d.get("stage") == "count")
    other.post(f"/api/v1/batch/{job}/cancel")
    reader.join(timeout=10)

    entered = [p for p in opened if p.startswith(str(root))]
    assert entered  # the walk did run
    for p in entered:
        parts = [part.casefold() for part in p[len(str(root)) :].replace("\\", "/").split("/")]
        assert "$recycle.bin" not in parts, p
        assert not any(mod._skip_dir(part) for part in parts), p


def test_cancel_at_the_drive_question_walks_nothing(client, batch, drive):
    from conftest import authed

    mod, calls, executors = batch
    root, walks, opened = drive
    job, got, reader = _open_drive(client, root)
    _until(got, lambda d: d.get("stage") == "drive")
    assert authed(client.application).post(f"/api/v1/batch/{job}/cancel").status_code == 200
    reader.join(timeout=10)

    rows = [json.loads(c) for c in got if c.strip()]
    assert rows[-1] == {"done": True, "cancelled": True, "processed": 0, "total": None}
    assert walks == [] and calls == []
    assert not [p for p in opened if p.startswith(str(root))]
    _assert_fully_stopped(mod, executors, job)


def test_cancel_at_the_count_walks_but_analyses_nothing(client, batch, drive):
    from conftest import authed

    mod, calls, executors = batch
    root, walks, opened = drive
    job, got, reader = _open_drive(client, root)
    other = authed(client.application)
    _until(got, lambda d: d.get("stage") == "drive")
    other.post(f"/api/v1/batch/{job}/confirm", json={"confirm": True, "stage": "drive"})
    _until(got, lambda d: d.get("stage") == "count")
    assert other.post(f"/api/v1/batch/{job}/cancel").status_code == 200
    reader.join(timeout=10)

    rows = [json.loads(c) for c in got if c.strip()]
    assert rows[-1] == {"done": True, "cancelled": True, "processed": 0, "total": 4}
    assert len(walks) == 1 and calls == []
    assert _tracks_in_db() == 0
    _assert_fully_stopped(mod, executors, job)


def test_the_windows_drive_is_found_by_windir_not_assumed(client, batch, drive, monkeypatch):
    # Windows installed on "F:" this time: that drive is the one refused.
    root, walks, opened = drive
    monkeypatch.setenv("WINDIR", str(root / "Windows"))
    r = client.post("/api/v1/batch", json={"path": str(root)}, buffered=False)
    assert r.status_code == 400
    assert json.loads(r.get_data())["error"] == (
        f"{root} is the Windows drive \u2014 pick a music folder instead."
    )
    r.close()
    assert walks == []
