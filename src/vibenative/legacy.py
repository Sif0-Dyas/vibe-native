"""Support for material inherited from the predecessor app, which ran under WSL.

Two things carry WSL-shaped paths into this one:

* a library database migrated from the old app, whose ``tracks.filepath`` values
  are mount paths like ``/mnt/c/Users/you/Music/x.mp3`` (schema migration 2
  rewrites them in place on first open);
* the developer ``oracle/`` fixtures, whose ``index.json`` records where each
  reference track lived when it was captured.

Someone typing a ``/mnt/...`` path into the app by habit gets the same courtesy.

None of this is needed by a fresh install, and none of it is a licensing matter
-- WSL is a runtime, not a dependency, and nothing here carries anyone else's
code. It lives in its own module so that is obvious at a glance, and so it can
be deleted in one piece once no installation needs it. See docs/PROVENANCE.md.
"""

from __future__ import annotations

import re
from pathlib import PureWindowsPath

_MNT = re.compile(r"^/mnt/([a-zA-Z])/(.*)$")


def wsl_to_windows(path: str) -> str:
    """``/mnt/c/Users/x`` -> ``C:\\Users\\x``. A path that isn't a /mnt mount
    (already-Windows, UNC, relative, ...) is returned unchanged."""
    if not path:
        return path
    m = _MNT.match(path.replace("\\", "/"))
    if not m:
        return path
    drive, rest = m.group(1).upper(), m.group(2)
    return str(PureWindowsPath(f"{drive}:/") / rest) if rest else f"{drive}:\\"
