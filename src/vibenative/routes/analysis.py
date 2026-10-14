"""Analysis routes: analyze / refine / batch, plus the audio and
waveform media endpoints and their upload helpers."""

import os
import re
import tempfile
import threading
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
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
from ..config import AUDIO_EXTS, log
from ..decode import UnreadableAudio
from ..hashing import file_hash
from ..metadata import probe_duration
from ..repo import tracks as tracks_repo
from ..repo.tracks import cache_get, cache_put, waveform_cache_get, waveform_cache_put
from ..serve import MAX_BATCH_WORKERS
from ..settings import current
from ..style import dominant_read, identity_fields
from ._shared import UploadError, bp


def _too_short(path):
    """``(duration, minimum)`` if ``path`` is shorter than Settings.min_duration_s,
    else None. Checked before anything is hashed, analysed or written: a short
    file never reaches the library. A length that can't be told isn't "short"."""
    minimum = current().min_duration_s
    if not minimum:
        return None
    d = probe_duration(path)
    return (d, minimum) if d is not None and d < minimum else None


# ----------------------------------------------------------------------------
# Upload plumbing shared by /analyze, /refine: validate the audio
# upload, stage it to a temp file, and always clean up.
# ----------------------------------------------------------------------------
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
    from ..repo.keys import key_label_get

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
            short = _too_short(p)
            if short:
                # Not an error and not silence either: the Analyzer shows one line.
                return jsonify(
                    {
                        "ok": False,
                        "short": True,
                        "filename": upload_label(f.filename),
                        "duration": round(short[0], 1),
                        "min_duration": short[1],
                    }
                )
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
            nc = insight.check(emb, *dominant_read(payload)) if emb is not None else None
            if nc:
                payload["neighbor_check"] = nc  # flag likely misreads
            cache_put(h, name, None, title, payload, emb)
            if wave is not None:
                waveform_cache_put(h, wave)
            payload["hash"] = h
            payload["cached"] = False
            payload.update(identity_fields(payload))
            return jsonify(payload)
    except UnreadableAudio as e:
        log.warning(
            "analyze: %s is not a readable audio file (%s)", upload_label(f.filename), e.reason
        )
        return jsonify({"error": "not a readable audio file"}), 422


@bp.post("/refine")
def refine_route():
    """Re-analyze one track at fine resolution; returns a denser segment list."""
    f = request.files.get("file")
    _check_upload(f)

    with saved_upload(f) as p:
        segments, frames = refine_segments(p)  # locks its own inference
        return jsonify({"segments": segments, "frames": frames, "hop_seconds": FINE_HOP_SECONDS})


def _backfill_filepath(h, path):
    """Record or repair a cached track's server-side path on a re-scan:

    - fills a BLANK path (drop-analyzed rows stored none), and
    - RE-POINTS a STALE one -- if the stored path no longer exists on disk but the
      freshly-scanned `path` does, the file was moved/renamed. The content hash
      matched (this is a cache hit), so it's the same track: follow it.

    A stored path that still resolves to a real file is left untouched (so scanning
    a duplicate copy elsewhere doesn't thrash the original). Keeps audio preview,
    on-demand waveform, and section overrides working after a move."""
    tracks_repo.backfill_filepath(h, path)


def _segment_overrides(h):
    """The persisted segment overrides for a track, oldest span first. Each carries
    its rowid as ``id`` so the client can target it for removal."""
    rows = tracks_repo.segment_overrides(h)
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
    row = tracks_repo.file_info(h)
    if row and row[0] and Path(row[0]).is_file():
        return  # GET /waveform can decode that itself
    try:
        waveform_cache_put(h, waveform_minmax(load_samples_for_waveform(upload)))
    except Exception:
        log.exception("waveform backfill failed for %s", h)  # the envelope stands


def _cached_response(cached, h, **extra):
    """A cached payload dressed the way every cache hit is returned.

    ``dominant_*`` is the track's identity (style.identity_fields) -- what the
    Analyzer shows and colours a row by. ``adjusted`` is the blend after the
    track's manual weight adjustments (or None), sent with every cached payload so a track nudged on the map reads
    the same the moment it lands in the Analyzer -- the alternative was a
    second round-trip per row just to find out most rows had nothing to say.
    """
    from ..weights import read_with_steps

    cached.update({"hash": h, "cached": True, **extra})
    cached["segment_overrides"] = _segment_overrides(h)
    cached["adjusted"] = read_with_steps(cached)
    cached.update(identity_fields(cached))
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
    row = tracks_repo.file_info(h)
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
    row = tracks_repo.file_info(h)
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
    # Only for tracks already in the library: this must not become a way to have
    # the server decode arbitrary uploads under an arbitrary key.
    if not tracks_repo.exists(h):
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
    raw = wsl_to_windows(str(data.get("path", ""))).strip()
    # "F:" alone is the current folder ON F: to Windows, not its root -- someone
    # who types it means the drive.
    if re.fullmatch(r"[A-Za-z]:", raw):
        raw += "\\"
    folder = Path(raw).expanduser()
    # Bounded parallelism throttles CPU/GPU/RAM so a huge folder can't swamp the
    # machine; clamp whatever the client asks for to a safe range.
    cpu = os.cpu_count() or 4
    workers = max(1, min(int(data.get("workers", 3) or 3), cpu, MAX_BATCH_WORKERS))

    if not folder.is_dir():
        return jsonify({"error": f"not a directory: {folder}"}), 400
    refusal = _refuse_folder(folder)
    if refusal:
        return jsonify({"error": refusal}), 400
    whole_drive = _is_drive_root(folder)

    def analyze_one(path: Path):
        # Log BEFORE the heavy work (with the file size) and FLUSH via
        # the logging handler, so if this file OOM-kills the process the last START
        # line on disk names the culprit. Kept concise; one pair of lines per file.
        try:
            size_mb = round(path.stat().st_size / 1e6, 1)
        except OSError:
            size_mb = "?"
        short = _too_short(path)
        if short:
            # Counted, reported in the final line, never written. No log line each:
            # a drive can hold thousands of these.
            return {
                "ok": False,
                "short": True,
                "filename": path.name,
                "filepath": str(path),
                "duration": round(short[0], 1),
            }
        log.info("  · START %s (%s MB)", path.name, size_mb)
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
            payload.update(identity_fields(payload))
            log.info("  · OK %s (%.1fs)", path.name, _time.time() - t0)
            return payload
        except UnreadableAudio as e:
            # A stray non-audio file: one line, no traceback -- the trace says nothing.
            log.warning("  · SKIP %s: not a readable audio file (%s)", path, e.reason)
            return {
                "ok": False,
                "filename": path.name,
                "filepath": str(path),
                "error": "not a readable audio file",
            }
        except Exception:
            log.exception("  · FAIL %s (%.1fs)", path.name, _time.time() - t0)
            return {
                "ok": False,
                "filename": path.name,
                "filepath": str(path),
                "error": "analysis failed",
            }

    job = uuid.uuid4().hex

    def final(done, total, cancelled, **extra):
        body = {"done": True, "cancelled": cancelled, "processed": done, "total": total}
        return _json.dumps({**body, **extra}) + "\n"

    def generate():
        # Registered here, not in the route: if the response is never iterated,
        # nothing is left behind. The client learns the id from the first line,
        # which is yielded only after this.
        state = _Job()
        cancel = state.cancel
        with _BATCH_JOBS_LOCK:
            _BATCH_JOBS[job] = state
        ex = ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"batch-{job}")
        done, total = 0, None
        short = 0  # files skipped as under the minimum duration

        def await_go(stage):
            """Wait for POST /batch/<job>/confirm answering ``stage`` (or a cancel).
            The blank keepalive line (NDJSON readers skip it) is what lets a closed
            tab be noticed -- a disconnect only shows up on a write."""
            state.confirm.clear()
            state.stage = stage
            quiet = 0.0
            while not state.confirm.wait(0.25):
                if cancel.is_set():
                    break
                quiet += 0.25
                if quiet >= CONFIRM_KEEPALIVE_S:
                    quiet = 0.0
                    yield "\n"
            state.stage = None

        try:
            # The id goes out FIRST, before the folder walk: a big tree takes a while
            # to walk, and the job must be cancellable for all of it.
            yield _json.dumps({"job": job}) + "\n"
            if whole_drive:
                # A whole drive is asked about twice. First, before any walking:
                # "the whole of F:\ -- continue?" Then, after the walk, the count.
                ask = {"needs_confirm": True, "stage": "drive", "drive": str(folder)}
                yield _json.dumps(ask) + "\n"
                yield from await_go("drive")
                if cancel.is_set():
                    yield final(0, None, True)  # cancelled at the first question: no walk
                    return
            files = []
            for seen, p in enumerate(_iter_folder(folder), 1):
                if seen % WALK_CANCEL_EVERY == 0 and cancel.is_set():
                    break
                if p.is_file() and p.suffix.lower() in AUDIO_EXTS and not _is_sidecar(p):
                    files.append(p)
            if cancel.is_set():
                yield final(0, None, True)  # cancelled while walking: nothing analysed
                return
            files.sort()
            total = len(files)
            # A whole drive always shows its count; any other folder only a big one.
            needs_confirm = bool(files) and (whole_drive or total > BATCH_CONFIRM_OVER)
            head = {"total": total}
            if needs_confirm:
                head.update(needs_confirm=True, stage="count")
            yield _json.dumps(head) + "\n"
            if not files:
                yield final(0, 0, False, error="no audio files found")
                return
            if needs_confirm:
                # Waits for POST /batch/<job>/confirm {"confirm": true, "stage": "count"}.
                yield from await_go("count")
                if cancel.is_set():
                    yield final(0, total, True)  # cancelled at the prompt
                    return
            log.info("batch START: %s  (%d files, %d workers)", folder, total, workers)
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
                    short += bool(result.get("short"))
                    yield _json.dumps(result) + "\n"
                refill()  # after a cancel this adds nothing; running files finish, cached
            # Short files are part of `processed` (each was dealt with) and also
            # counted on their own, only when there were any.
            yield final(done, total, done < total, **({"short": short} if short else {}))
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
            log.info("batch END: %d/%s processed, %d skipped as short", done, total, short)

    return Response(generate(), mimetype="application/x-ndjson")


# How often the folder walk looks at the cancel flag (in directory entries).
WALK_CANCEL_EVERY = 200


# Folders the walk never enters, matched by name (ignoring case) at every level
# below the chosen folder: system and program trees, other people's profiles and
# app data, the recycle bin, caches and source checkouts. From a drive root they
# hold thousands of sound files that aren't music -- and a recycle bin full of
# deleted tracks is exactly what should not come back.
SKIP_DIRS = frozenset(
    name.casefold()
    for name in (
        "$RECYCLE.BIN",
        "System Volume Information",
        "Windows",
        "Program Files",
        "Program Files (x86)",
        "ProgramData",
        "Users",
        "AppData",
        ".git",
        "node_modules",
        "__pycache__",
        "Temp",
    )
)


def _skip_dir(name: str) -> bool:
    n = name.casefold()
    return n in SKIP_DIRS or n.startswith("pytest-of-")


def _iter_folder(folder: Path):
    """Every folder and file under ``folder``, lazily, minus the SKIP_DIRS trees
    (pruned, so never entered). A folder that can't be read is passed over.
    Separate so a test can make it slow."""
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if not _skip_dir(d)]
        base = Path(dirpath)
        for name in dirnames:
            yield base / name  # folders too, so a deep tree still checks cancel
        for name in filenames:
            yield base / name


# More audio files than this and a batch waits for an explicit go-ahead.
BATCH_CONFIRM_OVER = 2000
# While it waits: seconds between keepalive lines.
CONFIRM_KEEPALIVE_S = 5.0


class _Job:
    """A running batch's two flags -- cancel it, or answer the question it is
    waiting on -- and which question that is: "drive" (scan the whole drive?),
    "count" (N files -- start?) or None while it isn't asking."""

    def __init__(self):
        self.cancel = threading.Event()
        self.confirm = threading.Event()
        self.stage = None


# Running /batch jobs: job id -> its _Job. An entry lives exactly as long as that
# job's generator (added at its start, removed in its finally).
_BATCH_JOBS: dict[str, _Job] = {}
_BATCH_JOBS_LOCK = threading.Lock()


def _job(job):
    with _BATCH_JOBS_LOCK:
        return _BATCH_JOBS.get(job)


@bp.post("/batch/<job>/cancel")
def batch_cancel_route(job):
    """Ask a running batch to stop: no new files start; the ones already being
    analysed finish (and are cached), then the stream ends with a cancelled line."""
    state = _job(job)
    if state is None:
        return jsonify({"error": "no such batch"}), 404
    state.cancel.set()
    return jsonify({"ok": True, "job": job})


@bp.post("/batch/<job>/confirm")
def batch_confirm_route(job):
    """Answer the question a batch stopped at: "scan the whole drive?" (stage
    "drive") or "N files -- start?" (stage "count"). ``stage`` names the question
    being answered; one that isn't the question asked now (a second click on the
    first, landing during the second) is refused rather than taken as a yes."""
    body = request.get_json(silent=True) or {}
    if body.get("confirm") is not True:
        return jsonify({"error": 'send {"confirm": true} to start the batch'}), 400
    state = _job(job)
    if state is None:
        return jsonify({"error": "no such batch"}), 404
    stage = body.get("stage")
    if stage is not None and stage != state.stage:
        return jsonify({"error": f"the batch is not asking about {stage!r} now"}), 409
    state.confirm.set()
    return jsonify({"ok": True, "job": job, "stage": state.stage})


def _norm(p):
    return os.path.normcase(os.path.abspath(str(p)))


def _is_drive_root(folder: Path) -> bool:
    """True for the top of a drive (F:\\, or / elsewhere)."""
    here = Path(_norm(folder.resolve()))
    return here.parent == here


def _os_drive() -> str:
    """The drive Windows runs from: the one holding %WINDIR% -- not assumed to be
    C:. (Elsewhere, the filesystem root.)"""
    windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot")
    p = Path(windir) if windir else Path(os.sep)
    for up in (p, *p.parents):
        if _is_drive_root(up):  # the same test the folder itself is put to
            return _norm(up)
    return _norm(p.anchor)


def _refuse_folder(folder: Path):
    """Why ``folder`` must not be batch-scanned, or None if it's fine.

    Walking the Windows drive, a whole user profile or an app-data root finds
    thousands of sound files that aren't music (app sounds, caches, other
    programs' samples) -- how 435 of them once landed in the library. Any other
    drive root is allowed, but asked about twice (batch_route), and the walk skips
    SKIP_DIRS. Compared case-insensitively on Windows."""
    here = _norm(folder.resolve())
    if _is_drive_root(folder) and here == _os_drive():
        return f"{folder} is the Windows drive \u2014 pick a music folder instead."
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    if here in (_norm(home), _norm(Path.home())):
        return f"{folder} is your whole user folder -- choose the music folder inside it"
    # The app-data ROOTS only (and the AppData folder holding both): a folder
    # somewhere inside, like a zip extracted under Temp, is a deliberate choice.
    for app in (os.environ.get("APPDATA"), os.environ.get("LOCALAPPDATA"), home / "AppData"):
        if app and here == _norm(app):
            return f"{folder} is application data, not music -- choose your music folder"
    return None
