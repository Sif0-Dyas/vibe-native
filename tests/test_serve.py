"""waitress: sizing, the request log line, and NDJSON streaming through a real server.

The streaming test runs the app under a real waitress server on a loopback port
(temp DB via the client fixture, FAKE mode, a slowed analyzer) and reads /batch
over a real socket, timing each line -- lines must arrive while the batch is
still running, not all at once at the end.
"""

import http.client
import importlib
import json
import logging
import threading
import time

from conftest import TEST_TOKEN
from vibenative import serve

SLOW_S = 0.3


def test_thread_count_covers_the_batch_cap_plus_ui():
    assert serve.THREADS == serve.MAX_BATCH_WORKERS + serve.UI_THREADS
    assert serve.UI_THREADS >= 2


def test_each_request_logs_method_path_status_but_never_the_token(client, caplog):
    with caplog.at_level(logging.INFO, logger="vibenative.requests"):
        assert client.get("/library", query_string={"k": TEST_TOKEN}).status_code == 200
        anon = client.application.test_client()
        assert anon.get("/library").status_code == 403
    lines = [r.getMessage() for r in caplog.records if r.name == "vibenative.requests"]
    assert "GET /library 200" in lines and "GET /library 403" in lines
    assert TEST_TOKEN not in caplog.text


def _write_wavs(folder, n):
    import io
    import struct
    import wave

    folder.mkdir()
    for i in range(n):
        buf = io.BytesIO()
        w = wave.open(buf, "w")
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(struct.pack("<800h", *([i + 1] * 800)))
        w.close()
        (folder / f"{i:02d}.wav").write_bytes(buf.getvalue())


def test_batch_ndjson_streams_through_waitress(client, monkeypatch, tmp_path):
    mod = importlib.import_module("vibenative.routes.analysis")
    real_analyze = mod.analyze

    def slow_analyze(path):
        time.sleep(SLOW_S)
        return real_analyze(path)

    monkeypatch.setattr(mod, "analyze", slow_analyze)
    _write_wavs(tmp_path / "lib", 10)

    srv = serve.create_server(client.application, "127.0.0.1", 0)
    port = srv.effective_port
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        body = json.dumps({"path": str(tmp_path / "lib"), "workers": 3})
        t0 = time.monotonic()
        conn.request(
            "POST",
            f"/batch?k={TEST_TOKEN}",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        assert resp.status == 200
        arrivals = []
        while line := resp.readline():
            if line.strip():
                arrivals.append((time.monotonic() - t0, json.loads(line)))
        conn.close()
    finally:
        srv.close()
        t.join(timeout=5)

    first, *results, final = arrivals
    assert first[1]["total"] == 10
    assert len(results) == 10 and all(r["ok"] for _, r in results)
    assert final[1] == {"done": True, "cancelled": False, "processed": 10, "total": 10}
    # Streamed, not buffered: the first result is in hand well before the batch
    # ends (10 files at 0.3 s over 3 workers take ~1.2 s), and results arrive in
    # several separate bursts rather than one.
    assert results[0][0] < final[0] - 2 * SLOW_S
    gaps = [b[0] - a[0] for a, b in zip(results, results[1:], strict=False)]
    assert sum(g > SLOW_S / 2 for g in gaps) >= 2
