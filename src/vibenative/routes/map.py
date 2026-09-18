"""Map routes: the 3-D genre map, misread audit, the index page, and the guide."""

import hashlib
import json
from contextlib import closing
from pathlib import Path

from flask import Response, jsonify, render_template, request

from .. import insight, taxonomy
from ..config import log
from ..db import (
    _db_lock,
    db,
)
from ._shared import _artist_of, _dominant_style, _ranked_read, _second_style, bp

# A runner-up needs at least this share before it's worth offering as a fix.
# Measured against the library: at 3% about 91% of tracks still keep at least one
# candidate (2.5 on average), while the 0-2% tail -- which is model noise, not a
# plausible alternative -- stops being suggested. Offering a 0% read as an answer
# is worse than offering nothing.
CANDIDATE_MIN_SCORE = 0.03


def _override_candidates(p, top_style, limit=5):
    """The track's other weighted reads, strongest first.

    When a track is mislabelled the right answer is usually already in the list,
    one rung down -- a happy-hardcore misread whose runner-up is drum and bass.
    Sending the weights with the node means correcting it is a click instead of
    remembering how to spell it.

    The same ranked read ``_dominant_style`` decides from (``_ranked_read``), so
    the candidates are the runners-up of the read the label actually came from:
    a relabelled track offers the relabel's runners-up, and a genre you removed
    by hand is not offered back as a one-click correction.
    """
    ranked = _ranked_read(p)
    out = []
    for entry in ranked:
        style = (entry or {}).get("style")
        if not style or style == top_style:
            continue
        try:
            score = round(float(entry.get("score") or 0), 4)
        except (TypeError, ValueError):
            continue
        if score < CANDIDATE_MIN_SCORE:
            continue
        out.append({"style": style, "score": score})
        if len(out) >= limit:
            break
    return out


def _tags_by_hash(c):
    """{hash: [tag, ...]} for the whole library in one query.

    Fetched in bulk rather than per node: the map already reads every track, and
    a per-track tag lookup would turn one query into thousands.
    """
    out = {}
    for h, name in c.execute(
        "SELECT tt.hash, t.name FROM track_tags tt JOIN tags t ON t.id = tt.tag_id"
    ):
        out.setdefault(h, []).append(name)
    return out


def _keystone_fields(p, style, mode="dark"):
    """The taxonomy read for one track: family, keystone(s), label and paint.

    Computed per request rather than stored, so editing the taxonomy or the
    palette re-labels the whole map on the next load with no migration. It's
    pure table lookup over the style read that's already in the payload.

    All three tiers travel, not just the widest one. The popup used to have the
    top tier and nothing else, which names the room a track belongs in and never
    the record: every Tech House, Deep House and Bassline track read "House".
    ``ksub`` is the strongest style *within* the primary keystone rather than the
    track's dominant style, so the chips always read as one chain -- Tech House
    under House under House -- instead of a subgenre that hangs off a keystone
    the card isn't showing.

    Every field is always present. A track the taxonomy cannot place -- a
    style with no keystone, or no read at all -- is filed under its dominant
    style as a standalone genre of its own (or "Other" with no read), the way
    a standalone archgenre repeats its name at every tier. The client reads
    fields, not fallback chains: a node with holes in it meant every consumer
    carried its own guess at what should have been there, and they disagreed.
    """
    from .. import keystone as K
    from .. import palette as P

    cls = K.classify(p)
    if not cls:
        k = style or "Other"
        return {
            "family": "Other",
            "keystones": [k],
            "klabel": k,
            "kkey": k,
            "karch": k,
            "ksub": style,
            "kfusion": False,
            "kshares": {k: 1.0} if style else {},
            "rings": [],
            "kcolor": None,
        }
    paint = P.track_paint(cls, mode) or {}
    return {
        "family": cls["family"],
        "keystones": cls["keystones"],
        "klabel": cls["label"],
        "kkey": cls["key"],
        "karch": cls["archgenre"],
        "ksub": (K.dominant_subgenre(cls) or {}).get("style"),
        "kfusion": cls["fusion"],
        "kshares": cls["shares"],
        "rings": paint.get("rings") or [],
        "kcolor": paint.get("color"),
    }


def _map_node(h, title, filename, payload, filepath="", tags=(), mode="dark"):
    p = payload if isinstance(payload, dict) else json.loads(payload)
    style, score = _dominant_style(p)
    return {
        **_keystone_fields(p, style, mode),
        "cands": _override_candidates(p, style),
        "tags": list(tags),
        "hash": h,
        "title": title or (Path(filename).stem if filename else h[:8]),
        "artist": _artist_of(p, title, filename),
        "style": style,
        "score": score,
        "styles": [s.get("style") for s in (p.get("styles") or [])[:3]],
        "mix": _second_style(p, style, score),  # [style2, weight2] for colour blend
        "bpm": p.get("bpm"),
        "key": p.get("key"),
        "scale": p.get("scale"),
        "camelot": p.get("camelot"),
        "duration": p.get("duration"),
        "a": 1 if (filepath and str(filepath).strip()) else 0,  # has a server-side file -> playable
    }


@bp.get("/audit")
def audit_route():
    """Scan the library for likely-misread genres: a low-confidence read whose
    closest sonic neighbours strongly point to a different family. Flags + a
    suggested genre; never changes anything."""
    return jsonify(insight.audit())


# ----------------------------------------------------------------------------
# /map response cache.
#
# Building the map means parsing every track's payload and classifying it, which
# on a 3,300-track library is around seven seconds -- and it ran on every single
# request, so opening the app, or switching to the Map tab, or jumping to the
# playing track, all sat waiting for the same answer to be recomputed. Most of
# that time is spent parsing per-frame genre predictions the map never looks at:
# `frames` alone is ~85% of a stored payload and `frames` + `segments` +
# `waveform` are ~97% of it.
#
# So the built response is kept, keyed by a digest of everything it is derived
# from. Reading the payloads back out of SQLite and hashing them costs about a
# quarter of a second, against seven to rebuild -- and because the key IS the
# input, the cache cannot serve a stale map: change anything the map depends on
# and the digest changes with it. It lives on disk beside the database rather
# than in memory, because the complaint was about opening the app, and a
# process-lifetime cache is empty exactly then.
# ----------------------------------------------------------------------------
CACHE_KEEP = 4  # recent builds to keep on disk (one per mode, plus a little slack)

# Bumped whenever a node or edge grows, loses or changes a field. The app version
# is in the fingerprint too, but it moves per release and the node shape moves per
# commit -- without this, adding a field to _map_node during development serves
# yesterday's map, missing the field, to code that now needs it.
NODE_SCHEMA = 3


def _map_cache_dir():
    from ..db import DB_PATH

    return Path(DB_PATH).parent / "vibe-mapcache"


def _map_fingerprint(rev, mode):
    """A digest of every input the map is built from.

    The library revision (bumped by trigger on every write to the tracks and
    tags tables -- see db._migration_7), the render mode, the taxonomy overlay
    -- which is also where the palette choice and per-genre colours live, so
    one stamp covers all three -- and the app version, so upgrading the code
    cannot serve a map built by the old one.

    Nothing here reads a track: a stamp is a handful of bytes, so asking "is my
    map current" costs the same on a six-thousand-track library as on six.
    """
    from .. import __version__
    from ..db import DB_PATH
    from ..taxonomy import path as taxonomy_path

    h = hashlib.blake2b(digest_size=16)
    h.update(__version__.encode("utf-8"))
    h.update(f"schema{NODE_SCHEMA}".encode())
    h.update(mode.encode("utf-8"))
    h.update(str(DB_PATH).encode("utf-8", "replace"))
    try:
        st = taxonomy_path().stat()
        h.update(f"{st.st_mtime_ns}:{st.st_size}".encode())
    except OSError:
        h.update(b"no-overlay")
    h.update(f"rev{rev}".encode())
    return h.hexdigest()


def _map_stamp(mode):
    """The fingerprint the map would be built from right now."""
    from ..db import library_rev

    with _db_lock, closing(db()) as conn, conn as c:
        rev = library_rev(c)
    return _map_fingerprint(rev, mode)


def _map_cache_read(fp):
    """The stored response for this fingerprint, or None.

    Never raises: a cache that can't be read is a cache miss, not a broken map.
    The expected byte length is part of the filename and is checked here -- the
    rename in the writer means this process cannot leave a half-written entry
    behind, but a file truncated by something else (a full disk, a crash mid-copy,
    a sync client) would otherwise be served as though it were a whole map.
    """
    try:
        for f in _map_cache_dir().glob(f"{fp}-*.json"):
            try:
                expected = int(f.stem.rsplit("-", 1)[1])
            except (IndexError, ValueError):
                continue
            body = f.read_bytes()
            if len(body) == expected:
                return body
            f.unlink(missing_ok=True)      # truncated: not a map, and never will be
    except OSError:
        return None
    return None


def _map_cache_write(fp, body):
    """Store a built response, then drop the older ones. Written under a temp
    name and renamed, so a reader can only ever see the finished file."""
    try:
        d = _map_cache_dir()
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f"{fp}-{len(body)}.json.part"
        tmp.write_bytes(body)
        tmp.replace(d / f"{fp}-{len(body)}.json")
        keep = sorted(d.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
        for stale in keep[CACHE_KEEP:]:
            stale.unlink(missing_ok=True)
    except OSError:
        log.debug("map cache write failed", exc_info=True)


@bp.get("/map")
def map_route():
    # Palette steps differ per theme; the client says which it's rendering in.
    mode = "light" if request.args.get("mode") == "light" else "dark"
    fp = _map_stamp(mode)
    hit = _map_cache_read(fp)
    if hit is not None:
        resp = Response(hit, mimetype="application/json")
        resp.headers["X-Map-Cache"] = "hit"
        return resp
    with _db_lock, closing(db()) as conn, conn as c:
        rows = c.execute(
            "SELECT hash, title, filename, filepath, payload, embedding FROM tracks"
        ).fetchall()
        tags_by_hash = _tags_by_hash(c)
    # One taxonomy overlay for the whole build: every node classified and
    # painted against the same file, and one stat() instead of one per lookup.
    with taxonomy.pinned():
        return _build_map(rows, tags_by_hash, mode, fp)


def _build_map(rows, tags_by_hash, mode, fp):
    import numpy as np

    nodes, embs, emb_idx = [], [], []
    # Every payload is parsed exactly once here and the parsed form is carried
    # to the audit at the end. _map_node takes a dict as happily as a string.
    # Previously the audit re-queried the library and json.loads()-ed the lot a
    # second time, which was 4.3s of an 18s response spent re-deriving data that
    # was already in memory.
    audit_rows = []
    for h, title, filename, filepath, payload, blob in rows:
        parsed = payload if isinstance(payload, dict) else json.loads(payload)
        nodes.append(
            _map_node(h, title, filename, parsed, filepath, tags_by_hash.get(h, ()), mode)
        )
        if blob is not None:
            emb = np.frombuffer(blob, dtype=np.float32)
            embs.append(emb)
            emb_idx.append(len(nodes) - 1)
            audit_rows.append((h, title, parsed, emb))
    edges = []
    m = len(embs)
    if m >= 2:
        M = np.vstack(embs).astype(np.float32)
        # (1) similarity edges from cosine. Only the top-K neighbours per node
        #     are kept, so the cosine matrix is computed in row-blocks and each
        #     row's top-K pulled out, instead of materialising the full m*m
        #     matrix (~400 MB at 10k tracks, recomputed on every map load).
        norm = np.linalg.norm(M, axis=1, keepdims=True)
        norm[norm == 0] = 1.0
        Mn = M / norm
        K = 2  # nearest neighbours per node
        seen = set()
        BLOCK = 512
        kth = min(K, m) - 1
        for i0 in range(0, m, BLOCK):
            block = Mn[i0 : i0 + BLOCK] @ Mn.T  # (rows, m)
            for r in range(block.shape[0]):
                a = i0 + r
                row = block[r]
                row[a] = -1.0  # exclude self (was np.fill_diagonal)
                # top-K via argpartition, then ordered by descending sim so the
                # edge list is identical to the previous argsort()[:K] output.
                cand = np.argpartition(-row, kth)[:K]
                cand = cand[np.argsort(-row[cand])]
                for b in cand:
                    b = int(b)
                    s = float(row[b])
                    if s <= 0:
                        continue
                    key = (min(a, b), max(a, b))
                    if key in seen:
                        continue
                    seen.add(key)
                    edges.append(
                        {
                            "a": nodes[emb_idx[a]]["hash"],
                            "b": nodes[emb_idx[b]]["hash"],
                            "sim": round(s, 3),
                        }
                    )
        # (2) PCA of the embeddings -> a few sonic coordinates per track. The
        #     client picks, per genre region, the 2 components that best spread
        #     THAT region's members, so a big single-genre cluster (e.g. all
        #     dubstep) still fans out by how the tracks actually sound.
        Mc = M - M.mean(axis=0, keepdims=True)
        try:
            _, _, Vt = np.linalg.svd(Mc, full_matrices=False)
            ncomp = int(min(8, Vt.shape[0]))
            proj = Mc @ Vt[:ncomp].T  # (m, ncomp)
            std = proj.std(axis=0, keepdims=True)
            std[std == 0] = 1.0
            proj = proj / std  # standardise each component
            for k, i in enumerate(emb_idx):
                nodes[i]["e"] = [round(float(v), 4) for v in proj[k]]
        except np.linalg.LinAlgError:
            pass
    # Split each credit into the artists it actually names. Done here, after the
    # node loop, because the ampersand rule needs to see the WHOLE library: only
    # the rest of the collection can say whether "Above & Beyond" is one act or
    # two. See vibenative.artists.
    from .. import artists as _artists

    credit_index = _artists.build_index(n["artist"] for n in nodes)
    for n in nodes:
        n["artists"] = _artists.split_credit(n["artist"], credit_index)

    # annotate likely-misread reads so the map can mark them (fresh, whole-library)
    flags = {f["hash"]: f for f in insight.audit(prepared=audit_rows)}
    for n in nodes:
        fl = flags.get(n["hash"])
        n["flag"] = bool(fl)
        n["suggest"] = fl["suggested_style"] if fl else None
    resp = jsonify({"nodes": nodes, "edges": edges, "stamp": fp})
    _map_cache_write(fp, resp.get_data())
    resp.headers["X-Map-Cache"] = "miss"
    return resp


@bp.get("/map/stamp")
def map_stamp_route():
    """The fingerprint /map would be built from, without building it.

    The client keeps the map it has and only rebuilds when the library changes
    underneath it. It cannot see the library, so it watches its own writes and
    assumes the worst -- which is right, but coarse: rating a track, or an
    adjustment the map already applied to the star in place, marks a map stale
    that is in fact still exactly correct, and the next visit spends a rebuild
    proving it.

    So it asks here first. This is the same digest /map keys its cache on, read
    from the library revision counter rather than the rows, so it costs
    microseconds against seven and a half seconds to rebuild -- and it is
    derived from the same inputs, so a match is a real answer and not an
    optimistic one.
    """
    mode = "light" if request.args.get("mode") == "light" else "dark"
    return jsonify({"stamp": _map_stamp(mode)})


@bp.get("/")
def index():
    from .. import __version__

    return render_template("index.html", app_version=__version__)


@bp.get("/guide")
def guide_route():
    """Serve the user guide (docs/USAGE.md) as raw markdown for the in-app tab."""
    # docs/ ships as bundle data in a packaged build (sys._MEIPASS) and lives at the
    # repo root in dev — resource_base() resolves both.
    from ..paths import resource_base

    path = resource_base() / "docs" / "USAGE.md"
    try:
        return Response(path.read_text(encoding="utf-8"), mimetype="text/markdown")
    except OSError:
        return Response(
            "# Guide unavailable\n\nCould not read docs/USAGE.md.", mimetype="text/markdown"
        )
