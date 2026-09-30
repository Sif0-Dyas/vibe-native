"""HTTP routes, split by domain across this package.

One Blueprint (``bp``, defined in ``_shared``) carries every API route; importing
the domain modules below registers their handlers on it via their decorators. The
app factory mounts it under API_PREFIX. The page itself (/) is on ``pages``.
``_artist_of`` / ``_second_style`` are re-exported for the tests that import them.
"""

from . import (  # noqa: F401  -- importing each domain module registers its routes on bp
    analysis,
    genrelab,
    labels,
    library,
    map,
    playlists,
    tags,
    training,
    vibes,
)
from ._shared import _artist_of, _second_style, bp  # noqa: F401  -- re-exported
from .pages import pages

# Where the API lives. The page and /static/* stay at the root.
API_PREFIX = "/api/v1"

__all__ = ["API_PREFIX", "bp", "pages"]
