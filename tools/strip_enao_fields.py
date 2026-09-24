#!/usr/bin/env python3
"""Remove Every Noise at Once data from an existing genres_electronic.json, in place.

Older versions of tools/crawl_genres.py joined the local ENAO snapshot into each
record (an ``everynoise`` block of colour + map coordinates). That data carries no
licence and this file ships inside the app, so the crawler no longer writes it;
this script cleans a file written before that change, without re-crawling.

Removes ``genres[].everynoise``, the ``"everynoise"`` entry in ``genres[].sources``,
``licences.everynoise`` and ``coverage.everynoise``. Keeps ``everynoise_id``: that is
Wikidata property P9881 (CC0), not ENAO data. Idempotent; writes atomically, in
the same format the crawler does.

Usage:
    python tools/strip_enao_fields.py                 # the repo's data file
    python tools/strip_enao_fields.py path/to/genres_electronic.json
"""

import argparse
import json
import os
import sys
from pathlib import Path

DEFAULT = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "vibenative"
    / "data"
    / "genres_electronic.json"
)


def strip(blob: dict) -> int:
    """Strip ENAO fields from a parsed file, in place. Returns records changed."""
    changed = 0
    for rec in blob.get("genres", []):
        had = rec.pop("everynoise", None) is not None
        sources = rec.get("sources")
        if isinstance(sources, list) and "everynoise" in sources:
            rec["sources"] = [s for s in sources if s != "everynoise"]
            had = True
        changed += had
    for section in ("licences", "coverage"):
        if isinstance(blob.get(section), dict):
            blob[section].pop("everynoise", None)
    return changed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", nargs="?", type=Path, default=DEFAULT)
    args = ap.parse_args(argv)

    blob = json.loads(args.path.read_text(encoding="utf-8"))
    before = len(blob.get("genres", []))
    changed = strip(blob)
    after = len(blob.get("genres", []))

    tmp = args.path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(blob, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, args.path)
    print(f"{args.path}: {before} records before, {after} after; {changed} had ENAO data removed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
