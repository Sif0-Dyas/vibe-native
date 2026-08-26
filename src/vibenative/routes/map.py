"""Map routes: the 3-D genre map, misread audit, the index page, and the guide."""

import json
from contextlib import closing
from pathlib import Path

from flask import Response, jsonify, render_template, request

from .. import insight
from ..db import (
    _db_lock,
    db,
)
from ._shared import _artist_of, _dominant_style, _second_style, bp

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

    Prefers the salience read (the energy/confidence/recurrence-weighted identity)
    over the flat scores, matching what ``_dominant_style`` decides from.
    """
    ranked = p.get("salience") or p.get("styles") or []
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


def _keystone_fields(p, mode="dark"):
    """The taxonomy read for one track: family, keystone(s), label and paint.

    Computed per request rather than stored, so editing the taxonomy or the
    palette re-labels the whole map on the next load with no migration. It's
    pure table lookup over the style read that's already in the payload.
    """
    from .. import keystone as K
    from .. import palette as P

    cls = K.classify(p)
    if not cls:
        return {}
    paint = P.track_paint(cls, mode) or {}
    return {
        "family": cls["family"],
        "keystones": cls["keystones"],
        "klabel": cls["label"],
        "kkey": cls["key"],
        "kfusion": cls["fusion"],
        "kshares": cls["shares"],
        "rings": paint.get("rings") or [],
        "kcolor": paint.get("color"),
    }


def _map_node(h, title, filename, payload, filepath="", tags=(), mode="dark"):
    p = payload if isinstance(payload, dict) else json.loads(payload)
    style, score = _dominant_style(p)
    return {
        **_keystone_fields(p, mode),
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


@bp.get("/map")
def map_route():
    import numpy as np

    # Palette steps differ per theme; the client says which it's rendering in.
    mode = "light" if request.args.get("mode") == "light" else "dark"
    with _db_lock, closing(db()) as conn, conn as c:
        rows = c.execute(
            "SELECT hash, title, filename, filepath, payload, embedding FROM tracks"
        ).fetchall()
        tags_by_hash = _tags_by_hash(c)
    nodes, embs, emb_idx = [], [], []
    for h, title, filename, filepath, payload, blob in rows:
        nodes.append(
            _map_node(h, title, filename, payload, filepath, tags_by_hash.get(h, ()), mode)
        )
        if blob is not None:
            embs.append(np.frombuffer(blob, dtype=np.float32))
            emb_idx.append(len(nodes) - 1)
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
    # annotate likely-misread reads so the map can mark them (fresh, whole-library)
    flags = {f["hash"]: f for f in insight.audit()}
    for n in nodes:
        fl = flags.get(n["hash"])
        n["flag"] = bool(fl)
        n["suggest"] = fl["suggested_style"] if fl else None
    return jsonify({"nodes": nodes, "edges": edges})


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
