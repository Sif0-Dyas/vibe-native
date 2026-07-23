#!/usr/bin/env python3
"""Dump golden-reference analysis data from the EXISTING WSL Vibe_Identify.

Run this in WSL, inside the app's venv, from anywhere:

    python tools/make_oracle.py /mnt/c/Users/you/oracle_tracks -o ./oracle

It imports the installed/checked-out `vibedentify` package directly (point
PYTHONPATH at the Vibe_Identify checkout if it isn't installed), analyzes
every audio file in the folder, and writes:

    oracle/<hash>.npz   embeddings (n_frames x 1280 float32), emb_mean (1280)
    oracle/index.json   hash -> {file, title, bpm, bpm_confidence, key, scale,
                                 camelot, key_strength, duration, styles}

This folder is the acceptance target for the native build: its mel frontend
is correct when cosine(native_embeddings, oracle_embeddings) > 0.999.

Pick ~50 diverse tracks: your core genres, plus edge cases (quiet intros,
vinyl rips, mono files, several formats/bitrates, one very short track).
"""

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("tracks_dir", help="folder of audio files to reference")
    ap.add_argument("-o", "--out", default="oracle", help="output folder")
    ap.add_argument(
        "--repo",
        default=None,
        help="path to a Vibe_Identify checkout (if vibedentify isn't installed)",
    )
    args = ap.parse_args()

    if args.repo:
        sys.path.insert(0, str(Path(args.repo).expanduser().resolve()))
    try:
        import numpy as np
        from essentia.standard import MonoLoader

        from vibedentify.analysis import analyze, get_engine
        from vibedentify.config import AUDIO_EXTS
        from vibedentify.db import file_hash
    except ImportError as e:
        print(
            f"import failed ({e}).\nRun inside the WSL venv; if the package "
            "isn't installed, pass --repo /path/to/Vibe_Identify",
            file=sys.stderr,
        )
        return 1

    tracks = Path(args.tracks_dir).expanduser()
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)

    files = sorted(
        p for p in tracks.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXTS
    )
    if not files:
        print(f"no audio under {tracks}", file=sys.stderr)
        return 1

    index = {}
    for i, f in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {f.name}")
        h = file_hash(f)

        # raw embeddings straight from the engine (same path analyze() uses)
        audio16 = MonoLoader(filename=str(f), sampleRate=16000, resampleQuality=4)()
        embs = np.asarray(get_engine()["embedder"](audio16), dtype=np.float32)

        # full analysis for the scalar references
        result = analyze(f)

        np.savez(
            out / f"{h}.npz",
            embeddings=embs,
            emb_mean=np.asarray(result.get("emb_mean"), dtype=np.float32),
        )
        index[h] = {
            "file": str(f),
            "n_frames": int(embs.shape[0]),
            "bpm": result.get("bpm"),
            "bpm_confidence": result.get("bpm_confidence"),
            "key": result.get("key"),
            "scale": result.get("scale"),
            "camelot": result.get("camelot"),
            "key_strength": result.get("key_strength"),
            "duration": result.get("duration"),
            "styles": result.get("styles", [])[:5],
        }

    (out / "index.json").write_text(json.dumps(index, indent=2))
    print(f"\noracle written -> {out}  ({len(index)} tracks)")
    print(
        "copy this folder (and ~/essentia_models/*.pb+.json) into the "
        "vibe-native repo before Session A"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
