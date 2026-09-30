"""The package logger, the audio extensions, and the .env parser.

Settings read from the environment live in settings.py; nothing here reads the
environment at import. This module has no project-internal imports -- it is the
base of the graph.
"""

import logging
import os
from pathlib import Path

log = logging.getLogger("vibenative")


def _apply_dotenv(path, env=None):
    """Load KEY=VALUE pairs from ``path`` into ``env`` (default os.environ) and
    return the names it set. Real environment variables always win -- only keys
    ABSENT from ``env`` are set. Tolerant parsing: blank lines and ``#`` comments
    are skipped, an optional ``export`` prefix and surrounding quotes on the value
    are accepted, malformed lines (no ``=`` / empty key) are ignored silently. A
    missing file is a silent no-op."""
    env = os.environ if env is None else env
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return {}
    applied = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, sep, val = line.partition("=")
        key = key.strip()
        if not sep or not key:  # malformed -> skip silently
            continue
        if key not in env:  # real environment always wins
            env[key] = val.strip().strip("\"'")
            applied[key] = env[key]
    return applied


AUDIO_EXTS = {
    ".mp3",
    ".flac",
    ".m4a",
    ".mp4",
    ".aac",
    ".alac",
    ".ogg",
    ".oga",
    ".opus",
    ".wav",
    ".aif",
    ".aiff",
    ".aifc",
    ".wma",
    ".wv",
    ".ape",
    ".mpc",
    ".dsf",
}
