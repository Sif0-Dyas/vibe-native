"""Stand-in engines for fake mode (``Settings.fake``, FAKE_ANALYZER=1): no ffmpeg,
no ONNX models, instant and deterministic results -- for the test suite, CI and
UI work.

The real pipeline (``analysis.analyze``, ``refine_segments``, the waveform
loader) runs unchanged on these; only the engines underneath are swapped, so a
fake analysis produces exactly the payload shape a real one does. What is
faked, and nothing else:

* decode -- synthetic audio, seeded by the file's content hash, so the same
  file always reads the same (any bytes will do: nothing is parsed); the
  waveform loader still reads a real WAV with the stdlib, as fake mode always
  has, so tests can draw a known shape;
* the genre engine -- the real Discogs-400 labels (models/…json, which ships
  with the repo), a seeded embedder, and a classifier that favours one
  primary style with a few switches, as a real track's frames do;
* tempo and key -- seeded, in the real engines' ranges: bpm confidence is a
  mean peak softmax (0..1) as tempo.estimate's is, key strength 0.5-0.95.

:func:`engines` is the one place that chooses: every consumer asks it for the
engines and never looks at the setting itself.
"""

import hashlib
import logging
import random
from types import SimpleNamespace

import numpy as np

from . import frontend_mel
from .settings import current

log = logging.getLogger("vibenative")

# Styles the fake classifier favours (Discogs-400 names, so the taxonomy, the map
# and the colour tables all know them).
_POOL = (
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
)


def engines():
    """The engines analysis runs on: the real ones, or -- in fake mode -- these."""
    return _FAKE if current().fake else _real()


def _real():
    # Imported here, not at the top: onnxruntime (behind onnx_engine) must not be
    # needed just to import the package in fake mode or on CI.
    from . import decode, tempo, tonality

    def genre():
        from . import onnx_engine

        return onnx_engine.get_engine()

    return SimpleNamespace(
        decode_both=decode.decode_both,
        decode_16k_mono=decode.decode_16k_mono,
        decode_mono=decode.decode_mono,
        genre=genre,
        tempo=tempo.estimate,
        key=tonality.estimate,
        startup_check=decode.warn_if_tools_missing,
    )


# --- seeding ---------------------------------------------------------------------
def _rng(*parts) -> random.Random:
    seed = hashlib.sha1(b"".join(parts)).hexdigest()  # nosec B324  # a PRNG seed, not security
    return random.Random(seed)  # nosec B311  # deterministic fake data, not security


def _content_rng(path) -> random.Random:
    from .hashing import file_hash

    return _rng(file_hash(path).encode())


def _audio_rng(audio) -> random.Random:
    """A generator seeded by a signal -- which the fake decode seeded by the file --
    so tempo, key, embeddings and predictions all follow the file too."""
    a = np.asarray(audio, dtype=np.float32)
    return _rng(str(len(a)).encode(), a[:4096].tobytes())


# --- decode ------------------------------------------------------------------------
def _synth(path, sr):
    """A mono float32 signal at ``sr``: 30-90 s of tones under a slow loudness
    envelope (quiet intro, louder body), so energy-weighted reads have
    something to weigh."""
    rng = _content_rng(path)
    seconds = rng.randint(30, 90)
    # Whole-hertz tones and a two-beat bar repeat every second, so one second is
    # synthesised and tiled (computing sin over the whole track was most of a
    # fake analysis's time).
    f1, f2, beat = rng.randint(55, 110), rng.randint(220, 440), 2
    t = np.arange(sr, dtype=np.float32) / sr
    pulse = 0.5 + 0.5 * (np.sin(2 * np.pi * beat * t) > 0)
    second = 0.6 * np.sin(2 * np.pi * f1 * t) * pulse + 0.3 * np.sin(2 * np.pi * f2 * t)
    x = np.tile(second.astype(np.float32), seconds)
    envelope = 0.2 + 0.8 * np.clip(np.linspace(0, 4, x.size, dtype=np.float32), 0, 1)
    return (x * envelope).astype(np.float32)


def _decode_both(path):
    return _synth(path, 16000), _synth(path, 44100)


def _decode_16k_mono(path):
    return _synth(path, 16000)


def _decode_mono(path, sr=None):
    """The waveform loader's decode: a real WAV read with the stdlib (resampling
    is irrelevant for an envelope), peak-normalised."""
    import wave

    with wave.open(str(path), "rb") as wf:
        ch, sw, n = wf.getnchannels(), wf.getsampwidth(), wf.getnframes()
        raw = wf.readframes(n)
    dt = {1: np.int8, 2: np.int16, 4: np.int32}.get(sw, np.int16)
    a = np.frombuffer(raw, dtype=dt).astype(np.float32)
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    m = float(np.abs(a).max()) or 1.0
    return a / m


# --- the genre engine ------------------------------------------------------------
_genre = {}


def _labels():
    """The real 400 labels (taxonomy.classify.discogs_labels: the JSON ships
    with the repo, and beside the models in a packaged build)."""
    from .taxonomy.classify import discogs_labels

    return discogs_labels()


def _n_patches(n_samples, hop_frames):
    """How many patches the real frontend cuts from ``n_samples`` at 16 kHz."""
    n_frames = 1 + n_samples // frontend_mel.HOP
    if n_frames < frontend_mel.PATCH:
        return 0
    return (n_frames - frontend_mel.PATCH) // hop_frames + 1


def _embedder(audio16, hop_frames=frontend_mel.PATCH_HOP_COARSE):
    """(n_patches, 1280) float32: a per-track direction plus per-patch noise, so
    tracks differ and a track's patches resemble each other."""
    n = _n_patches(len(audio16), hop_frames)
    rng = np.random.default_rng(_audio_rng(audio16).getrandbits(64))
    base = rng.standard_normal(1280).astype(np.float32)
    return (base + 0.3 * rng.standard_normal((n, 1280))).astype(np.float32)


def _classifier(embeddings):
    """(n, 400) float32 scores in 0..1: most patches won by one primary style, a
    few by two others, each winner with near-misses under it -- the flicker the
    hysteresis and sibling-merge lenses exist for."""
    emb = np.asarray(embeddings, dtype=np.float32)
    labels = _genre["labels"]
    index = {lab.split("---", 1)[1]: i for i, lab in enumerate(labels)}
    rng = _rng(emb.mean(axis=0).tobytes() if len(emb) else b"empty")
    pool = [s for s in _POOL if s in index]
    rng.shuffle(pool)
    choices = [pool[0]] * 4 + pool[1:3]
    preds = np.full((len(emb), len(labels)), 0.01, dtype=np.float32)
    style = pool[0]
    for row in preds:
        if rng.random() < 0.15:  # a switch, held for a stretch like a real section
            style = rng.choice(choices)
        top = rng.uniform(0.26, 0.55)
        row[index[style]] = top
        for other in rng.sample([p for p in pool if p != style], 3):
            row[index[other]] = rng.uniform(0.02, max(0.03, top - 0.02))
    return preds


def _genre_engine():
    if not _genre:
        _genre.update(labels=_labels(), embedder=_embedder, classifier=_classifier)
    return _genre


# --- tempo and key ---------------------------------------------------------------
def _tempo(audio, sr):
    """(bpm, confidence) as tempo.estimate returns them: confidence a mean peak
    softmax, 0..1."""
    rng = _audio_rng(audio)
    return round(rng.uniform(120, 178), 1), rng.uniform(0.3, 0.95)


def _key(audio, sr):
    """(key, "major"|"minor", strength) as tonality.estimate returns them."""
    from .tonality import KEY_NAMES, MODES

    rng = _audio_rng(audio)
    return rng.choice(KEY_NAMES), rng.choice(MODES), rng.uniform(0.5, 0.95)


def _startup_check():
    log.info("fake mode (FAKE_ANALYZER=1) -- serving fake results (no ffmpeg, no models).")


_FAKE = SimpleNamespace(
    decode_both=_decode_both,
    decode_16k_mono=_decode_16k_mono,
    decode_mono=_decode_mono,
    genre=_genre_engine,
    tempo=_tempo,
    key=_key,
    startup_check=_startup_check,
)
