"""Crawl the open web for everything publicly known about electronic music genres.

What this produces
------------------
``src/vibenative/data/genres_electronic.json`` -- one record per electronic genre
with its name, aliases, a one-line description, a prose excerpt, its place in the
genre hierarchy (parents/children/influences), when and where it started, and its
IDs in the other four genre vocabularies this project touches:

* **Every Noise at Once** (Wikidata P9881) -- the ID only. The ENAO data itself
  (colour, map coordinates) is deliberately NOT joined in: it carries no licence,
  and this file ships in the app. ``tools/strip_enao_fields.py`` removes it from a
  file written by an older version of this crawler.
* **MusicBrainz** (P8052), **Discogs style** (P9219) -- the latter is the same
  vocabulary the Discogs-400 classifier emits, so this is a route from a model
  label to a described, dated, placed genre.
* **Rate Your Music** (P9173) -- for onward reference only; RYM is not crawled.

Sources, and why these ones
---------------------------
Every source below was checked against its own ``robots.txt`` before being used.
That is not a formality here: this repo already refused to crawl everynoise.com
for exactly this reason (see ``tools/build_enao.py``), and the same rule is
applied consistently.

1. **Wikidata, via the QLever public mirror** (``qlever.cs.uni-freiburg.de``,
   no robots.txt -> unrestricted). CC0. The backbone: ~610 genres reachable by
   ``P279* -> Q9778`` (subclass-of* electronic music), of which ~602 carry an
   English description and ~478 carry aliases.

   Wikidata's *own* endpoint (``query.wikidata.org``) is deliberately NOT used --
   its robots.txt is ``Disallow: /sparql``. QLever hosts the same CC0 dump and
   publishes it for querying, so it is the compliant way to ask the question.

2. **DBpedia** (``dbpedia.org/sparql``, robots.txt explicitly permits ``/sparql``).
   CC BY-SA. Supplies the infobox edges Wikidata models thinly: ``stylisticOrigins``,
   ``derivatives``, ``subgenres``, ``fusiongenres``, ``otherNames``,
   ``culturalOrigins``, ``instruments``.

   Measured caveat that shapes the design: DBpedia's public endpoint serves **no**
   English prose any more -- ``dbo:abstract`` and ``rdfs:comment`` both return zero
   rows, and ``dbo:description`` only yields multilingual one-word labels
   ("genere musicale"). So DBpedia is used for structure only, and the prose comes
   from source 3. It also 502s intermittently under load, hence the retry/backoff.

3. **Wikimedia REST** (``api.wikimedia.org``, no robots.txt -> unrestricted).
   CC BY-SA. ``/core/v1/wikipedia/en/search/page`` returns a short description plus
   an excerpt of the lead section -- the readable gloss DBpedia can no longer give.

   Note ``en.wikipedia.org/api/rest_v1/...`` is the better-known endpoint and is
   NOT used: en.wikipedia.org's robots.txt carries ``Disallow: /api/``.
   ``api.wikimedia.org`` is Wikimedia's dedicated API host and carries no such rule.

4. **MusicBrainz** ``/ws/2/genre/all`` -- the full ~2,000-name genre vocabulary, in
   one single request. **Opt-in** (``--musicbrainz``), because musicbrainz.org's
   robots.txt says ``Disallow: /ws``. That directive is aimed at search-engine
   crawlers indexing API output rather than at documented API clients honouring the
   published 1-request/second limit, but it is not this script's call to make
   silently -- so it is off by default and the flag says what it does.


Being a polite crawler
----------------------
``Fetcher`` enforces, per host: robots.txt (parsed once, cached), a minimum delay
between requests, retry with exponential backoff on 5xx/timeouts, and an on-disk
response cache so re-runs and interrupted runs cost the sources nothing. Every
request carries a User-Agent naming the tool and its repository.

Usage::

    python tools/crawl_genres.py                     # full crawl (~10 min cold)
    python tools/crawl_genres.py --no-wikipedia      # structure only, ~1 min
    python tools/crawl_genres.py --musicbrainz       # + MB vocabulary (see 4)
    python tools/crawl_genres.py --limit 25 -v       # quick smoke test
    python tools/crawl_genres.py --refresh           # ignore the cache

Like ``models/`` and ``enao.json``, the generated artifact is git-ignored: it is a
derived aggregate of CC0 and CC BY-SA sources, and the per-record ``sources`` field
plus the file's ``licences`` block carry the attribution needed to redistribute it.
"""

import argparse
import hashlib
import html
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / "src" / "vibenative" / "data" / "genres_electronic.json"
DEFAULT_CACHE = REPO_ROOT / ".cache" / "genre-crawl"

USER_AGENT = "vibenative-genre-crawler/1.0 (+https://github.com/Sif0-Dyas/vibe-native)"

QLEVER = "https://qlever.cs.uni-freiburg.de/api/wikidata"
DBPEDIA = "https://dbpedia.org/sparql"
WIKIMEDIA = "https://api.wikimedia.org/core/v1/wikipedia/en/search/page"
MUSICBRAINZ = "https://musicbrainz.org/ws/2/genre/all"

# Hosts whose robots.txt Disallow rules cover a documented public API rather than
# crawlable content. Nothing here is bypassed unless the caller opts in with the
# flag named alongside it -- see source 4 in the module docstring.
ROBOTS_OPT_IN = {"musicbrainz.org": "--musicbrainz"}

# Per-host minimum seconds between requests. MusicBrainz *documents* 1 req/sec;
# the others have no published figure, so these are conservative guesses.
HOST_DELAY = {
    "musicbrainz.org": 1.1,
    "dbpedia.org": 0.5,
    "qlever.cs.uni-freiburg.de": 0.5,
    "api.wikimedia.org": 0.3,
}

LICENCES = {
    "wikidata": "CC0-1.0 (Wikidata), served via the QLever public mirror",
    "dbpedia": "CC-BY-SA-3.0 / GFDL (DBpedia, derived from Wikipedia infoboxes)",
    "wikipedia": "CC-BY-SA-4.0 (English Wikipedia, via api.wikimedia.org)",
    "musicbrainz": "CC0-1.0 (MusicBrainz genre vocabulary)",
}

WD = "http://www.wikidata.org/entity/"
ELECTRONIC_MUSIC = "Q9778"

SPARQL_PREFIXES = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX schema: <http://schema.org/>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
"""

# Wikidata external-ID properties, resolved from the live property labels rather
# than guessed. Each maps to the field name used in the output record.
EXTERNAL_IDS = {
    "P9881": "everynoise_id",
    "P8052": "musicbrainz_id",
    "P9219": "discogs_style_id",
    "P9173": "rateyourmusic_id",
}

# Wikidata item->item edges worth keeping, with their output field. Measured
# coverage across the electronic set is in the comment: P1303 (instrument) is
# omitted because exactly 1 of ~610 genres has it -- DBpedia's dbp:instruments
# covers that far better.
WD_EDGES = {
    "P279": "parents",  # subclass of        -- 607/610
    "P31": "instance_of",  # instance of     -- 604/610
    "P495": "origin_country",  # country of origin -- 177/610
    "P737": "influenced_by",  # influenced by -- 69/610
    "P361": "part_of",  # part of            -- 14/610
}

# DBpedia infobox predicates -> output field. These are the ones measured to carry
# real data for electronic genres (see the docstring); the dbp: (raw infobox) forms
# consistently out-cover their dbo: (ontology-mapped) equivalents, e.g.
# dbp:stylisticOrigins 174 vs dbo:stylisticOrigin 149.
DBP_FIELDS = {
    "http://dbpedia.org/property/stylisticOrigins": "stylistic_origins",
    "http://dbpedia.org/property/derivatives": "derivatives",
    "http://dbpedia.org/property/subgenres": "subgenres",
    "http://dbpedia.org/property/fusiongenres": "fusion_genres",
    "http://dbpedia.org/property/otherNames": "other_names",
    "http://dbpedia.org/property/culturalOrigins": "cultural_origins",
    "http://dbpedia.org/property/instruments": "instruments",
    "http://dbpedia.org/property/regionalScenes": "regional_scenes",
    "http://dbpedia.org/property/localScenes": "local_scenes",
}


# --------------------------------------------------------------------------- #
# pure helpers (no I/O -- these are what the unit tests exercise)
# --------------------------------------------------------------------------- #


def norm(name):
    """Fold a genre name to a join key: accents stripped, case and separators flat.

    ``"Drum & Bass"``, ``"drum-and-bass"`` and ``"Drum and Bass"`` all collapse
    together, which is what lets the four vocabularies be joined on name where an
    explicit ID is missing.
    """
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", str(name))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def qid(iri):
    """``http://www.wikidata.org/entity/Q341364`` -> ``Q341364`` (else '')."""
    s = str(iri or "")
    return s[len(WD) :] if s.startswith(WD) else ""


def wiki_title(article_url):
    """``https://en.wikipedia.org/wiki/Acid_house`` -> ``Acid_house`` (else '')."""
    m = re.match(r"https?://en\.wikipedia\.org/wiki/(.+)$", str(article_url or ""))
    return urllib.parse.unquote(m.group(1)) if m else ""


def dbpedia_iri(title):
    """Wikipedia title -> DBpedia resource IRI.

    DBpedia mints one resource per English Wikipedia article under the same title,
    so this is a pure derivation -- no lookup request needed to join the two.
    """
    return "http://dbpedia.org/resource/" + urllib.parse.quote(title.replace(" ", "_"))


def cell(binding, key):
    """Value of one SPARQL result cell, or '' when the OPTIONAL didn't match."""
    return binding.get(key, {}).get("value", "")


def strip_html(text):
    """Drop tags/entities from a Wikimedia search excerpt.

    Excerpts arrive with the match wrapped in ``<span class="searchmatch">``; the
    text is what we want, not the highlighting.

    Entities go through ``html.unescape`` rather than a hand-rolled replacement
    table, because these excerpts use the zero-padded numeric forms (``&#039;`` in
    every apostrophe of "drum 'n' bass") as well as the named ones.
    """
    s = re.sub(r"<[^>]+>", "", str(text or ""))
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


DBPEDIA_RESOURCE = "http://dbpedia.org/resource/"


def pretty_value(value):
    """A DBpedia object as readable text.

    Half of what these predicates point at is a resource IRI and half is a plain
    literal, in the same result column -- ``dbp:derivatives`` yields
    ``.../resource/Grime_music`` while ``dbp:otherNames`` yields ``"DnB, D&B"``.
    Resource IRIs become their article title; anything else is left alone bar
    HTML cleanup. Only the dbpedia.org namespace is rewritten, so an external
    link stays a usable URL.
    """
    s = str(value or "").strip()
    if s.startswith(DBPEDIA_RESOURCE):
        s = urllib.parse.unquote(s[len(DBPEDIA_RESOURCE) :]).replace("_", " ")
    return strip_html(s)


def clean_relations(values, own_name):
    """Drop the two kinds of junk DBpedia relation lists reliably contain.

    Both were found in real output for ``drum and bass``, whose ``dbp:subgenres``
    came back containing "Drum and bass" itself and "List of industrial music
    genres":

    * **self-references** -- an infobox that names the article's own genre among
      its subgenres, which is noise in a graph edge, and
    * **Wikipedia list articles** -- "List of ..." is a navigation page, not a
      genre, so it would appear as a phantom node.
    """
    own = norm(own_name)
    out = []
    for value in values:
        folded = norm(value)
        if not folded or folded == own or folded.startswith("list of "):
            continue
        out.append(value)
    return out


def split_names(values):
    """Flatten infobox name lists: ``["DnB, drum 'n' bass, D&B"]`` -> three names.

    ``dbp:otherNames`` is a list in the article but arrives as one comma-joined
    literal. Splitting it is what makes those spellings usable as aliases; the
    separators are only ``,`` and ``;``, so a name like ``drum 'n' bass`` survives
    intact.
    """
    out = []
    for value in values:
        for part in re.split(r"[,;]", pretty_value(value)):
            part = part.strip()
            if part:
                out.append(part)
    return out


def year_of(value):
    """Pull a signed year out of the several shapes these fields arrive in.

    Wikidata inception is an ISO timestamp (``1985-01-01T00:00:00Z``, and BCE dates
    carry a leading ``-``); DBpedia culturalOrigins is a bare number that may have
    picked up a decimal point on the way through the infobox (``1990.0``, and
    ``-1980.0`` for "1980s"). Returns an int, or None if there's no year in there.
    """
    s = str(value or "").strip()
    m = re.match(r"^(-?)(\d{1,4})", s)
    if not m:
        return None
    year = int(m.group(2))
    if not m.group(1):
        return year
    # A leading '-' is ambiguous: on an ISO timestamp it means BCE, but on
    # DBpedia's numeric infobox values it is just noise from a range -- techno's
    # culturalOrigins arrives as "-1980.0", meaning the 1980s. Nothing electronic
    # predates the 20th century, so a modern-looking negative year is the latter
    # and the sign is dropped; a genuinely ancient one is kept as BCE.
    return year if year > 1900 else -year


def group_rows(bindings, key="g"):
    """Group tall SPARQL rows by their subject cell, preserving order."""
    out = {}
    for b in bindings:
        out.setdefault(cell(b, key), []).append(b)
    return out


def dedupe(values):
    """Order-preserving de-duplication of a list of strings."""
    seen, out = set(), []
    for v in values:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def subclass_depth(parents, root, max_depth=64):
    """Distance from ``root`` down a parent map, by breadth-first search.

    ``parents`` maps child -> list of parents. Depth 0 is the root itself, 1 is a
    direct subclass, and so on; an entry not reachable from the root is absent from
    the result. Wikidata's subclass graph genuinely contains cycles (two genres
    each declared a subclass of the other), so the visited set is load-bearing
    rather than defensive, and ``max_depth`` bounds a pathological chain.

    Depth is what makes the dataset honest about breadth: a transitive
    ``subclass-of* electronic music`` query pulls in fusion genres many hops out,
    and a consumer that only wants the core can threshold on this instead of
    trusting that everything returned is equally "electronic".
    """
    children = {}
    for child, ps in parents.items():
        for p in ps:
            children.setdefault(p, []).append(child)
    depth = {root: 0}
    frontier = [root]
    d = 0
    while frontier and d < max_depth:
        d += 1
        nxt = []
        for node in frontier:
            for child in children.get(node, ()):
                if child not in depth:
                    depth[child] = d
                    nxt.append(child)
        frontier = nxt
    return depth


def build_records(wd_items, wd_edges, wd_ids, dbp, wiki, label_of):
    """Merge every source into the final per-genre records. Pure.

    Kept free of I/O so the whole merge -- including the ID joins and the
    provenance list -- is unit-testable off small canned dicts.
    """
    parents = {q: list(wd_edges.get(q, {}).get("parents", [])) for q in wd_items}
    depth = subclass_depth(parents, ELECTRONIC_MUSIC)

    records = []
    for q, item in sorted(wd_items.items(), key=lambda kv: kv[1]["name"].lower()):
        edges = wd_edges.get(q, {})
        rec = {
            "name": item["name"],
            "key": norm(item["name"]),
            "wikidata_id": q,
            "description": item.get("description", ""),
            "aliases": dedupe(item.get("aliases", [])),
            "electronic_depth": depth.get(q),
            "sources": ["wikidata"],
        }

        # Wikidata item->item edges, rendered as readable names where we know them.
        for field in ("parents", "instance_of", "origin_country", "influenced_by", "part_of"):
            names = dedupe(label_of.get(t, t) for t in edges.get(field, ()))
            if names:
                rec[field] = names

        if item.get("inception"):
            y = year_of(item["inception"])
            if y is not None:
                rec["origin_year"] = y

        ids = wd_ids.get(q, {})
        for field, value in sorted(ids.items()):
            rec[field] = value

        title = item.get("wikipedia_title", "")
        if title:
            rec["wikipedia"] = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(
                title.replace(" ", "_")
            )
            rec["dbpedia"] = dbpedia_iri(title)

        # DBpedia infobox fields, keyed by the same derived resource IRI.
        extra = dbp.get(rec.get("dbpedia", ""), {})
        if extra:
            rec["sources"].append("dbpedia")
        for field, values in sorted(extra.items()):
            if field == "cultural_origins":
                years = [year_of(v) for v in values]
                years = [y for y in years if y is not None]
                # Only fill from DBpedia when Wikidata had no inception date.
                if years and "origin_year" not in rec:
                    rec["origin_year"] = min(years)
                continue
            if field == "other_names":
                # Comma-joined in the infobox; also folded into aliases, since
                # that is the field a caller matching a user's spelling will read.
                cleaned = dedupe(split_names(values))
                known = {norm(a) for a in rec["aliases"]} | {rec["key"]}
                rec["aliases"] = rec["aliases"] + [n for n in cleaned if norm(n) not in known]
            else:
                cleaned = clean_relations(dedupe(pretty_value(v) for v in values), item["name"])
            if cleaned:
                rec[field] = cleaned

        # Wikipedia prose, keyed by article title.
        page = wiki.get(title, {}) if title else {}
        if page:
            rec["sources"].append("wikipedia")
            if page.get("excerpt"):
                rec["excerpt"] = page["excerpt"]
            # Wikipedia's short description is a decent fallback when Wikidata's
            # is missing, but never overrides it.
            if page.get("description") and not rec["description"]:
                rec["description"] = page["description"]
            # This genre has no article of its own; Wikipedia treats it inside a
            # broader one. Recorded so a caller knows where to read about it, and
            # can tell "no coverage" apart from "covered elsewhere".
            if page.get("covered_by"):
                rec["wikipedia_covered_by"] = page["covered_by"]

        records.append(rec)
    return records


def cross_reference(records, mb_names):
    """Mark which records MusicBrainz also knows, and which MB names we missed.

    Returns ``(matched_count, unmatched_names)``. Matching is by folded name or by
    the P8052 ID Wikidata already carries. The unmatched list is reported rather
    than guessed at: MusicBrainz's genre list is flat, with no parent genre, so
    there is no non-heuristic way to tell whether an unmatched name like
    ``acholitronix`` is electronic. Recording it as an open question beats
    inventing a classification -- the same call ``vibenative.enao`` makes about
    prefix-guessing unmapped styles.
    """
    known = set()
    for r in records:
        known.add(r["key"])
        known.update(norm(a) for a in r.get("aliases", ()))
        if r.get("musicbrainz_id"):
            known.add(norm(r["musicbrainz_id"]))
    matched = 0
    unmatched = []
    for name in mb_names:
        if norm(name) in known:
            matched += 1
        else:
            unmatched.append(name)
    for r in records:
        if r["key"] in {norm(n) for n in mb_names}:
            r.setdefault("sources", []).append("musicbrainz")
    return matched, unmatched


# --------------------------------------------------------------------------- #
# I/O: a polite fetcher
# --------------------------------------------------------------------------- #


class RobotsDenied(Exception):
    """Raised when robots.txt forbids a URL and the caller hasn't opted in."""


class Fetcher:
    """HTTPS GET with robots.txt enforcement, rate limiting, retries and a cache.

    One instance per run. ``opt_in`` is the set of hosts from ``ROBOTS_OPT_IN``
    the caller explicitly enabled; every other host is held to its robots.txt.
    """

    def __init__(
        self,
        cache_dir=None,
        delay=None,
        refresh=False,
        opt_in=(),
        verbose=False,
        opener=None,
        sleep=time.sleep,
        tries=4,
    ):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.delay = delay
        self.refresh = refresh
        self.opt_in = set(opt_in)
        self.verbose = verbose
        self.tries = tries
        # Injectable so the tests can drive the whole class without a network or a
        # real clock.
        self._open = opener or self._urlopen
        self._sleep = sleep
        self._robots = {}
        self._last = {}
        self.stats = {"fetched": 0, "cached": 0, "failed": 0, "denied": 0}

    # -- robots ------------------------------------------------------------- #

    def _robots_for(self, host):
        """Parsed robots.txt for ``host``, fetched once per run and remembered.

        Status handling follows RFC 9309 s2.3.1, which is *not* what you get for
        free: a ``RobotFileParser`` that never parsed anything answers ``can_fetch``
        with **False**, because ``last_checked`` is still 0. Two of the four hosts
        here answer 404 for robots.txt -- meaning unrestricted -- so relying on the
        default would have blocked the entire crawl. Hence the explicit mapping:

        * 2xx -> parse the rules,
        * 401/403 -> access to robots.txt itself is restricted; treat as full deny,
        * other 4xx (incl. 404 = no robots.txt at all) -> allow all,
        * 5xx or unreachable -> deny for this run. Conservative on purpose: an
          endpoint that can't tell us its rules doesn't get crawled by default.
        """
        if host in self._robots:
            return self._robots[host]

        parser = urllib.robotparser.RobotFileParser()
        url = f"https://{host}/robots.txt"
        parser.set_url(url)
        try:
            body = self._fetch_bytes(url, timeout=30, tries=2)
            # Some hosts serve robots.txt with a UTF-8 BOM, which would otherwise
            # end up glued to the first directive.
            parser.parse(body.decode("utf-8", "replace").lstrip("﻿").splitlines())
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                parser.disallow_all = True
            elif 400 <= exc.code < 500:
                parser.allow_all = True
            else:
                parser.disallow_all = True
            if self.verbose:
                verdict = "deny all" if parser.disallow_all else "allow all"
                print(f"  robots {host}: HTTP {exc.code} -> {verdict}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001  -- DNS, timeout, reset
            parser.disallow_all = True
            print(
                f"  robots {host}: unreachable ({type(exc).__name__}) -> refusing to crawl",
                file=sys.stderr,
            )
        self._robots[host] = parser
        return parser

    def allowed(self, url):
        """Is ``url`` fetchable? Consults robots.txt unless the host is opted in."""
        host = urllib.parse.urlsplit(url).netloc
        if host in self.opt_in:
            return True
        return self._robots_for(host).can_fetch(USER_AGENT, url)

    # -- rate limiting + cache --------------------------------------------- #

    def _wait(self, host):
        gap = self.delay if self.delay is not None else HOST_DELAY.get(host, 1.0)
        elapsed = time.monotonic() - self._last.get(host, 0.0)
        if self._last.get(host) is not None and elapsed < gap:
            self._sleep(gap - elapsed)
        self._last[host] = time.monotonic()

    def _cache_path(self, url):
        if not self.cache_dir:
            return None
        host = urllib.parse.urlsplit(url).netloc.replace(":", "_")
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
        return self.cache_dir / host / f"{digest}.bin"

    def _urlopen(self, url, timeout=60, accept=None):
        if not url.startswith("https://"):
            raise ValueError(f"refusing non-HTTPS URL: {url}")
        headers = {"User-Agent": USER_AGENT}
        if accept:
            headers["Accept"] = accept
        req = urllib.request.Request(url, headers=headers)
        # nosec B310  # https-only: the guard above rejects every other scheme
        return urllib.request.urlopen(req, timeout=timeout)  # nosec B310

    def _fetch_bytes(self, url, timeout=90, accept=None, tries=None):
        """Rate-limited GET with exponential backoff. No robots check, no cache.

        Separate from ``get`` so fetching robots.txt itself can reuse the retry and
        rate-limit behaviour without recursing into the robots check.
        """
        tries = self.tries if tries is None else tries
        host = urllib.parse.urlsplit(url).netloc
        last = None
        for attempt in range(tries):
            self._wait(host)
            try:
                return self._open(url, timeout=timeout, accept=accept).read()
            except urllib.error.HTTPError as exc:
                last = exc
                # 4xx other than 429 is a settled answer; retrying just adds load.
                if exc.code < 500 and exc.code != 429:
                    raise
            except Exception as exc:  # noqa: BLE001  -- timeouts, DNS, resets
                last = exc
            if attempt < tries - 1:
                backoff = 2.0 * (2**attempt)
                if self.verbose:
                    print(
                        f"  retry {attempt + 1}/{tries} in {backoff:.0f}s "
                        f"({type(last).__name__}) {url[:90]}",
                        file=sys.stderr,
                    )
                self._sleep(backoff)
        raise last

    def get(self, url, accept=None, timeout=90):
        """Fetch ``url`` as bytes, honouring cache, robots, rate limit and retries."""
        path = self._cache_path(url)
        if path and path.is_file() and not self.refresh:
            self.stats["cached"] += 1
            return path.read_bytes()

        if not self.allowed(url):
            self.stats["denied"] += 1
            hint = ROBOTS_OPT_IN.get(urllib.parse.urlsplit(url).netloc)
            raise RobotsDenied(
                f"robots.txt forbids {url}"
                + (f" -- pass {hint} to override for this documented API" if hint else "")
            )

        try:
            body = self._fetch_bytes(url, timeout=timeout, accept=accept)
        except Exception:
            self.stats["failed"] += 1
            raise
        self.stats["fetched"] += 1
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        return body

    def get_json(self, url, timeout=90):
        return json.loads(self.get(url, accept="application/json", timeout=timeout))


def sparql(fetcher, endpoint, query, timeout=180):
    """Run a SPARQL SELECT and return its result bindings."""
    url = (
        endpoint
        + "?"
        + urllib.parse.urlencode(
            {"query": SPARQL_PREFIXES + query, "format": "application/sparql-results+json"}
        )
    )
    body = fetcher.get(url, accept="application/sparql-results+json", timeout=timeout)
    return json.loads(body).get("results", {}).get("bindings", [])


def sparql_paged(fetcher, endpoint, query, order="?g", page=5000, timeout=180):
    """Run a SPARQL SELECT in LIMIT/OFFSET pages until a short page comes back.

    The endpoints cap result sets (DBpedia at 10,000 rows), and the tall edge
    queries here can exceed that, so paging is not optional.
    """
    rows, offset = [], 0
    while True:
        paged = f"{query}\nORDER BY {order}\nLIMIT {page} OFFSET {offset}"
        batch = sparql(fetcher, endpoint, paged, timeout=timeout)
        rows.extend(batch)
        if len(batch) < page:
            return rows
        offset += page


def batched(items, size):
    items = list(items)
    for i in range(0, len(items), size):
        yield items[i : i + size]


# --------------------------------------------------------------------------- #
# I/O: the sources
# --------------------------------------------------------------------------- #


def fetch_wikidata_items(fetcher, limit=None):
    """Genres reachable by ``subclass-of* electronic music``, with their text."""
    rows = sparql_paged(
        fetcher,
        QLEVER,
        f"""SELECT ?g ?label ?description ?inception ?article WHERE {{
  ?g wdt:P279* wd:{ELECTRONIC_MUSIC} .
  ?g rdfs:label ?label . FILTER(lang(?label) = "en")
  OPTIONAL {{ ?g schema:description ?description . FILTER(lang(?description) = "en") }}
  OPTIONAL {{ ?g wdt:P571 ?inception }}
  OPTIONAL {{ ?article schema:about ?g ; schema:isPartOf <https://en.wikipedia.org/> }}
}}""",
    )
    items = {}
    for b in rows:
        q = qid(cell(b, "g"))
        if not q:
            continue
        rec = items.setdefault(
            q, {"name": cell(b, "label"), "description": "", "aliases": [], "inception": ""}
        )
        rec["description"] = rec["description"] or cell(b, "description")
        rec["inception"] = rec["inception"] or cell(b, "inception")
        title = wiki_title(cell(b, "article"))
        if title:
            rec["wikipedia_title"] = title
    # The root itself is the axis, not a genre on it -- but keep it, since its
    # record is what depth 0 means and callers may want the anchor.
    if limit:
        keep = sorted(items, key=lambda q: items[q]["name"].lower())[:limit]
        items = {q: items[q] for q in keep}
    return items


def fetch_wikidata_aliases(fetcher, qids):
    """``skos:altLabel`` per genre -- the alternate spellings people actually type."""
    out = {}
    for chunk in batched(qids, 200):
        values = " ".join("wd:" + q for q in chunk)
        rows = sparql_paged(
            fetcher,
            QLEVER,
            f"""SELECT ?g ?alias WHERE {{
  VALUES ?g {{ {values} }}
  ?g skos:altLabel ?alias . FILTER(lang(?alias) = "en")
}}""",
        )
        for b in rows:
            out.setdefault(qid(cell(b, "g")), []).append(cell(b, "alias"))
    return out


def fetch_wikidata_edges(fetcher, qids):
    """The item->item relations in ``WD_EDGES``, plus every label they reference."""
    edges, referenced = {}, set()
    props = " ".join("wdt:" + p for p in WD_EDGES)
    for chunk in batched(qids, 200):
        values = " ".join("wd:" + q for q in chunk)
        rows = sparql_paged(
            fetcher,
            QLEVER,
            f"""SELECT ?g ?p ?o WHERE {{
  VALUES ?g {{ {values} }}
  VALUES ?p {{ {props} }}
  ?g ?p ?o .
}}""",
        )
        for b in rows:
            prop = cell(b, "p").rsplit("/", 1)[-1]
            field = WD_EDGES.get(prop)
            target = qid(cell(b, "o"))
            if not field or not target:
                continue
            edges.setdefault(qid(cell(b, "g")), {}).setdefault(field, []).append(target)
            referenced.add(target)
    return edges, referenced


def fetch_wikidata_ids(fetcher, qids):
    """The external-vocabulary IDs in ``EXTERNAL_IDS`` (ENAO, MB, Discogs, RYM)."""
    out = {}
    props = " ".join("wdt:" + p for p in EXTERNAL_IDS)
    for chunk in batched(qids, 200):
        values = " ".join("wd:" + q for q in chunk)
        rows = sparql_paged(
            fetcher,
            QLEVER,
            f"""SELECT ?g ?p ?o WHERE {{
  VALUES ?g {{ {values} }}
  VALUES ?p {{ {props} }}
  ?g ?p ?o .
}}""",
        )
        for b in rows:
            field = EXTERNAL_IDS.get(cell(b, "p").rsplit("/", 1)[-1])
            if field:
                out.setdefault(qid(cell(b, "g")), {}).setdefault(field, cell(b, "o"))
    return out


def fetch_labels(fetcher, qids):
    """English labels for referenced items, so edges read as names not Q-numbers."""
    out = {}
    for chunk in batched(qids, 300):
        values = " ".join("wd:" + q for q in chunk)
        rows = sparql_paged(
            fetcher,
            QLEVER,
            f"""SELECT ?g ?label WHERE {{
  VALUES ?g {{ {values} }}
  ?g rdfs:label ?label . FILTER(lang(?label) = "en")
}}""",
        )
        for b in rows:
            out.setdefault(qid(cell(b, "g")), cell(b, "label"))
    return out


def fetch_dbpedia(fetcher, iris, verbose=False):
    """The infobox fields in ``DBP_FIELDS``, batched over derived resource IRIs.

    One tall ``?g ?p ?o`` query per batch rather than one column per predicate:
    OPTIONALs across nine multi-valued predicates would cross-product into
    millions of rows.
    """
    out = {}
    props = " ".join(f"<{p}>" for p in DBP_FIELDS)
    for i, chunk in enumerate(batched(iris, 40), 1):
        values = " ".join(f"<{iri}>" for iri in chunk)
        query = f"""SELECT ?g ?p ?o WHERE {{
  VALUES ?g {{ {values} }}
  VALUES ?p {{ {props} }}
  ?g ?p ?o .
}}"""
        try:
            rows = sparql_paged(fetcher, DBPEDIA, query)
        except Exception as exc:  # noqa: BLE001
            # DBpedia 502s intermittently; a lost batch costs supplementary fields
            # on ~40 genres, not the run. Report it and carry on.
            print(f"  dbpedia batch {i} failed ({type(exc).__name__}) -- skipped", file=sys.stderr)
            continue
        for b in rows:
            field = DBP_FIELDS.get(cell(b, "p"))
            if field:
                out.setdefault(cell(b, "g"), {}).setdefault(field, []).append(cell(b, "o"))
        if verbose:
            print(f"  dbpedia batch {i}: {len(rows)} rows")
    return out


def fetch_wikipedia(fetcher, titles, verbose=False):
    """Short description + lead excerpt per article, from api.wikimedia.org.

    One request per title -- the search endpoint has no batch form. This is the
    slowest phase of the crawl and the reason for the cache; ``--no-wikipedia``
    skips it when only structure is wanted.
    """
    out = {}
    total = len(titles)
    for i, title in enumerate(sorted(titles), 1):
        url = WIKIMEDIA + "?" + urllib.parse.urlencode({"q": title.replace("_", " "), "limit": 1})
        try:
            pages = fetcher.get_json(url, timeout=60).get("pages") or []
        except Exception as exc:  # noqa: BLE001
            if verbose:
                print(f"  wikipedia {title}: {type(exc).__name__}", file=sys.stderr)
            continue
        if not pages:
            continue
        page = pages[0]
        # The search endpoint is a search, so it can answer with a different
        # article than the one asked for. Measured on the full run: 80 of 276
        # genres hit this, and every one checked was a genre whose own article is a
        # redirect into a broader one -- "Brostep" answers with "Dubstep",
        # "Darksynth" with "Synthwave", "Disco house" with "French house".
        #
        # Taking that excerpt would make brostep's description read "Dubstep is a
        # genre of...", which is wrong about the genre being described. But "this
        # genre is covered under that article" is itself a fact worth keeping, so
        # it's recorded rather than dropped. (matched_title, which would flag the
        # redirect directly, comes back null on all of these.)
        if norm(page.get("title", "")) != norm(title.replace("_", " ")):
            out[title] = {"covered_by": (page.get("title") or "").strip()}
            continue
        out[title] = {
            "description": (page.get("description") or "").strip(),
            "excerpt": strip_html(page.get("excerpt")),
        }
        if verbose and i % 50 == 0:
            print(f"  wikipedia {i}/{total}")
    return out


def fetch_musicbrainz(fetcher):
    """The full MusicBrainz genre vocabulary -- one request, newline-delimited."""
    body = fetcher.get(MUSICBRAINZ + "?fmt=txt", accept="text/plain", timeout=120)
    return [ln.strip() for ln in body.decode("utf-8", "replace").splitlines() if ln.strip()]


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #


def crawl(fetcher, limit=None, wikipedia=True, musicbrainz=False, verbose=False):
    """Run every enabled source and return ``(records, report)``."""
    say = print if verbose else (lambda *a, **k: None)

    print("wikidata: subclass-of* electronic music ...")
    items = fetch_wikidata_items(fetcher, limit=limit)
    print(f"  {len(items)} genres")
    qids = list(items)

    say("wikidata: aliases ...")
    for q, aliases in fetch_wikidata_aliases(fetcher, qids).items():
        if q in items:
            items[q]["aliases"] = aliases

    say("wikidata: relations ...")
    edges, referenced = fetch_wikidata_edges(fetcher, qids)

    say("wikidata: external IDs ...")
    ids = fetch_wikidata_ids(fetcher, qids)

    say("wikidata: labels for referenced items ...")
    label_of = fetch_labels(fetcher, referenced - set(qids))
    label_of.update({q: it["name"] for q, it in items.items()})

    titles = [it["wikipedia_title"] for it in items.values() if it.get("wikipedia_title")]

    print(f"dbpedia: infobox fields for {len(titles)} articles ...")
    dbp = fetch_dbpedia(fetcher, [dbpedia_iri(t) for t in titles], verbose=verbose)
    print(f"  {len(dbp)} genres enriched")

    wiki = {}
    if wikipedia:
        print(f"wikipedia: descriptions + excerpts for {len(titles)} articles ...")
        wiki = fetch_wikipedia(fetcher, titles, verbose=verbose)
        print(f"  {len(wiki)} articles")

    records = build_records(items, edges, ids, dbp, wiki, label_of)

    report = {"musicbrainz_matched": None, "musicbrainz_unmatched": []}
    if musicbrainz:
        print("musicbrainz: genre vocabulary ...")
        try:
            mb = fetch_musicbrainz(fetcher)
            matched, unmatched = cross_reference(records, mb)
            report.update(
                musicbrainz_total=len(mb),
                musicbrainz_matched=matched,
                musicbrainz_unmatched=unmatched,
            )
            print(f"  {len(mb)} names, {matched} matched, {len(unmatched)} unmatched")
        except RobotsDenied as exc:
            print(f"  skipped: {exc}", file=sys.stderr)

    return records, report


def summarise(records):
    """Field-coverage counts -- what the crawl actually managed to learn.

    Emptiness is tested explicitly rather than by truthiness, because
    ``electronic_depth`` is legitimately 0 for the root genre and a plain
    ``if r.get(f)`` would report that record as missing the field.
    """
    fields = [
        "electronic_depth",
        "description",
        "excerpt",
        "wikipedia_covered_by",
        "aliases",
        "parents",
        "origin_year",
        "origin_country",
        "influenced_by",
        "stylistic_origins",
        "derivatives",
        "subgenres",
        "fusion_genres",
        "other_names",
        "instruments",
        "everynoise_id",
        "musicbrainz_id",
        "discogs_style_id",
        "rateyourmusic_id",
        "wikipedia",
    ]
    return {f: sum(1 for r in records if r.get(f) not in (None, "", [], {})) for f in fields}


def build_parser():
    """The CLI. Split out from ``main`` so the flags can be tested without a crawl."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"output JSON (default: {DEFAULT_OUT.relative_to(REPO_ROOT)})",
    )
    ap.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help="response cache directory")
    ap.add_argument("--no-cache", action="store_true", help="don't read or write the cache")
    ap.add_argument("--refresh", action="store_true", help="re-fetch even if cached")
    ap.add_argument(
        "--delay",
        type=float,
        default=None,
        help="seconds between requests per host (default: per-host, see HOST_DELAY)",
    )
    ap.add_argument(
        "--limit", type=int, default=None, help="only crawl the first N genres (smoke test)"
    )
    ap.add_argument(
        "--no-wikipedia", action="store_true", help="skip the per-article prose phase (much faster)"
    )
    ap.add_argument(
        "--musicbrainz",
        action="store_true",
        help="also fetch the MusicBrainz genre vocabulary (robots.txt disallows /ws -- see module docstring)",
    )
    ap.add_argument(
        "-v", "--verbose", action="store_true", help="per-phase progress and retry detail"
    )
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)

    # A cold crawl runs for minutes, and stdout is block-buffered when it's a pipe
    # or a file -- which is exactly when someone is tailing a log to see how far it
    # has got. Line-buffer it so the phase lines appear as they happen.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, OSError):  # pragma: no cover -- exotic/replaced stdout
        pass

    fetcher = Fetcher(
        cache_dir=None if args.no_cache else args.cache,
        delay=args.delay,
        refresh=args.refresh,
        opt_in={"musicbrainz.org"} if args.musicbrainz else set(),
        verbose=args.verbose,
    )

    started = time.monotonic()
    try:
        records, report = crawl(
            fetcher,
            limit=args.limit,
            wikipedia=not args.no_wikipedia,
            musicbrainz=args.musicbrainz,
            verbose=args.verbose,
        )
    except RobotsDenied as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not records:
        print("error: no genres found -- are the endpoints reachable?", file=sys.stderr)
        return 1

    coverage = summarise(records)
    blob = {
        "source": "wikidata + dbpedia + wikipedia" + (" + musicbrainz" if args.musicbrainz else ""),
        "licences": LICENCES,
        "root": f"wd:{ELECTRONIC_MUSIC} (electronic music), via subclass-of*",
        "count": len(records),
        "coverage": coverage,
        "musicbrainz": {k: v for k, v in report.items() if v is not None},
        "genres": records,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(blob, ensure_ascii=False, indent=1), encoding="utf-8")

    kb = args.out.stat().st_size / 1024
    print(
        f"\n{len(records)} genres -> {args.out} ({kb:.0f} KB) in {time.monotonic() - started:.0f}s"
    )
    print(f"requests: {fetcher.stats}")
    width = max(len(f) for f in coverage)
    for field, n in sorted(coverage.items(), key=lambda kv: -kv[1]):
        print(f"  {field:<{width}}  {n:>4}/{len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
