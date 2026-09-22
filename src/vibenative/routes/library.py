"""Library routes: the track listing, forget, manual genre overrides (whole track
and time-segment), app status, external metadata lookup, and nearest-neighbour
similarity."""

import json
import time
from contextlib import closing
from pathlib import Path

from flask import jsonify, request

from .. import lookup
from ..db import _db_lock, cosine, db, track_embedding
from ._shared import _artist_of, _dominant_style, bp


@bp.post("/forget/<h>")
def forget_route(h):
    """Delete a track's analysis by content hash: removes it from the cache, the
    map, and any vibe/tag membership. Does NOT touch the audio file -- dropping
    the track again will re-analyze it from scratch."""
    with _db_lock, closing(db()) as conn, conn as c:
        deleted = c.execute("DELETE FROM tracks WHERE hash=?", (h,)).rowcount
        c.execute("DELETE FROM track_tags WHERE hash=?", (h,))
        c.execute("DELETE FROM vibe_tracks WHERE hash=?", (h,))
    return jsonify({"ok": True, "deleted": deleted})


@bp.get("/library")
def library_list():
    """A lean listing of EVERY cached track for the Library tab: hash, title, top
    style, BPM, key/scale/camelot, and whether a server-side file exists. Parses each
    stored payload for just those fields (the big segments/waveform arrays are dropped)."""
    with _db_lock, closing(db()) as conn, conn as c:
        rows = c.execute(
            "SELECT hash, filename, title, payload, filepath, created FROM tracks "
            "ORDER BY created DESC"
        ).fetchall()
    out = []
    for h, fn, title, payload, filepath, created in rows:
        p = json.loads(payload) if payload else {}
        styles = p.get("styles") or []
        out.append(
            {
                "hash": h,
                "title": title or fn or h[:10],
                "filename": fn,
                "artist": _artist_of(p, title, fn),
                "style": styles[0].get("style") if styles else None,
                "bpm": p.get("bpm"),
                "key": p.get("key"),
                "scale": p.get("scale"),
                "camelot": p.get("camelot"),
                "duration": p.get("duration"),
                "energy": p.get("energy"),
                "has_file": bool(filepath),
                "created": created,
            }
        )
    return jsonify(out)


@bp.get("/status")
def status_route():
    """App status for the Options tab: version, DB location + track count, ffmpeg
    availability, and the GPU/execution-provider situation. Read-only; never builds
    the ONNX engine just to report."""
    import vibenative

    from ..db import DB_PATH
    from ..decode import find_tool

    with _db_lock, closing(db()) as conn, conn as c:
        n = c.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
    ffmpeg, ffprobe = find_tool("ffmpeg"), find_tool("ffprobe")

    provider, available = None, []
    try:
        import onnxruntime as ort

        available = list(ort.get_available_providers())
        from .. import onnx_engine

        if onnx_engine._engine:  # only if already built (don't trigger a build here)
            provider = onnx_engine._engine.get("_provider")
    except Exception:  # nosec B110  # status is best-effort; onnxruntime absent (FAKE/CI) is fine
        pass

    import os

    return jsonify(
        {
            "version": vibenative.__version__,
            "db_path": str(DB_PATH),
            "log_path": os.environ.get("GENRE_BACKEND_LOG") or None,
            "tracks": n,
            "ffmpeg": bool(ffmpeg),
            "ffmpeg_path": ffmpeg,
            "ffprobe": bool(ffprobe),
            "provider": provider,
            "gpu_available": "DmlExecutionProvider" in available,
            "providers_available": available,
        }
    )


@bp.post("/reveal")
def reveal_route():
    """Open a known app path in Explorer, selecting the file.

    Deliberately NOT a general "open this path" primitive: the caller names
    *which* app path it wants ("db" / "log" / "ffmpeg") and the server resolves
    it. A route that opened whatever path it was handed would be a much broader
    capability than the Options tab needs, reachable from any page the browser
    can be talked into loading.
    """
    import os
    import subprocess  # nosec B404  # fixed arg list, no shell

    from ..db import DB_PATH
    from ..decode import find_tool

    what = ((request.get_json(silent=True) or {}).get("what") or "").strip()
    targets = {
        "db": str(DB_PATH),
        "log": os.environ.get("GENRE_BACKEND_LOG") or "",
        "ffmpeg": find_tool("ffmpeg") or "",
    }
    target = targets.get(what)
    if not target:
        return jsonify({"error": f"unknown or unset target: {what}"}), 400
    p = Path(target)
    if not p.exists():
        return jsonify({"error": f"path does not exist: {p}"}), 404
    try:
        # /select, highlights the file inside its folder rather than opening it
        subprocess.run(  # nosec B603 B607  # explorer with a fixed flag + a server-resolved path
            ["explorer", "/select,", str(p)], timeout=10, check=False
        )
    except (subprocess.SubprocessError, OSError) as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True, "path": str(p)})


@bp.post("/db-path")
def db_path_route():
    """Record a new library-database location in settings.ini.

    Only writes the setting -- it does not move the database or re-point the
    running process. ``DB_PATH`` is resolved once at import and threaded through
    live connections, so switching underneath a running app would leave open
    handles pointing at the old file. The response says a restart is needed, and
    the Options tab says so too.
    """
    import configparser
    import os

    from ..paths import settings_ini

    raw = ((request.get_json(silent=True) or {}).get("path") or "").strip()
    if not raw:
        return jsonify({"error": "path required"}), 400
    target = Path(os.path.expandvars(raw)).expanduser()
    if target.is_dir():
        return jsonify({"error": "that's a folder -- give the full path to a .db file"}), 400
    parent = target.parent
    if not parent.is_dir():
        return jsonify({"error": f"folder does not exist: {parent}"}), 400
    if not os.access(parent, os.W_OK):
        return jsonify({"error": f"folder is not writable: {parent}"}), 400

    ini = settings_ini()
    cp = configparser.ConfigParser(interpolation=None)
    if ini.is_file():
        cp.read(ini, encoding="utf-8")
    if not cp.has_section("vibenative"):
        cp.add_section("vibenative")
    cp.set("vibenative", "db_path", str(target))
    try:
        with open(ini, "w", encoding="utf-8") as fh:
            cp.write(fh)
    except OSError as e:
        return jsonify({"error": f"could not write {ini}: {e}"}), 500
    return jsonify(
        {
            "ok": True,
            "path": str(target),
            "settings_ini": str(ini),
            "exists": target.is_file(),
            "restart_required": True,
            "note": "GENRE_DB, if set, still overrides this.",
        }
    )


@bp.post("/override/<h>")
def override_route(h):
    """Manually set a track's genre. Persists into the cached analysis (so the
    map, list and audit reflect it and it survives a reload), and files the audio
    under ~/genre_training/<genre>/ when a server-side file is available."""
    import shutil

    data = request.get_json(silent=True) or {}
    genre = (data.get("genre") or "").strip()
    if not genre:
        return jsonify({"error": "genre required"}), 400
    with _db_lock, closing(db()) as conn, conn as c:
        row = c.execute("SELECT filepath, payload FROM tracks WHERE hash=?", (h,)).fetchone()
        if not row:
            return jsonify({"error": "track not in database"}), 404
        filepath, payload = row
        p = json.loads(payload)
        p["override"] = genre
        c.execute("UPDATE tracks SET payload=? WHERE hash=?", (json.dumps(p), h))
    # INVARIANT: the training-copy file I/O below runs AFTER the _db_lock block
    # closes -- `filepath` was read inside the lock, but shutil.copy2 must not be
    # moved back inside it (never hold the DB lock across disk I/O).
    trained = False
    if filepath:
        safe = "".join(ch if ch.isalnum() or ch in " _-" else "_" for ch in genre).strip()
        src = Path(filepath)
        if safe and src.is_file():
            dest_dir = Path.home() / "genre_training" / safe
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / src.name
            if not dest.exists():
                shutil.copy2(src, dest)
            trained = True
    return jsonify({"ok": True, "genre": genre, "trained": trained})


def _remove_segment_clip(h, genre, start, end):
    """Best-effort delete of the training clip an override produced. Reconstructs
    the exact path _extract_segment wrote (same genre folder + <hash>_<s>-<e><ext>,
    ext from the track's source file). Returns True if a file was removed."""
    with _db_lock, closing(db()) as conn, conn as c:
        row = c.execute("SELECT filepath FROM tracks WHERE hash=?", (h,)).fetchone()
    filepath = row[0] if row else None
    safe = "".join(ch if ch.isalnum() or ch in " _-" else "_" for ch in genre).strip()
    if not safe:
        return False
    ext = (Path(filepath).suffix.lower() if filepath else "") or ".wav"
    dest = Path.home() / "genre_training" / safe / f"{h}_{int(round(start))}-{int(round(end))}{ext}"
    try:
        if dest.is_file():
            dest.unlink()
            return True
    except OSError:
        pass
    return False


def _extract_segment(src, safe_genre, h, start, end):
    """Extract [start, end] of ``src`` into ~/genre_training/<safe_genre>/ with
    ffmpeg. Tries a stream-copy first (fast, lossless, container permitting) and
    falls back to a re-encode. Returns (dest_path | None, error | None); a missing
    ffmpeg is a soft failure (the override is still recorded, just not clipped)."""
    import subprocess  # nosec B404  # only used to run ffmpeg with a fixed arg list, never a shell

    from ..decode import NO_WINDOW, find_tool

    ffmpeg = find_tool("ffmpeg")  # PATH or the WinGet Links dir (Windows winget install)
    if not ffmpeg:
        return None, "ffmpeg not found on PATH -- override recorded, clip not extracted"
    dest_dir = Path.home() / "genre_training" / safe_genre
    dest_dir.mkdir(parents=True, exist_ok=True)
    ext = src.suffix.lower() or ".wav"
    dest = dest_dir / f"{h}_{int(round(start))}-{int(round(end))}{ext}"
    # -ss before -i = fast input seek; -t = duration. Build both variants.
    base = [
        ffmpeg,
        "-nostdin",
        "-y",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(src),
        "-t",
        f"{end - start:.3f}",
    ]

    def _run(cmd):
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=300, creationflags=NO_WINDOW)  # nosec B603  # ffmpeg from shutil.which, args are a list (no shell), src is a DB-recorded path
            if r.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
                return True, None
            return False, (r.stderr.decode(errors="replace")[-300:].strip() or "ffmpeg failed")
        except (subprocess.SubprocessError, OSError) as e:
            return False, str(e)

    ok, err = _run(base + ["-map", "0:a", "-c", "copy", str(dest)])  # (1) stream-copy
    if ok:
        return str(dest), None
    ok, err = _run(base + ["-vn", str(dest)])  # (2) re-encode fallback
    return (str(dest), None) if ok else (None, err)


@bp.post("/override_segment")
def override_segment_route():
    """Label a time range of a track a genre. Validates 0 <= start < end <=
    duration, records the span, and extracts that range into the genre's training
    folder. Needs a server-side source file: a browser-dropped track (no saved
    path) gets a clear message rather than a silent re-upload."""
    data = request.get_json(silent=True) or {}
    h = (data.get("hash") or "").strip()
    genre = (data.get("genre") or "").strip()
    if not h or not genre:
        return jsonify({"error": "hash and genre required"}), 400
    try:
        start = float(data.get("start"))
        end = float(data.get("end"))
    except (TypeError, ValueError):
        return jsonify({"error": "start and end must be numbers"}), 400

    with _db_lock, closing(db()) as conn, conn as c:
        row = c.execute("SELECT filepath, payload FROM tracks WHERE hash=?", (h,)).fetchone()
    if not row:
        return jsonify({"error": "track not in database"}), 404
    filepath, payload = row
    duration = (json.loads(payload) if payload else {}).get("duration")

    # validate the range: 0 <= start < end <= duration (small tolerance on the end)
    if not (start >= 0 and end > start):
        return jsonify({"error": "need 0 <= start < end"}), 400
    if duration and end > duration + 0.5:
        return jsonify(
            {"error": f"end {end:.1f}s is past the track duration ({duration:.1f}s)"}
        ), 400

    # extraction needs the real file -- dropped tracks have none; say so plainly.
    if not filepath:
        return jsonify(
            {
                "error": "section overrides need a server-side file. This track was "
                "dropped in the browser and has no saved path -- add it from a folder "
                "or batch scan first, then override sections of it."
            }
        ), 400
    src = Path(filepath)
    if not src.is_file():
        return jsonify({"error": "the source file for this track no longer exists on disk"}), 404

    with _db_lock, closing(db()) as conn, conn as c:
        cur = c.execute(
            "INSERT INTO segment_overrides(hash, start_s, end_s, genre, created) VALUES(?,?,?,?,?)",
            (h, start, end, genre, time.time()),
        )
        new_id = cur.lastrowid
    # ffmpeg extraction stays OUTSIDE the DB lock (subprocess + disk I/O)
    safe = "".join(ch if ch.isalnum() or ch in " _-" else "_" for ch in genre).strip()
    clip, err = _extract_segment(src, safe, h, start, end) if safe else (None, "invalid genre name")
    return jsonify(
        {
            "ok": True,
            "id": new_id,
            "hash": h,
            "genre": genre,
            "start": start,
            "end": end,
            "extracted": bool(clip),
            "extract_error": err,
        }
    )


@bp.post("/override_segment/delete")
def override_segment_delete():
    """Remove a segment override by id: drops the DB record AND deletes the training
    clip it produced (undoing the override should not leave the clip behind to keep
    training the head). The client gates this behind an explicit confirm."""
    data = request.get_json(silent=True) or {}
    oid = data.get("id")
    if oid is None:
        return jsonify({"error": "id required"}), 400
    try:
        oid = int(oid)
    except (TypeError, ValueError):
        return jsonify({"error": "id must be an integer"}), 400
    with _db_lock, closing(db()) as conn, conn as c:
        row = c.execute(
            "SELECT hash, start_s, end_s, genre FROM segment_overrides WHERE rowid=?", (oid,)
        ).fetchone()
        if not row:
            return jsonify({"error": "override not found"}), 404
        c.execute("DELETE FROM segment_overrides WHERE rowid=?", (oid,))
    h, start, end, genre = row
    # disk I/O stays outside the DB lock
    clip_removed = _remove_segment_clip(h, genre, start, end)
    return jsonify({"ok": True, "deleted": 1, "clip_removed": clip_removed})


@bp.get("/lookup/<h>")
def lookup_route(h):
    """Look up external metadata (genres/styles/tags) for a track by artist/title
    across Discogs, MusicBrainz, and Last.fm. Only sources with a configured key are
    queried (MusicBrainz needs none); each source degrades independently (a timeout
    or failure is reported for that source, never fatal). Successful responses are
    cached PERMANENTLY per (hash, source) so a repeat click never re-queries."""
    with _db_lock, closing(db()) as conn, conn as c:
        row = c.execute("SELECT title, filename, payload FROM tracks WHERE hash=?", (h,)).fetchone()
        if not row:
            return jsonify({"error": "track not in database"}), 404
        cached = {
            r[0]: json.loads(r[1])
            for r in c.execute("SELECT source, response_json FROM lookup_cache WHERE hash=?", (h,))
        }
    title, filename, payload = row
    artist, track_title, remix = lookup.parse_track(
        json.loads(payload) if payload else {}, title, filename
    )

    fetchers = {
        "discogs": (lookup.fetch_discogs, lookup.parse_discogs),
        "musicbrainz": (lookup.fetch_musicbrainz, lookup.parse_musicbrainz),
        "lastfm": (lookup.fetch_lastfm, lookup.parse_lastfm),
    }
    conf = lookup.configured()
    results, errors = {}, {}
    for src, (fetch, parse) in fetchers.items():
        if src in cached:  # permanent cache -> never re-query
            results[src] = cached[src]
            continue
        if not conf.get(src):
            errors[src] = "not configured"
            continue
        if not track_title:
            errors[src] = "no title to search"
            continue
        raw, err = fetch(artist, track_title)  # network stays OUTSIDE the DB lock
        if err:
            errors[src] = err
            continue
        parsed = parse(raw)
        results[src] = parsed
        with _db_lock, closing(db()) as conn, conn as c:  # cache the hit permanently
            c.execute(
                "INSERT OR REPLACE INTO lookup_cache(hash, source, response_json, fetched) "
                "VALUES(?,?,?,?)",
                (h, src, json.dumps(parsed), time.time()),
            )
    return jsonify(
        {
            "query": {"artist": artist, "title": track_title, "remix": remix},
            "results": results,
            "errors": errors,
        }
    )


@bp.get("/similar/<h>")
def similar_route(h):
    """Top-k nearest tracks to <h> by embedding cosine (for the map popup)."""
    import numpy as np

    k = max(1, min(int(request.args.get("k", 8)), 40))
    target = track_embedding(h)
    if target is None:
        return jsonify({"error": "track not in database"}), 404
    with _db_lock, closing(db()) as conn, conn as c:
        rows = c.execute(
            "SELECT hash, title, filename, filepath, payload, embedding FROM tracks "
            "WHERE embedding IS NOT NULL AND hash != ?",
            (h,),
        ).fetchall()
    out = []
    for hh, title, filename, filepath, payload, blob in rows:
        emb = np.frombuffer(blob, dtype=np.float32)
        p = json.loads(payload)
        style, _ = _dominant_style(p)
        out.append(
            {
                "hash": hh,
                "title": title or (Path(filename).stem if filename else hh[:8]),
                "artist": _artist_of(p, title, filename),
                "style": style,
                "bpm": p.get("bpm"),
                "camelot": p.get("camelot"),
                "sim": round(cosine(target, emb), 4),
                "a": 1 if (filepath and str(filepath).strip()) else 0,
            }
        )
    out.sort(key=lambda x: -x["sim"])
    return jsonify(out[:k])


@bp.get("/filepaths/audit")
def filepaths_audit_route():
    """How many analysed tracks have a usable file path, and which don't."""
    from .. import filepaths

    check = request.args.get("check_exists", "1") != "0"
    return jsonify(filepaths.audit(check_exists=check))


@bp.post("/filepaths/repair")
def filepaths_repair_route():
    """Reconnect analysed tracks to their audio by hashing a folder.

    Defaults to a dry run: POST {"folder": "...", "apply": true} to write.
    Never re-analyses and never changes a genre -- it only fills in a missing or
    broken ``filepath`` for a track whose analysis already exists.
    """
    from .. import filepaths
    from ..paths import wsl_to_windows

    d = request.get_json(silent=True) or {}
    folder = str(d.get("folder") or "").strip()
    if not folder:
        return jsonify({"error": "folder required"}), 400
    try:
        out = filepaths.repair(wsl_to_windows(folder), dry_run=not bool(d.get("apply")))
    except NotADirectoryError:
        return jsonify({"error": f"not a directory: {folder}"}), 400
    except OSError as e:
        return jsonify({"error": str(e)}), 500
    return jsonify(out)


@bp.post("/filepaths/count")
def filepaths_count_route():
    """How many audio files a folder holds, and roughly how long hashing takes.

    A fast directory walk, no hashing -- so the UI can warn before a whole-drive
    scan rather than appearing to hang for minutes.
    """
    from .. import filepaths
    from ..paths import wsl_to_windows

    folder = str((request.get_json(silent=True) or {}).get("folder") or "").strip()
    if not folder:
        return jsonify({"error": "folder required"}), 400
    try:
        return jsonify(filepaths.count_files(wsl_to_windows(folder)))
    except NotADirectoryError:
        return jsonify({"error": f"not a directory: {folder}"}), 400


@bp.get("/weights/<h>")
def weights_get(h):
    """A track's manual weight adjustments and the blend they produce."""
    from .. import weights as W

    with _db_lock, closing(db()) as conn, conn as c:
        row = c.execute("SELECT payload FROM tracks WHERE hash=?", (h,)).fetchone()
    if not row:
        return jsonify({"error": "track not found"}), 404
    try:
        p = json.loads(row[0]) if row[0] else {}
    except ValueError:
        p = {}
    base = W.base_read(p)
    return jsonify(
        {
            "hash": h,
            "steps": p.get("weights") or {},
            # Unfiltered on purpose: `base` is what the model said, so the UI can
            # name a removed genre in order to offer it back. Hiding the dropped
            # ones here would make a removal the one edit you can't undo.
            "base": base[:8],
            "drops": _effective_drops(p),
            "adjusted": W.read_with_steps(p) or base[:8],
            "max_step": W.MAX_STEP,
            "words": {str(k): v for k, v in W.STEP_WORDS.items()},
        }
    )


def _effective_drops(p):
    """The stored drops that take effect against the track's current read.

    Stored verbatim, reported filtered: the drop that would empty the read is
    refused by ``weights.apply`` at read time, and which one that is can change
    -- a relabel can make a drop that was harmless when it was made the one
    that empties the read. Filtering when reporting rather than when storing
    means the panel and the star agree whenever they are looked at, not only
    on the day the drop was made.
    """
    from .. import weights as W

    return W.surviving_drops(W.base_read(p), p.get("drops"))


@bp.post("/weights/<h>")
def weights_put(h):
    """Set a track's per-genre adjustments.

    Body: ``{"steps": {"House": 3, "Tech Trance": -3}, "drops": ["Hands Up"]}``.
    A step of 0 is removed rather than stored, so "no opinion" and "explicitly
    neutral" stay the same thing and the payload doesn't accumulate dead entries.

    Either key may be omitted, and an omitted key is left as it was -- removing a
    genre must not silently discard the steps you set on the others, and vice
    versa. Send ``{}`` for a key to clear that one.

    Only the adjustments are written; the analysed read underneath is untouched,
    so clearing them restores exactly what the model said.
    """
    from .. import weights as W

    data = request.get_json(silent=True) or {}
    raw, raw_drops = data.get("steps"), data.get("drops")
    if raw is None and raw_drops is None:
        return jsonify({"error": "steps object or drops list required"}), 400
    if raw is not None and not isinstance(raw, dict):
        return jsonify({"error": "steps object required"}), 400
    if raw_drops is not None and not isinstance(raw_drops, list):
        return jsonify({"error": "drops list required"}), 400
    steps = {}
    for style, v in (raw or {}).items():
        s = W.clamp_step(v)
        if s and str(style).strip():
            steps[str(style).strip()] = s
    drops = W.clean_drops(raw_drops)

    with _db_lock, closing(db()) as conn, conn as c:
        row = c.execute("SELECT payload FROM tracks WHERE hash=?", (h,)).fetchone()
        if not row:
            return jsonify({"error": "track not found"}), 404
        try:
            p = json.loads(row[0]) if row[0] else {}
        except ValueError:
            p = {}
        if raw is not None:
            if steps:
                p["weights"] = steps
            else:
                p.pop("weights", None)
        if raw_drops is not None:
            if drops:
                p["drops"] = drops
                # A genre can't be both raised and removed; the removal is the
                # later, more explicit statement, so it takes the name and the
                # step goes with it -- including one stored earlier. apply()
                # ignores it either way, but a stored "very House" on a removed
                # House would come back the moment House was restored: a
                # judgement made before deciding it wasn't there at all.
                kept = {k: v for k, v in (p.get("weights") or {}).items() if k not in drops}
                if kept:
                    p["weights"] = kept
                else:
                    p.pop("weights", None)
            else:
                p.pop("drops", None)
        c.execute("UPDATE tracks SET payload=? WHERE hash=?", (json.dumps(p), h))
    return jsonify(
        {
            "hash": h,
            "steps": p.get("weights") or {},
            "drops": _effective_drops(p),
            "adjusted": W.read_with_steps(p) or [],
        }
    )
