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
    r = client.post("/batch", json={"path": str(folder), "workers": 3}, buffered=False)
    assert r.status_code == 200
    lines = iter(r.response)
    first = json.loads(next(lines))
    return r, lines, first


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
    assert client.post(f"/batch/{job}/cancel").status_code == 200
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
    assert client.post(f"/batch/{job}/cancel").status_code == 404  # gone once ended


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
    assert client.post(f"/batch/{a_job}/cancel").status_code == 200
    b_rest = [json.loads(x) for x in b_lines]
    a_rest = [json.loads(x) for x in a_lines]

    assert b_rest[-1] == {"done": True, "cancelled": False, "processed": 6, "total": 6}
    assert all(x["ok"] for x in b_rest[:-1])
    assert a_rest[-1]["cancelled"] is True and a_rest[-1]["processed"] < 8
    assert len(executors) == 2
    _assert_fully_stopped(mod, executors, a_job)
    _assert_fully_stopped(mod, executors, b_job)


def test_cancel_of_an_unknown_job_is_404(client):
    assert client.post("/batch/not-a-job/cancel").status_code == 404
