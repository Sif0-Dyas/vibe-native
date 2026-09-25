"""Analysis routes: analyze / refine / batch, plus the audio and
waveform media endpoints and their upload helpers."""

import os
import re
import tempfile
import threading
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import closing, contextmanager
from pathlib import Path

from flask import Response, jsonify, request, send_file

from .. import insight
from ..analysis import (
    FINE_HOP_SECONDS,
    analyze,
    build_payload,
    load_samples_for_waveform,
    read_tags,
    read_title,
    refine_segments,
    waveform_minmax,
)
from ..config import AUDIO_EXTS, FAKE, log
from ..db import (
    _db_lock,
    cache_get,
    cache_put,
    db,
    file_hash,
    waveform_cache_get,
    waveform_cache_put,
)
from ..serve import MAX_BATCH_WORKERS
from ._shared import bp


# ----------------------------------------------------------------------------
# Upload plumbing shared by /analyze, /refine: validate the audio
# upload, stage it to a temp file, and always clean up.
# ----------------------------------------------------------------------------
class UploadError(Exception):
    """Bad/missing upload -- carries the HTTP status the route should return."""

    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


def upload_label(filename):
    """The browser-supplied filename as a display label: the last path component
    only, whichever separator the client used. It is only ever a label (the upload
    itself goes to a temp file), so it keeps its spaces and non-ASCII characters --
    secure_filename would turn "Artist - Title.mp3" into "Artist_-_Title.mp3" and
    break the artist fallback. Anything that uses a name as a PATH must still pass
    it through secure_filename (see routes/training.py)."""
    return re.split(r"[\\/]", filename or "")[-1]


def _check_upload(f, missing_msg="no file received"):
    """Validate a Werkzeug FileStorage; raise UploadError, else return its suffix."""
    if f is None or not f.filename:
        raise UploadError(missing_msg, 400)
    suffix = Path(f.filename).suffix.lower()
    if suffix not in AUDIO_EXTS:
        raise UploadError(f"unsupported file type: {suffix or 'none'}", 415)
    return suffix


@contextmanager
def saved_upload(f, missing_msg="no file received"):
    """Validate `f`, save it to a temp file, yield its Path, and unlink on exit."""
    suffix = _check_upload(f, missing_msg)
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        f.save(tmp.name)
        tmp.close()
        yield Path(tmp.name)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def _apply_key_correction(h, payload):
    """Overlay a human-corrected key onto an analysis payload (in place).
    Corrections live outside the payload so re-analysis cannot clobber them, so
    every path that serves a payload has to put them back."""
    from ..db import key_label_get

    correction = key_label_get(h)
    if not correction:
        payload.setdefault("key_source", "detector")
        return payload
    from ..analysis import CAMELOT

    key, scale = correction
    payload["key"], payload["scale"] = key, scale
    payload["camelot"] = CAMELOT.get((key, scale))
    payload["key_source"] = "manual"
    return payload


@bp.post("/analyze")
def analyze_route():
    f = request.files.get("file")
    try:
        with saved_upload(f) as p:
            # cache-first: identical audio content = identical hash = instant return
            h = file_hash(p)
            cached = cache_get(h)
            if cached:
                _apply_key_correction(h, cached)
                _backfill_waveform(h, p)
                return jsonify(_cached_response(cached, h))

            name = upload_label(f.filename)
            title = read_title(p) or Path(name).stem
            tags = read_tags(p)
            result = analyze(p)  # analyze() locks its own model inference
            emb = result.pop("emb_mean", None)
            wave = result.pop("wave", None)  # DAW-style min/max/rms -> its own cache
            payload = build_payload(name, None, title, tags, result)
            nc = insight.check(emb, *insight.dominant(payload)) if emb is not None else None
            if nc:
                payload["neighbor_check"] = nc  # flag likely misreads
            cache_put(h, name, None, title, payload, emb)
            if wave is not None:
                waveform_cache_put(h, wave)
            payload["hash"] = h
            payload["cached"] = False
            return jsonify(payload)
    except UploadError as e:
        return jsonify({"error": str(e)}), e.status
    except Exception:
        log.exception("request failed")
        return jsonify({"error": "internal error"}), 500


@bp.post("/refine")
def refine_route():
    """Re-analyze one track at fine resolution; returns a denser segment list."""
    f = request.files.get("file")
    try:
        _check_upload(f)
        if FAKE:
            import hashlib
            import random

            seed = hashlib.md5(("fine" + f.filename).encode()).hexdigest()  # nosec B324  # deterministic seed for FAKE-mode data, not security
            rng = random.Random(seed)  # nosec B311  # deterministic FAKE-mode PRNG, not security
            pool = [
                "Drum n Bass",
                "Trance",
                "Dubstep",
                "Hard Techno",
                "Hardstyle",
                "House",
                "Techno",
                "Jungle",
                "Breakcore",
                "Psy-Trance",
            ]
            rng.shuffle(pool)
            seg_styles = [pool[0]] * 4 + pool[1:3]
            segments = []
            for _ in range(rng.randint(30, 60)):
                segments += [rng.choice(seg_styles)] * rng.randint(3, 12)
            frames = []
            for s in segments:
                others = rng.sample([p for p in pool if p != s], 3)
                top = round(rng.uniform(0.25, 0.6), 3)
                rest = sorted(
                    (round(rng.uniform(0.02, top - 0.02), 3) for _ in range(3)), reverse=True
                )
                frames.append([[s, top]] + [[others[j], rest[j]] for j in range(3)])
            return jsonify(
                {"segments": segments, "frames": frames, "hop_seconds": FINE_HOP_SECONDS}
            )

        with saved_upload(f) as p:
            segments, frames = refine_segments(p)  # locks its own inference
            return jsonify(
                {"segments": segments, "frames": frames, "hop_seconds": FINE_HOP_SECONDS}
            )
    except UploadError as e:
        return jsonify({"error": str(e)}), e.status
    except Exception:
        log.exception("request failed")
        return jsonify({"error": "internal error"}), 500


def _backfill_filepath(h, path):
    """Record or repair a cached track's server-side path on a re-scan:

    - fills a BLANK path (drop-analyzed rows stored none), and
    - RE-POINTS a STALE one -- if the stored path no longer exists on disk but the
      freshly-scanned `path` does, the file was moved/renamed. The content hash
      matched (this is a cache hit), so it's the same track: follow it.

    A stored path that still resolves to a real file is left untouched (so scanning
    a duplicate copy elsewhere doesn't thrash the original). Keeps audio preview,
    on-demand waveform, and section overrides working after a move."""
    with _db_lock, closing(db()) as conn, conn as c:
        row = c.execute("SELECT filepath FROM tracks WHERE hash=?", (h,)).fetchone()
        if row is None:
            return
        current = row[0] or ""
        if not current or not Path(current).is_file():  # blank, or stale (moved away)
            c.execute("UPDATE tracks SET filepath=? WHERE hash=?", (path, h))


def _segment_overrides(h):
    """The persisted segment overrides for a track, oldest span first. Each carries
    its rowid as ``id`` so the client can target it for removal."""
    with _db_lock, closing(db()) as conn, conn as c:
        rows = c.execute(
            "SELECT rowid, start_s, end_s, genre FROM segment_overrides WHERE hash=? "
            "ORDER BY start_s",
            (h,),
        ).fetchall()
    return [{"id": r[0], "start_s": r[1], "end_s": r[2], "genre": r[3]} for r in rows]


def _backfill_waveform(h, upload):
    """Render the detailed waveform from an upload we are already holding.

    A track dragged in and analysed without ever being linked to a folder has
    no file the server can reach, so its waveform can only ever come from the
    browser's copy. The client used to discover that by asking GET /waveform,
    getting a 404, and then re-uploading the same file to POST /waveform --
    which the server hashed a second time. On a cache hit the upload is right
    here, already hashed, so the one decode happens now and the second upload
    never has to.
    """
    if waveform_cache_get(h) is not None:
        return
    with _db_lock, closing(db()) as conn, conn as c:
        row = c.execute("SELECT filepath FROM tracks WHERE hash=?", (h,)).fetchone()
    if row and row[0] and Path(row[0]).is_file():
        return  # GET /waveform can decode that itself
    try:
        waveform_cache_put(h, waveform_minmax(load_samples_for_waveform(upload)))
    except Exception:
        log.exception("waveform backfill failed for %s", h)  # the envelope stands


def _cached_response(cached, h, **extra):
    """A cached payload dressed the way every cache hit is returned.

    ``adjusted`` is the blend after the track's manual weight adjustments (or
    None), sent with every cached payload so a track nudged on the map reads
    the same the moment it lands in the Analyzer -- the alternative was a
    second round-trip per row just to find out most rows had nothing to say.
    """
    from ..weights import read_with_steps

    cached.update({"hash": h, "cached": True, **extra})
    cached["segment_overrides"] = _segment_overrides(h)
    cached["adjusted"] = read_with_steps(cached)
    return cached


@bp.get("/track/<h>")
def track_route(h):
    """Return a cached track's full analysis payload by content hash — the same shape
    /analyze returns on a cache hit — so the Library tab can load it into the List
    without re-analyzing. 404 if it isn't cached."""
    cached = cache_get(h)
    if not cached:
        return jsonify({"error": "not in library"}), 404
    return jsonify(_cached_response(cached, h))


# ----------------------------------------------------------------------------
# Audio preview: stream a previously-analyzed track for in-app playback
# ----------------------------------------------------------------------------
AUDIO_MIME = {
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".aif": "audio/aiff",
    ".aiff": "audio/aiff",
    ".aifc": "audio/aiff",
    ".wma": "audio/x-ms-wma",
}


@bp.get("/audio/<h>")
def audio_route(h):
    """Stream a track's audio by content hash for the in-app preview player.
    Read-only; serves ONLY files already recorded in the analysis DB (so this is
    not an arbitrary-file endpoint). Supports HTTP Range so the browser can seek.
    Browser-dropped files have no server path -- those play client-side via a
    blob URL instead, so a 404 here is expected for them."""
    with _db_lock, closing(db()) as conn, conn as c:
        row = c.execute("SELECT filepath, filename FROM tracks WHERE hash=?", (h,)).fetchone()
    if not row or not row[0]:
        return jsonify({"error": "no server-side file for this track"}), 404
    p = Path(row[0])
    if not p.is_file():
        return jsonify({"error": "file no longer exists on disk"}), 404
    mime = AUDIO_MIME.get(p.suffix.lower(), "application/octet-stream")
    return send_file(
        str(p), mimetype=mime, conditional=True, as_attachment=False, download_name=row[1] or p.name
    )


@bp.get("/waveform/<h>")
def waveform_route(h):
    """A DAW-style min/max/rms waveform for a track. Served from the permanent
    cache (pre-filled at analysis time); for older tracks with no cache yet, decode
    the source file once and cache it. A track with neither a cache nor a file
    (e.g. an old browser-dropped one) 404s, and the client keeps its envelope."""
    cached = waveform_cache_get(h)
    if cached:
        return jsonify(cached)
    with _db_lock, closing(db()) as conn, conn as c:
        row = c.execute("SELECT filepath FROM tracks WHERE hash=?", (h,)).fetchone()
    if not row:
        return jsonify({"error": "track not in database"}), 404
    filepath = row[0]
    if not filepath or not Path(filepath).is_file():
        return jsonify({"error": "no server-side audio to render (re-add the track)"}), 404
    try:
        samples = load_samples_for_waveform(Path(filepath))  # decode stays outside the DB lock
    except Exception:
        log.exception("waveform decode failed for %s", h)
        return jsonify({"error": "could not decode this track's audio"}), 500
    data = waveform_minmax(samples)
    waveform_cache_put(h, data)
    return jsonify(data)


@bp.post("/waveform/<h>")
def waveform_upload_route(h):
    """Build a track's detailed waveform from an uploaded copy of its audio.

    The GET above can only serve tracks it can reach: one with a cached waveform,
    or one with a server-side file to decode. A track dragged in and analysed
    without ever being linked to a folder has neither, so it was stuck drawing
    the coarse envelope forever -- there was no path by which it could ever get
    the detailed one, however many times you re-added it.

    The browser is holding the audio in those exact cases, so it sends it here.
    The upload is used for the waveform and thrown away -- no path is recorded
    (a temp file is not where the track lives) and the analysis is not touched.
    The result is cached permanently, so this happens once per track.
    """
    cached = waveform_cache_get(h)
    if cached:
        return jsonify(cached)  # raced another tab; nothing to do
    with _db_lock, closing(db()) as conn, conn as c:
        row = c.execute("SELECT hash FROM tracks WHERE hash=?", (h,)).fetchone()
    # Only for tracks already in the library: this must not become a way to have
    # the server decode arbitrary uploads under an arbitrary key.
    if not row:
        return jsonify({"error": "track not in database"}), 404
    try:
        with saved_upload(request.files.get("file")) as up:
            # The hash has to match, or a mistake (or a crafted request) would
            # file one track's waveform under another's name and the row would
            # draw someone else's audio.
            if file_hash(up) != h:
                return jsonify({"error": "this audio is not that track"}), 400
            samples = load_samples_for_waveform(up)
    except UploadError as e:
        return jsonify({"error": str(e)}), e.status
    except Exception:
        log.exception("waveform upload decode failed for %s", h)
        return jsonify({"error": "could not decode this track's audio"}), 500
    data = waveform_minmax(samples)
    waveform_cache_put(h, data)
    return jsonify(data)


def _rss_mb():
    """Current process resident-set size in MB (Windows, via ctypes); None if it
    can't be read. Used to trace memory growth during a batch so an OOM crash can
    be pinned to the file that pushed it over."""
    try:
        import ctypes
        from ctypes import wintypes

        class _PMC(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = ctypes.c_void_p  # HANDLE is pointer-sized
        psapi = ctypes.WinDLL("psapi")
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_PMC),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        c = _PMC()
        c.cb = ctypes.sizeof(_PMC)
        if psapi.GetProcessMemoryInfo(k.GetCurrentProcess(), ctypes.byref(c), c.cb):
            return round(c.WorkingSetSize / 1e6)
    except Exception:  # nosec B110  # diagnostics only — never break a scan over this
        pass
    return None


@bp.post("/clientlog")
def clientlog_route():
    """Sink for the frontend's diagnostics (batch milestones, JS heap size, uncaught
    errors). The WebView renderer can crash independently of this backend, taking
    its console with it — POSTing here lands those breadcrumbs in the same backend
    log file, so a renderer crash still leaves a trail."""
    data = request.get_json(silent=True) or {}
    msg = str(data.get("msg", ""))[:2000]
    level = data.get("level", "info")
    fn = getattr(log, level if level in ("info", "warning", "error") else "info")
    fn("[client] %s", msg)
    return ("", 204)


def _is_sidecar(path) -> bool:
    """True for metadata sidecars that merely *look* like audio.

    macOS writes an AppleDouble resource fork beside every file on a non-HFS
    volume -- ``._Track.mp3`` next to ``Track.mp3`` -- so a USB drive that has
    been on a Mac is full of 4 KB stubs carrying a real audio suffix. The
    scanner picked them up, spawned ffprobe on each, and logged the failure:
    240 of 240 failures in one 1,645-file scan were these, and not one real
    track failed. They are not errors worth reporting, just files that should
    never have been queued.
    """
    return path.name.startswith("._")


@bp.post("/batch")
def batch_route():
    """Scan a server-side folder path and analyze all audio files in parallel.
    Accepts a native Windows path (C:\\Users\\you\\Music) directly; a legacy WSL
    mount path (/mnt/c/Users/you/Music) is translated to its drive-letter form for
    muscle-memory compatibility. Returns newline-delimited JSON results (NDJSON)."""
    import json as _json
    import time as _time

    from ..legacy import wsl_to_windows

    data = request.get_json(silent=True) or {}
    folder = Path(wsl_to_windows(str(data.get("path", "")))).expanduser()
    # Bounded parallelism throttles CPU/GPU/RAM so a huge folder can't swamp the
    # machine; clamp whatever the client asks for to a safe range.
    cpu = os.cpu_count() or 4
    workers = max(1, min(int(data.get("workers", 3) or 3), cpu, MAX_BATCH_WORKERS))

    if not folder.is_dir():
        return jsonify({"error": f"not a directory: {folder}"}), 400

    files = sorted(
        p
        for p in folder.rglob("*")
        if p.is_file() and p.suffix.lower() in AUDIO_EXTS and not _is_sidecar(p)
    )
    if not files:
        return jsonify({"error": "no audio files found"}), 404

    log.info(
        "batch START: %s  (%d files, %d workers, rss=%sMB)", folder, len(files), workers, _rss_mb()
    )

    def analyze_one(path: Path):
        # Log BEFORE the heavy work (with the file size + current RSS) and FLUSH via
        # the logging handler, so if this file OOM-kills the process the last START
        # line on disk names the culprit. Kept concise; one pair of lines per file.
        try:
            size_mb = round(path.stat().st_size / 1e6, 1)
        except OSError:
            size_mb = "?"
        log.info("  · START %s (%s MB, rss=%sMB)", path.name, size_mb, _rss_mb())
        t0 = _time.time()
        try:
            h = file_hash(path)
            cached = cache_get(h)
            if cached:
                _apply_key_correction(h, cached)
                cached = _cached_response(dict(cached), h, ok=True, filepath=str(path))
                # backfill a server-side path for older drop-analyzed rows (which
                # stored none) so audio preview / DAW waveform / section overrides
                # light up for the whole library on a re-scan -- no re-analysis.
                _backfill_filepath(h, str(path))
                log.info("  · CACHED %s (%.1fs)", path.name, _time.time() - t0)
                return cached
            title = read_title(path) or path.stem
            tags = read_tags(path)
            result = analyze(path)
            emb = result.pop("emb_mean", None)
            wave = result.pop("wave", None)
            payload = build_payload(path.name, str(path), title, tags, result)
            cache_put(h, path.name, str(path), title, payload, emb)
            if wave is not None:
                waveform_cache_put(h, wave)
            payload.update({"ok": True, "hash": h, "cached": False})
            log.info("  · OK %s (%.1fs, rss=%sMB)", path.name, _time.time() - t0, _rss_mb())
            return payload
        except Exception:
            log.exception("  · FAIL %s (%.1fs)", path.name, _time.time() - t0)
            return {
                "ok": False,
                "filename": path.name,
                "filepath": str(path),
                "error": "analysis failed",
            }

    job = uuid.uuid4().hex

    def generate():
        # Registered here, not in the route: if the response is never iterated,
        # nothing is left behind. The client learns the id from the first line,
        # which is yielded only after this.
        cancel = threading.Event()
        with _BATCH_JOBS_LOCK:
            _BATCH_JOBS[job] = cancel
        ex = ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"batch-{job}")
        done = 0
        try:
            yield _json.dumps({"total": len(files), "job": job}) + "\n"
            # Lazy submission: at most `workers` files in flight, the next one
            # submitted only as one finishes -- nothing queued behind them, so a
            # cancel (or a disconnect) has only those few left to wait for.
            todo, pending = iter(files), set()

            def refill():
                while len(pending) < workers and not cancel.is_set():
                    nxt = next(todo, None)
                    if nxt is None:
                        return
                    pending.add(ex.submit(analyze_one, nxt))

            refill()
            while pending:
                finished, _ = wait(pending, return_when=FIRST_COMPLETED)
                for fut in finished:
                    pending.discard(fut)
                    done += 1
                    result = fut.result()  # analyze_one never raises; failures are dicts
                    result["progress"] = done
                    yield _json.dumps(result) + "\n"
                refill()  # after a cancel this adds nothing; running files finish, cached
            final = {"done": True, "cancelled": done < len(files), "processed": done}
            final["total"] = len(files)
            yield _json.dumps(final) + "\n"
        finally:
            # The one place a batch ends, whichever way: finished; cancelled via
            # /batch/<job>/cancel (no refills, the loop drained and fell through);
            # or the client went away (GeneratorExit raised at a yield when the
            # server closes the response). Stop new work, wait only for what is
            # already running, forget the job.
            cancel.set()
            ex.shutdown(wait=True, cancel_futures=True)
            with _BATCH_JOBS_LOCK:
                _BATCH_JOBS.pop(job, None)
            log.info("batch END: %d/%d processed, rss=%sMB", done, len(files), _rss_mb())

    return Response(generate(), mimetype="application/x-ndjson")


# Running /batch jobs: job id -> its cancel flag. An entry lives exactly as long
# as that job's generator (added at its start, removed in its finally).
_BATCH_JOBS: dict[str, threading.Event] = {}
_BATCH_JOBS_LOCK = threading.Lock()


@bp.post("/batch/<job>/cancel")
def batch_cancel_route(job):
    """Ask a running batch to stop: no new files start; the ones already being
    analysed finish (and are cached), then the stream ends with a cancelled line."""
    with _BATCH_JOBS_LOCK:
        cancel = _BATCH_JOBS.get(job)
    if cancel is None:
        return jsonify({"error": "no such batch"}), 404
    cancel.set()
    return jsonify({"ok": True, "job": job})
