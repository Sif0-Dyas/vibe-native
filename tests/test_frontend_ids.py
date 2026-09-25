"""Every element id the JS looks up by name exists in the page.

A getElementById('x') / querySelector('#x') whose element isn't there returns
null, and the first .addEventListener on it throws, stopping the rest of that
script. eslint can't see it. An id may be missing from templates/index.html only
if the JS builds that element itself; those are listed in DYNAMIC_IDS below, and
each entry is checked to really be created in the file named -- so the list
can't quietly go stale.
"""

import re
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "src" / "vibenative"
STATIC = PKG / "static"
PAGE = PKG / "templates" / "index.html"

# Ids that are rendered by JS (innerHTML / template strings), not in index.html.
DYNAMIC_IDS = {
    "options.js": {
        "db-edit",
        "db-edit-cancel",
        "db-edit-in",
        "db-edit-save",
        "fp-apply",
        "fp-check",
        "fp-folder",
        "fp-stat",
        "keyview",
        "notices",
        "opt-map-reset",
        "opt-prefs-reset",
    },
    "genres.js": {
        "gen-msg",
        "gen-rl-apply",
        "gen-rl-preview",
        "gen-rl-revert",
        "gen-rl-stat",
        "gen-snap",
        "gen-tax-msg",
        "gen-tax-reset",
    },
    "panels.js": {"lbl-count", "lbl-genre", "lbl-genres", "lbl-go", "lbl-queue"},
    "map.js": {"pop-artists", "pop-pick", "pop-sim"},
    "vibes.js": {
        "vib-create",
        "vib-imp",
        "vib-imp-file",
        "vib-imp-msg",
        "vib-new",
        "vib-top-msg",
    },
}

_BY_ID = re.compile(r"""getElementById\(\s*(['"])([^'"]+)\1\s*\)""")
_BY_SELECTOR = re.compile(r"""querySelector(?:All)?\(\s*(['"])#([A-Za-z][\w-]*)""")


def page_ids(html):
    return set(re.findall(r"""\bid\s*=\s*["']([^"']+)["']""", html))


def looked_up(js):
    return {m.group(2) for m in _BY_ID.finditer(js)} | {
        m.group(2) for m in _BY_SELECTOR.finditer(js)
    }


def unresolved(html, scripts):
    """{file: ids it looks up that neither the page nor DYNAMIC_IDS accounts for}."""
    known = page_ids(html) | set().union(*DYNAMIC_IDS.values())
    out = {}
    for name, js in scripts.items():
        missing = looked_up(js) - known
        if missing:
            out[name] = sorted(missing)
    return out


def _scripts():
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(STATIC.glob("*.js"))}


def test_every_looked_up_id_exists_in_the_page_or_is_built_by_js():
    assert unresolved(PAGE.read_text(encoding="utf-8"), _scripts()) == {}


def test_every_dynamic_id_is_really_created_by_its_file():
    scripts = _scripts()
    for name, ids in DYNAMIC_IDS.items():
        for i in ids:
            assert re.search(rf"""\bid\s*=\s*\\?["'`]{re.escape(i)}\\?["'`]""", scripts[name]), (
                f"{i} is listed as built by {name}, but {name} never creates it"
            )


def test_the_check_catches_a_page_missing_an_element_the_js_needs():
    # The stale-server case: the new app.js against a page without batch-cancel.
    page = PAGE.read_text(encoding="utf-8")
    stale = re.sub(r"""<button id="batch-cancel"[^>]*>.*?</button>""", "", page)
    assert stale != page
    assert unresolved(stale, _scripts()) == {"app.js": ["batch-cancel"]}
