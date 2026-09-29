"""User-typed names made safe to use as a folder or file name."""


def safe_name(text) -> str:
    """``text`` with every character that isn't a letter or digit (any script),
    a space, ``_`` or ``-`` replaced by ``_``, then stripped. "AC/DC" -> "AC_DC",
    "St. Germain" -> "St_ Germain", "../x" -> "___x"; path separators and dots
    never survive, so the result can't climb out of the folder it's joined to.

    The one rule for a genre's training folder, a playlist's export file name
    and a snapshot's label; callers add their own fallback for an empty result.
    """
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in (text or "")).strip()
