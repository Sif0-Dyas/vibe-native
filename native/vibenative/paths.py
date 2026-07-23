"""WSL <-> native-Windows path translation.

The oracle's index.json (and the legacy genre_v2.db that Phase 4 inherits) store
source paths as WSL mount paths, e.g. ``/mnt/c/Users/mrand/oracle_tracks/x.mp3``.
On native Windows those must become ``C:\\Users\\mrand\\oracle_tracks\\x.mp3``.

Reused by the Phase-4 database migration (addendum §5: translate the /mnt-prefix
filepaths stored in old rows so audio preview + section extraction keep working).
"""

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
