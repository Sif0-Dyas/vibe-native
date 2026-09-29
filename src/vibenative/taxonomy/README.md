# `vibenative/taxonomy/`

How a genre name resolves: a Discogs style, or a name someone typed, to a
**keystone** (House, Drum n Bass, Ambient...), then an **archgenre** and a
**family** (Dance, Bass, Chill, Experimental, Other).

| Module | Holds |
| --- | --- |
| `overlay.py` | The user's edits: `taxonomy.json` beside `settings.ini` (aliases, archgenre and family reassignments, colours, hidden, order, palette). |
| `tables.py` | The built-in tables: style -> keystone, keystone -> archgenre / family, fusion names, names only a manual override uses. Data only. |
| `lexicon.py` | ~610 electronic genres from Wikidata / DBpedia / Wikipedia / MusicBrainz (`data/genres_electronic.json`, built by `tools/crawl_genres.py`, git-ignored), for names the classifier cannot emit. |
| `classify.py` | The functions: `keystone_of`, `archgenre_of`, `family_of`, `classify`, ... |
| `profiles.py` | Per-keystone reference data for the Genres view: canonical BPM range and a character sketch. |

## Precedence

**overlay -> built-in tables -> lexicon.** The first that has an answer wins.

1. **Overlay.** A user alias outranks every built-in table (it is the one statement
   in the chain somebody made on purpose about their own library); a user
   archgenre or family assignment outranks the table's.
2. **Built-in tables** (`tables.py`): the explicit style overrides, then the
   Discogs parent when the label has one (Rock is split by keyword, Electronic
   uses the style table), then -- for a bare style -- the electronic style table
   and the manual-override names.
3. **Lexicon**, only for a name the tables don't know: its parent chain is walked
   until it reaches a name the tables resolve.
4. Last, the loosest guess: read a compound name as "a kind of <keystone>".

A name none of these resolves has no keystone (`None`), and groups under
**Other**.

Colours are presentation and live outside the package (`palette.py`, the solved
default; `palettes.py`, the presets); they read the overlay's colour choices.
