"""Third-party notices, assembled for the Options tab.

Several things this app ships carry attribution obligations: ffmpeg is LGPL, the
genre reference is built partly from CC BY-SA sources, the analysis models are
MTG's. Those obligations are owed to whoever *runs the product*, which means the
attribution has to be somewhere a user can read it -- not only in the repo's
README, which a customer never sees, and not only inside a bundled JSON file.

What is listed here is what actually ships. `docs/PROVENANCE.md` is the fuller
engineering inventory, including the parts that are still unresolved; this module
is deliberately the short, user-facing version of the same facts.

Entries whose files are absent from a given build are dropped, so the panel never
credits something that is not there.
"""

from __future__ import annotations

import json
from pathlib import Path

from .paths import models_dir

_DATA = Path(__file__).resolve().parent / "data"

# Static entries: (name, what it is, licence, url). Assembled into dicts below.
_STATIC = [
    (
        "FFmpeg",
        "Audio decoding and tag reading. Shipped as a separate program and invoked "
        "as one; not linked into this application.",
        "LGPL-2.1-or-later",
        "https://ffmpeg.org",
    ),
    (
        "ONNX Runtime",
        "Runs the analysis models, on the GPU where DirectML is available.",
        "MIT",
        "https://onnxruntime.ai",
    ),
    (
        "NumPy, Flask, pywebview",
        "Numerics, the local web server, and the desktop window.",
        "BSD-3-Clause",
        "https://numpy.org",
    ),
]

_MODELS = (
    "Discogs-EffNet and Discogs-400 (genre), TempoCNN / DeepTemp (tempo)",
    "The pretrained analysis models, by the Music Technology Group, Universitat "
    "Pompeu Fabra. Alonso-Jimenez et al., ISMIR 2022; Schreiber and Muller, SMC 2019.",
    "CC BY-NC-ND 4.0",
    "https://essentia.upf.edu/models.html",
)

_KEY_MODEL = (
    "Key detection model",
    "Trained for this app on the GiantSteps key dataset (Knees et al., ISMIR 2015) "
    "and the Beatport EDM Key dataset (Faraldo, UPF 2017, CC BY-SA 4.0).",
    "See docs/KEY_SPEC.md",
    "https://zenodo.org/records/1101082",
)


def _entry(name, what, licence, url):
    return {"name": name, "what": what, "licence": licence, "url": url}


def _genre_reference() -> dict | None:
    """The crawled genre reference credits its own sources in a `licences` block;
    read them from the shipped file rather than restating them here, so the credit
    can never drift from the data it describes."""
    path = _DATA / "genres_electronic.json"  # works frozen and in dev alike
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    licences = doc.get("licences") or doc.get("licenses") or {}
    if not licences:
        return None
    return _entry(
        "Electronic genre reference",
        "Genre names, aliases, descriptions and hierarchy, aggregated from: "
        + "; ".join(f"{k} — {v}" for k, v in licences.items()),
        "CC0-1.0 and CC BY-SA (per source, above)",
        "https://www.wikidata.org",
    )


def all_notices() -> list[dict]:
    """Everything this build actually ships that is owed a credit."""
    out = [_entry(*e) for e in _STATIC]

    if any(models_dir().glob("*.onnx")):
        out.append(_entry(*_MODELS))
    if (_DATA / "key_profiles.json").is_file():
        out.append(_entry(*_KEY_MODEL))

    genres = _genre_reference()
    if genres:
        out.append(genres)
    return out
