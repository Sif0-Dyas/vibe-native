"""Build the Every Noise at Once genre reference from a locally saved page.

Every Noise at Once (https://everynoise.com) plots ~6,300 Spotify genres on a
2-D map -- y runs mechanical/electric -> organic/acoustic, x runs dense and
atmospheric -> spiky and bouncy -- and each genre's colour *is* its position
encoded as RGB. That gives us a fixed, human-meaningful coordinate system and a
canonical palette for genre names, which the Discogs-400 label set alone can't
provide. See ``vibenative.enao`` for how the axes were verified.

The site has no API, no bulk download, and its robots.txt is ``Disallow: /``, so
this script **never touches the network**. You save the page once from a browser
(Ctrl+S, either "HTML only" or "Complete"), and this converts that local file
into ``src/vibenative/data/enao.json``. Same arrangement as ``models/``: the
generated artifact stays git-ignored and local, and nothing in the running app
fetches anything.

The data is a frozen snapshot -- the site lost its Spotify feed in Dec 2023 --
so treat it as a static reference, not a live source.

Usage::

    python tools/build_enao.py "C:/Users/me/Desktop/Every Noise at Once.html"
    python tools/build_enao.py page.html --out src/vibenative/data/enao.json
"""

import argparse
import html
import json
import re
import sys
from pathlib import Path

# One genre node, as emitted by everynoise.com:
#
#   <div id=item1 preview_url="..." class="genre scanme" scan=true
#        style="color: #ad8907; top: 4997px; left: 783px; font-size: 160%"
#        onclick="playx(&quot;1V6gIisPpYqgFeWbMLI0bA&quot;, &quot;pop&quot;, this);"
#        title="e.g. Demi Lovato &quot;Heart Attack&quot;">pop<a ...>&raquo;</a></div>
#
# The served page leaves attributes unquoted (id=item1); a browser "Save as"
# round-trips them through the DOM serializer and quotes them (id="item1").
# `["']?` on every attribute makes the parser accept both forms, so it doesn't
# matter which way the page was saved.
_Q = r"[\"']?"
GENRE_RE = re.compile(
    rf"<div\s+id={_Q}item\d+{_Q}[^>]*?"
    rf"style={_Q}color:\s*(#[0-9a-fA-F]{{6}});\s*"
    rf"top:\s*(\d+)px;\s*left:\s*(\d+)px;\s*font-size:\s*(\d+)%{_Q}"
    rf"[^>]*?onclick={_Q}playx\(&quot;([^&]*)&quot;,\s*&quot;(.*?)&quot;",
    re.I,
)

# The example artist/track lives in the node's title attribute, as
#   title="e.g. Demi Lovato &quot;Heart Attack&quot;"
# It is advisory only -- a genre with no example still gets coordinates.
EXAMPLE_RE = re.compile(rf"title={_Q}e\.g\.\s*(.*?)\s*&quot;(.*?)&quot;", re.I)


def parse(markup):
    """Parse saved Every Noise markup into a list of genre dicts.

    Pure: takes the page text, returns records. No I/O, so it unit-tests off a
    small canned string. Duplicate genre names keep their first occurrence
    (the page lists each genre once; this is belt-and-braces).
    """
    out, seen = [], set()
    for chunk in markup.split("<div ")[1:]:
        m = GENRE_RE.match("<div " + chunk)
        if not m:
            continue
        color, top, left, size, track_id, name = m.groups()
        name = html.unescape(name).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        rec = {
            "name": name,
            # Page pixels, kept raw so they still plot against the real map.
            # Larger x = spikier/bouncier, larger y = more organic/acoustic.
            "x": int(left),
            "y": int(top),
            "color": color.lower(),
            # font-size % is the site's popularity proxy (~100-160).
            "size": int(size),
        }
        if track_id:
            rec["track_id"] = track_id
        # Search the opening tag only, so a genre whose *label text* happens to
        # contain "e.g." can't be mistaken for the title attribute.
        tag_end = chunk.find(">")
        ex = EXAMPLE_RE.search(chunk[:tag_end] if tag_end != -1 else chunk)
        if ex:
            rec["example"] = {
                "artist": html.unescape(ex.group(1)).strip(),
                "title": html.unescape(ex.group(2)).strip(),
            }
        out.append(rec)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("page", type=Path, help="locally saved everynoise.com homepage (.html)")
    ap.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent.parent
        / "src"
        / "vibenative"
        / "data"
        / "enao.json",
        help="output JSON (default: src/vibenative/data/enao.json)",
    )
    args = ap.parse_args(argv)

    if not args.page.is_file():
        ap.error(f"no such file: {args.page}")

    # The page declares UTF-8 and browsers preserve it on save.
    markup = args.page.read_text(encoding="utf-8")
    genres = parse(markup)
    if not genres:
        print(
            f"error: no genre nodes found in {args.page.name}.\n"
            "Is this the everynoise.com homepage? A saved *shortcut* (.url, a few\n"
            "hundred bytes) won't work -- you need the page itself (~3.5 MB).",
            file=sys.stderr,
        )
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps({"source": "everynoise.com", "genres": genres}, ensure_ascii=False),
        encoding="utf-8",
    )
    kb = args.out.stat().st_size / 1024
    print(f"{len(genres)} genres -> {args.out} ({kb:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
