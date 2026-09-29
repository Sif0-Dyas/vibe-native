"""A track's identity is its audio content, not its name or location."""

import hashlib


def file_hash(path) -> str:
    """Content hash: same song caches regardless of filename or location."""
    h = hashlib.sha1()  # nosec B324  # content cache key (dedupe by audio), not security
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
