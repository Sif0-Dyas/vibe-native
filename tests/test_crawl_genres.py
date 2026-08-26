"""Unit tests for the electronic-genre crawler (``tools/crawl_genres.py``).

Everything here runs offline. The crawler is split so that this is possible: the
parsing/merging half is pure functions over dicts, and the fetching half funnels
every request through one injectable opener, so ``Fetcher`` -- robots handling,
rate limiting, retries, cache -- is driven by a fake that never opens a socket and
a fake clock that never actually sleeps.

The robots tests are the ones that matter most. This crawler's whole premise is
that it only touches sources that permit it, and the failure mode is silent: a
robots bug either blocks a compliant source (which is what happened during
development -- ``RobotFileParser.can_fetch`` answers False when robots.txt was
never parsed, so a 404 read as "forbidden" and blocked the entire crawl) or, worse,
lets through one that said no.
"""

import json
import sys
import urllib.error
from pathlib import Path

import pytest

# tools/ is a scripts directory, not an installed package, so it isn't on the path
# the way `src/` is (see [tool.pytest.ini_options] pythonpath in pyproject.toml).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import crawl_genres as cg  # noqa: E402

# --------------------------------------------------------------------------- #
# pure helpers
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Drum & Bass", "drum and bass"),
        ("drum-and-bass", "drum and bass"),
        ("Drum and Bass", "drum and bass"),
        ("Synth-pop", "synth pop"),
        ("Norteño", "norteno"),
        ("  UK  Garage  ", "uk garage"),
        ("", ""),
        (None, ""),
    ],
)
def test_norm_folds_spelling_variants(raw, expected):
    assert cg.norm(raw) == expected


def test_norm_bridges_the_forms_the_vocabularies_disagree_on():
    # the whole point: these are the same genre in four different spellings
    assert cg.norm("2-step") == cg.norm("2 step") == cg.norm("2 Step")


def test_id_key_ignores_separators():
    # Every Noise spells it "acidhouse"; the snapshot spells it "acid house"
    assert cg.id_key("acidhouse") == cg.id_key("acid house") == "acidhouse"
    assert cg.id_key(None) == ""


def test_qid_extracts_only_wikidata_entities():
    assert cg.qid("http://www.wikidata.org/entity/Q341364") == "Q341364"
    assert cg.qid("http://dbpedia.org/resource/Acid_house") == ""
    assert cg.qid(None) == ""


def test_wiki_title_and_dbpedia_iri_round_trip():
    title = cg.wiki_title("https://en.wikipedia.org/wiki/Acid_house")
    assert title == "Acid_house"
    assert cg.dbpedia_iri(title) == "http://dbpedia.org/resource/Acid_house"
    # a non-article URL is not a title
    assert cg.wiki_title("https://de.wikipedia.org/wiki/Acid_House") == ""
    assert cg.wiki_title("") == ""


def test_wiki_title_unquotes_percent_escapes():
    assert cg.wiki_title("https://en.wikipedia.org/wiki/Musique_concr%C3%A8te") == (
        "Musique_concrète"
    )


def test_strip_html_removes_search_highlighting():
    excerpt = '<span class="searchmatch">Techno</span> is a genre of electronic&nbsp;music'
    assert cg.strip_html(excerpt) == "Techno is a genre of electronic music"
    assert cg.strip_html("R&amp;B &lt;tag&gt;") == "R&B <tag>"
    assert cg.strip_html(None) == ""


def test_strip_html_decodes_zero_padded_numeric_entities():
    # the real excerpt for drum and bass spells every apostrophe "&#039;"
    assert cg.strip_html("drum &#039;n&#039; bass") == "drum 'n' bass"
    assert cg.strip_html("caf&#233; &#39;x&#39;") == "café 'x'"


def test_clean_relations_drops_self_references_and_list_articles():
    values = ["Darkstep", "Drum and bass", "List of industrial music genres", "Neurofunk"]
    assert cg.clean_relations(values, "drum and bass") == ["Darkstep", "Neurofunk"]


def test_clean_relations_matches_the_self_reference_loosely():
    # the infobox spelling need not match the label exactly
    assert cg.clean_relations(["Drum & Bass"], "drum and bass") == []


def test_pretty_value_renders_resource_iris_as_titles():
    assert cg.pretty_value("http://dbpedia.org/resource/Grime_music") == "Grime music"
    assert cg.pretty_value("http://dbpedia.org/resource/Musique_concr%C3%A8te") == (
        "Musique concrète"
    )
    # literals pass through
    assert cg.pretty_value("DnB, D&B") == "DnB, D&B"
    # a non-dbpedia URL stays a usable URL
    assert cg.pretty_value("https://example.org/a_b") == "https://example.org/a_b"


def test_split_names_splits_comma_joined_infobox_lists():
    assert cg.split_names(["DnB, drum 'n' bass, D&B"]) == ["DnB", "drum 'n' bass", "D&B"]
    # semicolons too, and blanks are dropped
    assert cg.split_names(["a; b", " , ", "c"]) == ["a", "b", "c"]


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1985-01-01T00:00:00Z", 1985),  # Wikidata inception
        ("1990.0", 1990),  # DBpedia numeric infobox value
        ("-1980.0", 1980),  # "1980s" mangled into a negative by DBpedia
        ("-0500-01-01T00:00:00Z", -500),  # a real BCE timestamp
        ("1985", 1985),
        ("", None),
        ("mid-decade", None),
        (None, None),
    ],
)
def test_year_of_handles_every_shape_these_fields_arrive_in(raw, expected):
    assert cg.year_of(raw) == expected


def test_dedupe_preserves_first_occurrence_order():
    assert cg.dedupe(["b", "a", "b", "", None, "c"]) == ["b", "a", "c"]


def test_group_rows_buckets_by_subject():
    rows = [
        {"g": {"value": "X"}, "o": {"value": "1"}},
        {"g": {"value": "Y"}, "o": {"value": "2"}},
        {"g": {"value": "X"}, "o": {"value": "3"}},
    ]
    grouped = cg.group_rows(rows)
    assert [cg.cell(b, "o") for b in grouped["X"]] == ["1", "3"]
    assert list(grouped) == ["X", "Y"]


def test_cell_returns_empty_for_unmatched_optional():
    assert cg.cell({"g": {"value": "x"}}, "missing") == ""


def test_batched_covers_every_item():
    assert list(cg.batched(range(5), 2)) == [[0, 1], [2, 3], [4]]
    assert list(cg.batched([], 3)) == []


# --------------------------------------------------------------------------- #
# subclass depth
# --------------------------------------------------------------------------- #


def test_subclass_depth_counts_hops_from_the_root():
    parents = {
        "ROOT": [],
        "A": ["ROOT"],
        "B": ["A"],
        "C": ["B"],
        "ELSEWHERE": ["UNRELATED"],
    }
    depth = cg.subclass_depth(parents, "ROOT")
    assert depth == {"ROOT": 0, "A": 1, "B": 2, "C": 3}
    # unreachable nodes are absent rather than guessed at
    assert "ELSEWHERE" not in depth


def test_subclass_depth_survives_a_cycle():
    # Wikidata really does contain mutual subclass-of pairs; without the visited
    # set this loops forever.
    parents = {"A": ["ROOT", "B"], "B": ["A"]}
    assert cg.subclass_depth(parents, "ROOT") == {"ROOT": 0, "A": 1, "B": 2}


def test_subclass_depth_takes_the_shortest_path():
    parents = {"A": ["ROOT"], "B": ["ROOT"], "C": ["A", "B"], "D": ["C"]}
    depth = cg.subclass_depth(parents, "ROOT")
    assert depth["C"] == 2 and depth["D"] == 3


def test_subclass_depth_bounded_by_max_depth():
    parents = {f"N{i}": [f"N{i - 1}"] for i in range(1, 10)}
    parents["N0"] = ["ROOT"]
    depth = cg.subclass_depth(parents, "ROOT", max_depth=3)
    assert depth["N2"] == 3
    assert "N5" not in depth


# --------------------------------------------------------------------------- #
# the merge
# --------------------------------------------------------------------------- #


def _canned():
    """A two-genre slice shaped exactly like what the fetchers return."""
    items = {
        "Q9778": {"name": "electronic music", "description": "genre", "aliases": []},
        "Q1751409": {
            "name": "2-step garage",
            "description": "UK garage subgenre",
            "aliases": ["2 step"],
            "inception": "1998-01-01T00:00:00Z",
            "wikipedia_title": "2-step_garage",
        },
    }
    edges = {
        "Q1751409": {
            "parents": ["Q9778"],
            "origin_country": ["Q145"],
            "instance_of": ["Q188451"],
        }
    }
    ids = {
        "Q1751409": {
            "everynoise_id": "2step",
            "musicbrainz_id": "db325bd7",
            "discogs_style_id": "2-Step",
        }
    }
    dbp = {
        "http://dbpedia.org/resource/2-step_garage": {
            "derivatives": ["http://dbpedia.org/resource/Grime_music"],
            "other_names": ["2-step, two-step garage"],
            "cultural_origins": ["2001.0"],
            "instruments": ["http://dbpedia.org/resource/Synthesizer"],
        }
    }
    wiki = {
        "2-step_garage": {
            "description": "genre of UK garage",
            "excerpt": "2-step is a genre of UK garage.",
        }
    }
    enao = {"2 step": {"x": 700, "y": 2100, "color": "#abcdef", "size": 120}}
    labels = {"Q9778": "electronic music", "Q145": "United Kingdom", "Q188451": "music genre"}
    return items, edges, ids, dbp, wiki, enao, labels


def test_build_records_merges_every_source():
    rec = cg.build_records(*_canned())[0]
    assert rec["name"] == "2-step garage"
    assert rec["wikidata_id"] == "Q1751409"
    assert rec["electronic_depth"] == 1
    # Q-numbers are rendered as readable labels
    assert rec["parents"] == ["electronic music"]
    assert rec["origin_country"] == ["United Kingdom"]
    # DBpedia resource IRIs are rendered as titles
    assert rec["derivatives"] == ["Grime music"]
    assert rec["instruments"] == ["Synthesizer"]
    # Wikipedia prose
    assert rec["excerpt"] == "2-step is a genre of UK garage."
    assert sorted(rec["sources"]) == ["dbpedia", "everynoise", "wikidata", "wikipedia"]


def test_build_records_orders_records_by_name():
    # "2-step garage" sorts before "electronic music"
    assert [r["name"] for r in cg.build_records(*_canned())] == [
        "2-step garage",
        "electronic music",
    ]


def test_build_records_prefers_wikidata_inception_over_dbpedia():
    # Wikidata says 1998, DBpedia's infobox says 2001; the structured date wins
    assert cg.build_records(*_canned())[0]["origin_year"] == 1998


def test_build_records_falls_back_to_dbpedia_year():
    items, edges, ids, dbp, wiki, enao, labels = _canned()
    del items["Q1751409"]["inception"]
    rec = cg.build_records(items, edges, ids, dbp, wiki, enao, labels)[0]
    assert rec["origin_year"] == 2001


def test_build_records_folds_other_names_into_aliases():
    rec = cg.build_records(*_canned())[0]
    assert rec["other_names"] == ["2-step", "two-step garage"]
    # "2-step" normalises to the existing "2 step" alias, so only the new one lands
    assert rec["aliases"] == ["2 step", "two-step garage"]


def test_build_records_joins_everynoise_by_property_id():
    rec = cg.build_records(*_canned())[0]
    # P9881 said "2step"; the snapshot key is "2 step" -- id_key bridges them
    assert rec["everynoise"]["color"] == "#abcdef"


def test_build_records_joins_everynoise_by_name_when_id_absent():
    items, edges, ids, dbp, wiki, enao, labels = _canned()
    del ids["Q1751409"]["everynoise_id"]
    enao = {"2-step garage": {"x": 1, "y": 2, "color": "#000000", "size": 100}}
    rec = cg.build_records(items, edges, ids, dbp, wiki, enao, labels)[0]
    assert rec["everynoise"]["color"] == "#000000"


def test_build_records_omits_everynoise_without_a_snapshot():
    items, edges, ids, dbp, wiki, labels = (*_canned()[:5], _canned()[6])
    rec = cg.build_records(items, edges, ids, dbp, wiki, {}, labels)[0]
    assert "everynoise" not in rec
    assert "everynoise" not in rec["sources"]
    # the ID is still recorded, so a later snapshot can be joined without re-crawling
    assert rec["everynoise_id"] == "2step"


def test_build_records_keeps_wikidata_description_over_wikipedia():
    rec = cg.build_records(*_canned())[0]
    assert rec["description"] == "UK garage subgenre"


def test_build_records_fills_missing_description_from_wikipedia():
    items, edges, ids, dbp, wiki, enao, labels = _canned()
    items["Q1751409"]["description"] = ""
    rec = cg.build_records(items, edges, ids, dbp, wiki, enao, labels)[0]
    assert rec["description"] == "genre of UK garage"


def test_build_records_tolerates_a_genre_with_nothing_but_a_label():
    items = {"Q1": {"name": "bleep", "description": "", "aliases": []}}
    rec = cg.build_records(items, {}, {}, {}, {}, {}, {"Q1": "bleep"})[0]
    assert rec["name"] == "bleep" and rec["sources"] == ["wikidata"]
    # not reachable from the root, so depth is unknown rather than 0
    assert rec["electronic_depth"] is None


# --------------------------------------------------------------------------- #
# MusicBrainz cross-reference
# --------------------------------------------------------------------------- #


def test_cross_reference_matches_by_name_and_alias():
    records = [
        {"key": "2 step garage", "aliases": ["two-step garage"], "sources": ["wikidata"]},
        {"key": "techno", "aliases": [], "sources": ["wikidata"]},
    ]
    matched, unmatched = cg.cross_reference(records, ["2-step garage", "techno", "acholitronix"])
    assert matched == 2
    # unmatched names are reported, never classified by guesswork
    assert unmatched == ["acholitronix"]
    assert "musicbrainz" in records[1]["sources"]


def test_cross_reference_matches_via_the_alias_spelling():
    records = [{"key": "drum and bass", "aliases": ["DnB"], "sources": []}]
    matched, unmatched = cg.cross_reference(records, ["dnb"])
    assert (matched, unmatched) == (1, [])


def test_cross_reference_with_no_names_is_a_no_op():
    records = [{"key": "techno", "aliases": [], "sources": []}]
    assert cg.cross_reference(records, []) == (0, [])
    assert records[0]["sources"] == []


# --------------------------------------------------------------------------- #
# the local Every Noise snapshot
# --------------------------------------------------------------------------- #


def test_load_enao_reads_the_snapshot(tmp_path):
    path = tmp_path / "enao.json"
    path.write_text(
        json.dumps(
            {
                "genres": [
                    {"name": "techno", "x": 1, "y": 2, "color": "#111111", "size": 130},
                    {"name": "", "x": 9, "y": 9},
                ]
            }
        ),
        encoding="utf-8",
    )
    loaded = cg.load_enao(path)
    assert loaded == {"techno": {"x": 1, "y": 2, "color": "#111111", "size": 130}}


def test_load_enao_missing_file_is_a_silent_skip(tmp_path):
    # the snapshot is git-ignored, so its absence is the normal case on a fresh
    # clone -- it must degrade, not raise
    assert cg.load_enao(tmp_path / "nope.json") == {}


def test_load_enao_tolerates_corrupt_json(tmp_path):
    path = tmp_path / "enao.json"
    path.write_text("{not json", encoding="utf-8")
    assert cg.load_enao(path) == {}


# --------------------------------------------------------------------------- #
# Fetcher: robots, rate limiting, retries, cache
# --------------------------------------------------------------------------- #


class FakeResponse:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body


class FakeOpener:
    """Stands in for urlopen. Maps URL -> bytes, or an exception to raise."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, timeout=None, accept=None):
        self.calls.append(url)
        answer = self.routes
        for prefix, value in self.routes.items():
            if url.startswith(prefix):
                answer = value
                break
        else:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        if isinstance(answer, list):  # a scripted sequence of answers
            answer = answer.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return FakeResponse(answer)


def _fetcher(routes, **kw):
    slept = []
    opener = FakeOpener(routes)
    f = cg.Fetcher(opener=opener, sleep=slept.append, verbose=False, **kw)
    return f, opener, slept


def test_robots_disallow_blocks_the_url():
    f, _, _ = _fetcher(
        {
            "https://example.org/robots.txt": b"User-agent: *\nDisallow: /private\n",
        }
    )
    assert f.allowed("https://example.org/public/x") is True
    assert f.allowed("https://example.org/private/x") is False


def test_robots_disallow_all_blocks_everything():
    # this is everynoise.com's actual robots.txt, and the reason it isn't crawled
    f, _, _ = _fetcher({"https://example.org/robots.txt": b"User-agent: *\nDisallow: /\n"})
    assert f.allowed("https://example.org/anything") is False


def test_robots_404_means_unrestricted():
    """A host with no robots.txt allows everything (RFC 9309 s2.3.1.3).

    Regression guard for the bug this crawler hit in development: a fresh
    RobotFileParser that never parsed anything answers can_fetch with False, so a
    404 was read as a blanket denial and blocked two of the four sources.
    """
    f, _, _ = _fetcher({})  # every URL 404s, robots.txt included
    assert f.allowed("https://qlever.example/api/wikidata") is True


def test_robots_401_and_403_deny_everything():
    for code in (401, 403):
        f, _, _ = _fetcher(
            {
                "https://example.org/robots.txt": urllib.error.HTTPError(
                    "u", code, "denied", {}, None
                )
            }
        )
        assert f.allowed("https://example.org/x") is False


def test_robots_server_error_is_treated_as_deny():
    # conservative on purpose: a host that can't state its rules isn't crawled
    f, _, _ = _fetcher(
        {"https://example.org/robots.txt": urllib.error.HTTPError("u", 503, "busy", {}, None)},
        tries=1,
    )
    assert f.allowed("https://example.org/x") is False


def test_robots_unreachable_is_treated_as_deny():
    f, _, _ = _fetcher({"https://example.org/robots.txt": TimeoutError("timed out")}, tries=1)
    assert f.allowed("https://example.org/x") is False


def test_robots_bom_does_not_swallow_the_first_directive():
    f, _, _ = _fetcher({"https://example.org/robots.txt": "﻿User-agent: *\nDisallow: /\n".encode()})
    assert f.allowed("https://example.org/x") is False


def test_robots_is_fetched_once_per_host():
    f, opener, _ = _fetcher(
        {
            "https://example.org/robots.txt": b"User-agent: *\nDisallow: /no\n",
            "https://example.org/ok": b"body",
        }
    )
    f.get("https://example.org/ok")
    f.get("https://example.org/ok")
    assert opener.calls.count("https://example.org/robots.txt") == 1


def test_get_raises_robots_denied_with_the_opt_in_hint(monkeypatch):
    monkeypatch.setitem(cg.ROBOTS_OPT_IN, "example.org", "--example")
    f, _, _ = _fetcher({"https://example.org/robots.txt": b"User-agent: *\nDisallow: /ws\n"})
    with pytest.raises(cg.RobotsDenied) as exc:
        f.get("https://example.org/ws/2/genre/all")
    assert "--example" in str(exc.value)
    assert f.stats["denied"] == 1


def test_opt_in_host_bypasses_robots():
    f, _, _ = _fetcher(
        {
            "https://example.org/robots.txt": b"User-agent: *\nDisallow: /ws\n",
            "https://example.org/ws/2": b"1 dnb\n2 techno\n",
        },
        opt_in={"example.org"},
    )
    assert f.get("https://example.org/ws/2") == b"1 dnb\n2 techno\n"


def test_get_retries_a_server_error_then_succeeds():
    f, opener, slept = _fetcher(
        {
            "https://example.org/robots.txt": b"",
            "https://example.org/q": [
                urllib.error.HTTPError("u", 502, "bad gateway", {}, None),
                b"ok",
            ],
        }
    )
    assert f.get("https://example.org/q") == b"ok"
    assert slept  # backed off before the retry
    assert f.stats == {"fetched": 1, "cached": 0, "failed": 0, "denied": 0}


def test_get_does_not_retry_a_client_error():
    f, opener, slept = _fetcher(
        {
            "https://example.org/robots.txt": b"",
            "https://example.org/q": urllib.error.HTTPError("u", 400, "bad", {}, None),
        }
    )
    with pytest.raises(urllib.error.HTTPError):
        f.get("https://example.org/q")
    assert opener.calls.count("https://example.org/q") == 1
    assert f.stats["failed"] == 1


def test_get_gives_up_after_the_retry_budget():
    f, opener, _ = _fetcher(
        {
            "https://example.org/robots.txt": b"",
            "https://example.org/q": urllib.error.HTTPError("u", 500, "boom", {}, None),
        },
        tries=3,
    )
    with pytest.raises(urllib.error.HTTPError):
        f.get("https://example.org/q")
    assert opener.calls.count("https://example.org/q") == 3


def test_cache_is_written_then_reused(tmp_path):
    routes = {"https://example.org/robots.txt": b"", "https://example.org/q": b"payload"}
    f, opener, _ = _fetcher(routes, cache_dir=tmp_path)
    assert f.get("https://example.org/q") == b"payload"

    # a second Fetcher over a *broken* route still answers, from the cache
    f2, opener2, _ = _fetcher(
        {"https://example.org/robots.txt": b"", "https://example.org/q": OSError("network down")},
        cache_dir=tmp_path,
    )
    assert f2.get("https://example.org/q") == b"payload"
    assert f2.stats["cached"] == 1
    assert "https://example.org/q" not in opener2.calls


def test_refresh_ignores_the_cache(tmp_path):
    routes = {"https://example.org/robots.txt": b"", "https://example.org/q": b"old"}
    f, _, _ = _fetcher(routes, cache_dir=tmp_path)
    f.get("https://example.org/q")

    f2, opener2, _ = _fetcher(
        {"https://example.org/robots.txt": b"", "https://example.org/q": b"new"},
        cache_dir=tmp_path,
        refresh=True,
    )
    assert f2.get("https://example.org/q") == b"new"
    assert f2.stats["fetched"] == 1


def test_cache_keys_are_per_url(tmp_path):
    f, _, _ = _fetcher(
        {
            "https://example.org/robots.txt": b"",
            "https://example.org/a": b"A",
            "https://example.org/b": b"B",
        },
        cache_dir=tmp_path,
    )
    assert f.get("https://example.org/a") == b"A"
    assert f.get("https://example.org/b") == b"B"


def test_rate_limit_sleeps_between_requests_to_one_host():
    f, _, slept = _fetcher(
        {"https://example.org/robots.txt": b"", "https://example.org/q": b"x"},
        delay=5.0,
    )
    f.get("https://example.org/q")
    f.get("https://example.org/q")
    # the robots fetch counts as the host's first request, so both gets waited
    assert len(slept) >= 1
    assert all(0 < s <= 5.0 for s in slept)


def test_non_https_urls_are_refused():
    f = cg.Fetcher(cache_dir=None)
    with pytest.raises(ValueError, match="non-HTTPS"):
        f._urlopen("http://example.org/insecure")


def test_get_json_parses_the_body():
    f, _, _ = _fetcher(
        {"https://example.org/robots.txt": b"", "https://example.org/j": b'{"a": 1}'}
    )
    assert f.get_json("https://example.org/j") == {"a": 1}


# --------------------------------------------------------------------------- #
# SPARQL plumbing
# --------------------------------------------------------------------------- #


class FakeFetcher:
    """Answers ``get`` from a scripted list of SPARQL result payloads."""

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.urls = []

    def get(self, url, accept=None, timeout=None):
        self.urls.append(url)
        return json.dumps(self.payloads.pop(0)).encode("utf-8")

    def get_json(self, url, timeout=None):
        return json.loads(self.get(url))


def _results(*names):
    return {"results": {"bindings": [{"g": {"value": n}} for n in names]}}


def test_sparql_sends_the_prefixes_and_returns_bindings():
    f = FakeFetcher([_results("X")])
    rows = cg.sparql(f, "https://e.example/sparql", "SELECT ?g WHERE {}")
    assert cg.cell(rows[0], "g") == "X"
    assert "PREFIX+wd" in f.urls[0] or "PREFIX%20wd" in f.urls[0]


def test_sparql_paged_stops_on_a_short_page():
    # page size 2: a full page then a partial one
    f = FakeFetcher([_results("a", "b"), _results("c")])
    rows = cg.sparql_paged(f, "https://e.example/sparql", "SELECT ?g WHERE {}", page=2)
    assert [cg.cell(r, "g") for r in rows] == ["a", "b", "c"]
    assert "OFFSET+0" in f.urls[0] and "OFFSET+2" in f.urls[1]


def test_sparql_paged_single_short_page_is_one_request():
    f = FakeFetcher([_results("a")])
    cg.sparql_paged(f, "https://e.example/sparql", "SELECT ?g WHERE {}", page=100)
    assert len(f.urls) == 1


# --------------------------------------------------------------------------- #
# source-level behaviour
# --------------------------------------------------------------------------- #


def test_fetch_wikipedia_records_a_redirect_instead_of_taking_its_prose():
    """A genre whose article redirects into a broader one must not borrow its text.

    This is the real measured case, not a hypothetical: 80 of 276 genres on the
    full run answer with a parent article -- "Brostep" returns "Dubstep". Taking
    that excerpt would make brostep's description read "Dubstep is a genre of...",
    so the redirect is recorded as a pointer and the excerpt is left empty.
    """
    payloads = [
        {"pages": [{"title": "Dubstep", "description": "a genre", "excerpt": "Dubstep is..."}]},
        {"pages": [{"title": "Techno", "description": "a genre", "excerpt": "<b>right</b>"}]},
    ]
    f = FakeFetcher(payloads)
    out = cg.fetch_wikipedia(f, ["Brostep", "Techno"])
    assert out["Brostep"] == {"covered_by": "Dubstep"}
    assert "excerpt" not in out["Brostep"]
    assert out["Techno"] == {"description": "a genre", "excerpt": "right"}


def test_build_records_surfaces_the_redirect_pointer():
    items, edges, ids, dbp, _, enao, labels = _canned()
    wiki = {"2-step_garage": {"covered_by": "UK garage"}}
    rec = cg.build_records(items, edges, ids, dbp, wiki, enao, labels)[0]
    assert rec["wikipedia_covered_by"] == "UK garage"
    # no borrowed prose, and the Wikidata description is untouched
    assert "excerpt" not in rec
    assert rec["description"] == "UK garage subgenre"


def test_fetch_wikipedia_survives_a_failed_article():
    class Boom(FakeFetcher):
        def get_json(self, url, timeout=None):
            if "Techno" in url:
                raise TimeoutError("slow")
            return super().get_json(url)

    f = Boom([{"pages": [{"title": "Trance", "description": "d", "excerpt": "e"}]}])
    out = cg.fetch_wikipedia(f, ["Techno", "Trance"])
    assert list(out) == ["Trance"]


def test_fetch_wikipedia_handles_an_empty_result():
    f = FakeFetcher([{"pages": []}])
    assert cg.fetch_wikipedia(f, ["Nonesuch"]) == {}


def test_fetch_musicbrainz_parses_the_newline_list():
    class Text(FakeFetcher):
        def get(self, url, accept=None, timeout=None):
            self.urls.append(url)
            return b"2 tone\nacid house\n\n  techno  \n"

    names = cg.fetch_musicbrainz(Text([]))
    assert names == ["2 tone", "acid house", "techno"]


def test_summarise_counts_populated_fields():
    records = [
        {"description": "d", "aliases": ["a"], "excerpt": ""},
        {"description": "", "aliases": [], "excerpt": "e"},
    ]
    counts = cg.summarise(records)
    assert counts["description"] == 1 and counts["aliases"] == 1 and counts["excerpt"] == 1


def test_summarise_counts_a_zero_depth_as_present():
    # the root genre sits at depth 0; truthiness would report it as missing
    counts = cg.summarise([{"electronic_depth": 0}, {"electronic_depth": None}])
    assert counts["electronic_depth"] == 1


# --------------------------------------------------------------------------- #
# configuration sanity
# --------------------------------------------------------------------------- #


def test_every_opt_in_hint_names_a_real_flag():
    """The RobotsDenied message tells the user which flag to pass.

    If that flag doesn't exist, the error sends them in circles -- so every hint in
    ROBOTS_OPT_IN must actually parse, and must actually enable that host.
    """
    parser = cg.build_parser()
    for host, flag in cg.ROBOTS_OPT_IN.items():
        args = parser.parse_args([flag])
        attr = flag.lstrip("-").replace("-", "_")
        assert getattr(args, attr) is True, f"{flag} does not set {attr} (for {host})"


def test_defaults_keep_the_disallowed_source_off():
    args = cg.build_parser().parse_args([])
    assert args.musicbrainz is False
    # and the prose phase is on by default -- it's the only source of real text
    assert args.no_wikipedia is False


def test_user_agent_identifies_the_tool_and_its_repository():
    assert "vibenative" in cg.USER_AGENT and "github.com" in cg.USER_AGENT


def test_every_source_url_is_https():
    for url in (cg.QLEVER, cg.DBPEDIA, cg.WIKIMEDIA, cg.MUSICBRAINZ):
        assert url.startswith("https://")


def test_wikidata_query_endpoint_is_not_used():
    """query.wikidata.org's robots.txt is ``Disallow: /sparql``.

    QLever is used instead. If someone swaps the endpoint back, this fails.
    """
    source = Path(cg.__file__).read_text(encoding="utf-8")
    assert "query.wikidata.org/sparql" not in source


def test_external_id_fields_are_distinct():
    assert len(set(cg.EXTERNAL_IDS.values())) == len(cg.EXTERNAL_IDS)
