"""Tag reading via ffprobe (vibenative.metadata).

Tags are decoration -- a missing ffprobe or an odd file must degrade to "no
tags", never raise -- so the contract tested here is as much about what happens
when things are absent as when they are present.

The tests that need real audio build it with ffmpeg and skip when ffmpeg is not
installed, so the suite still runs on a bare checkout.
"""

import shutil
import subprocess  # nosec B404  # builds a tagged test file with ffmpeg, fixed arg list

import pytest

from vibenative import metadata

_FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(not _FFMPEG, reason="ffmpeg not installed")


def _make_track(path, **tags):
    """One second of silence, tagged. Returns the path."""
    args = [
        _FFMPEG,
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=44100:cl=stereo",
        "-t",
        "1",
    ]
    for k, v in tags.items():
        args += ["-metadata", f"{k}={v}"]
    args += [str(path)]
    subprocess.run(args, check=True, capture_output=True)  # nosec B603  # ffmpeg, arg list, no shell
    return path


@needs_ffmpeg
def test_reads_the_fields_the_ui_shows(tmp_path):
    f = _make_track(
        tmp_path / "t.mp3",
        title="At Night",
        artist="Dave Spoon",
        album="Singles",
        genre="Trance",
        date="2008",
        track="3",
        composer="D. S.",
    )
    assert metadata.read_title(f) == "At Night"

    tags = metadata.read_tags(f)
    assert tags["tag"]["title"] == "At Night"
    assert tags["tag"]["artist"] == "Dave Spoon"
    assert tags["tag"]["genre"] == "Trance"
    assert tags["tag"]["tracknumber"] == "3"  # ffprobe calls it "track"
    assert tags["tech"]["sample rate"] == "44100 Hz"
    assert tags["tech"]["channels"] == "2"
    assert tags["tech"]["format"] == "MP3"


@needs_ffmpeg
def test_non_ascii_tags_survive(tmp_path):
    """The reason this beat mutagen on real files: encodings that used to come
    back as mojibake."""
    f = _make_track(tmp_path / "u.mp3", title="Böö ^Bsiide", artist="LöKii")
    assert metadata.read_title(f) == "Böö ^Bsiide"
    assert metadata.read_tags(f)["tag"]["artist"] == "LöKii"


@needs_ffmpeg
def test_an_untagged_file_is_not_an_error(tmp_path):
    f = _make_track(tmp_path / "bare.mp3")
    assert metadata.read_title(f) is None
    tags = metadata.read_tags(f)
    assert tags["tag"] == {}
    assert tags["tech"]["channels"] == "2"  # technical info still arrives


@needs_ffmpeg
def test_absurdly_long_tag_values_are_dropped(tmp_path):
    """DJ software embeds kilobytes of beatgrid state in tags; none of that is a
    title, and it must not reach the UI."""
    f = _make_track(tmp_path / "big.mp3", title="x" * 5000, artist="Real Artist")
    assert metadata.read_title(f) is None
    assert metadata.read_tags(f)["tag"].get("artist") == "Real Artist"


def test_a_missing_file_degrades_to_nothing(tmp_path):
    missing = tmp_path / "nope.mp3"
    assert metadata.read_title(missing) is None
    assert metadata.read_tags(missing) == {"tag": {}, "tech": {}}


def test_no_ffprobe_degrades_to_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(metadata, "find_tool", lambda name: None)
    assert metadata.read_title(tmp_path / "any.mp3") is None
    assert metadata.read_tags(tmp_path / "any.mp3") == {"tag": {}, "tech": {}}


def test_analysis_still_exports_the_tag_readers():
    """The rest of the app imports these from analysis; keep that working."""
    from vibenative import analysis

    # Compared by defining module, not identity: conftest re-imports the package
    # per test, so the two names can be equal functions from different instances.
    assert analysis.read_title.__module__.endswith("metadata")
    assert analysis.read_tags.__module__.endswith("metadata")
    assert callable(analysis.read_title) and callable(analysis.read_tags)
