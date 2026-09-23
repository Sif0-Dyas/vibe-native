"""Track tags and technical info, read with ffprobe.

This used to use mutagen, which is GPL-2.0 and was *imported* into the process --
unlike ffmpeg, which is invoked as a separate program and so stays mere
aggregation. The spec listed it in hiddenimports, so it shipped inside the exe:
the classic copyleft problem for a product meant to be sold. See
docs/PROVENANCE.md.

ffprobe is already shipped beside the exe for decoding (LGPL, separate process),
reads every container the decoder does, and is what the app already trusts for
sample rate and channel count.

Tag names differ by container -- ID3 arrives lower-case (`album_artist`), Vorbis
comments upper-case (`ALBUMARTIST`) -- so lookups here are case-insensitive over
a list of aliases, and the keys this returns are the ones the UI has always used.
"""

from __future__ import annotations

import json
import subprocess  # nosec B404  # ffprobe via decode._tool: fixed arg list, no shell
from pathlib import Path

from .decode import NO_WINDOW, find_tool

# Output field -> the tag names containers actually use for it, best first.
_FIELDS: dict[str, tuple[str, ...]] = {
    "title": ("title",),
    "artist": ("artist",),
    "album": ("album",),
    "albumartist": ("album_artist", "albumartist"),
    "genre": ("genre",),
    "date": ("date", "year", "originalyear"),
    "tracknumber": ("track", "tracknumber"),
    "discnumber": ("disc", "discnumber"),
    "composer": ("composer",),
    "bpm": ("bpm", "tbpm"),
}

# Some writers embed kilobytes of their own state in a tag (Traktor's beatgrid,
# cover art as text). Nothing that long is a title; cap what we keep.
_MAX_VALUE = 300


def _probe_json(path: Path | str) -> dict:
    """ffprobe's view of a file: format (tags, bitrate, duration) + first audio
    stream. Returns {} when ffprobe is missing or the file is unreadable --
    metadata is decoration, never a reason to fail an analysis."""
    exe = find_tool("ffprobe")
    if not exe:
        return {}
    try:
        out = subprocess.run(  # nosec B603  # ffprobe from find_tool(); arg list, no shell
            [
                exe, "-v", "error",
                "-select_streams", "a:0",
                "-show_entries",
                "format=format_name,bit_rate:format_tags:stream=sample_rate,channels,codec_name",
                "-of", "json",
                str(path),
            ],
            capture_output=True, check=True, creationflags=NO_WINDOW,
            # ffprobe emits UTF-8 JSON. text=True alone would decode it with the
            # locale encoding (cp1252 on a typical Windows box), turning every
            # accented tag into mojibake -- "Boo" written as UTF-8 and read as
            # cp1252 comes back as "BÃ¶Ã¶".
            encoding="utf-8", errors="replace",
        ).stdout
        return json.loads(out) or {}
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}


def _lookup(tags: dict, names: tuple[str, ...]) -> str | None:
    """First non-empty tag matching any alias, compared case-insensitively."""
    lower = {str(k).lower(): v for k, v in tags.items()}
    for n in names:
        v = lower.get(n)
        if v is None:
            continue
        s = str(v).strip()
        if s and len(s) <= _MAX_VALUE:
            return s
    return None


def read_title(path: Path) -> str | None:
    """Title from the file's tags, or None."""
    tags = _probe_json(path).get("format", {}).get("tags", {}) or {}
    return _lookup(tags, _FIELDS["title"])


def read_tags(path: Path) -> dict:
    """{"tag": {...}, "tech": {...}} -- the common tag fields and the technical
    info behind the details box. Keys are the ones the UI renders, in its order."""
    probe = _probe_json(path)
    fmt = probe.get("format", {}) or {}
    streams = probe.get("streams") or [{}]
    stream = streams[0] if streams else {}
    raw = fmt.get("tags", {}) or {}

    tag = {}
    for field, names in _FIELDS.items():
        v = _lookup(raw, names)
        if v:
            tag[field] = v

    tech = {}
    try:
        br = int(fmt.get("bit_rate") or 0)
        if br:
            tech["bitrate"] = f"{round(br / 1000)} kbps"
    except (TypeError, ValueError):
        pass
    if stream.get("sample_rate"):
        tech["sample rate"] = f"{stream['sample_rate']} Hz"
    if stream.get("channels"):
        tech["channels"] = str(stream["channels"])
    container = str(fmt.get("format_name") or "").split(",")[0]
    codec = str(stream.get("codec_name") or "")
    label = container or codec
    if label:
        # "mp3" / "flac" read better upper-cased, the way mutagen's class names did;
        # longer container names ("matroska") are left alone.
        tech["format"] = label.upper() if len(label) <= 4 else label
    return {"tag": tag, "tech": tech}
