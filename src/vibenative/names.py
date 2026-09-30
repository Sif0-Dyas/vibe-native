"""User-typed names made safe to use as a folder or file name."""


def safe_name(text) -> str:
    """``text`` with every character that isn't a letter or digit (any script),
    a space, ``_`` or ``-`` replaced by ``_``, then stripped. "AC/DC" -> "AC_DC",
    "St. Germain" -> "St_ Germain", "../x" -> "___x"; path separators and dots
    never survive, so the result can't climb out of the folder it's joined to.

    The one character rule for a genre's training folder (through
    genre_folder, which also refuses a name with no letter or digit), a
    playlist's export file name and a snapshot's label; callers add their own
    fallback for an empty result.
    """
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in (text or "")).strip()


# What a route answers (400) for a genre that genre_folder() refuses.
GENRE_NEEDS_ALNUM = "genre name needs at least one letter or digit"


def genre_folder(genre):
    """The folder name a genre maps to, or None if the name isn't usable.

    safe_name, plus one rejection: a name with no letter or digit at all.
    "///" sanitises to "___", which would silently create a junk folder of
    training audio -- and let a reset claim it had cleared something real.
    Every genre -> training-folder route refuses such a name with
    GENRE_NEEDS_ALNUM before it copies a file or writes a label.
    """
    raw = genre or ""
    if not any(c.isalnum() for c in raw):
        return None
    return safe_name(raw) or None
