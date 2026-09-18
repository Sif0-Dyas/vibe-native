// ESLint flat config for the static frontend JS.
//
// The frontend ships as plain <script>-loaded files (app.js -> player.js ->
// map.js) that share ONE global scope -- not ES modules. So a function defined
// in one file and called from another is a normal cross-file reference, which
// ESLint (linting each file in isolation) would otherwise flag as no-undef.
// Rather than silence no-undef, the names that are genuinely shared across the
// files are declared as globals below (grep the files to maintain the list) --
// that way a REAL cross-file typo/rename (the failure mode of the split) still
// trips no-undef, while the legitimate shared surface is documented here.
//
// Scope: correctness only (no-undef, no-unused-vars). No stylistic rules --
// ruff owns Python style and there's no appetite for a JS style war here.

const globals = require("globals");

module.exports = [
  // genre_families.json lives in static/ too; it's data, not code -- never lint it.
  { ignores: ["src/vibenative/static/genre_families.json"] },
  {
    files: ["src/vibenative/static/*.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script", // plain scripts sharing one global scope, not modules
      globals: {
        ...globals.browser,
        // Cross-file shared surface: defined in one script, used in another.
        // Keep this list in sync with the files (grep for the names) -- a REAL
        // typo/rename across the split still trips no-undef in the caller.
        escapeHtml: "writable", // app.js  -> used by map.js, panels.js
        adjustPanelHtml: "writable", // app.js -> used by map.js (the adjust panel)
        wireAdjustPanel: "writable", // app.js -> used by map.js
        fillGenreList: "writable", // app.js -> used by map.js (shared genre datalist)
        nameHue: "writable", //     app.js -> used by map.js, vibes.js (name -> hue)
        PREFS: "writable", //       app.js -> used by map.js, options.js (app-wide preferences)
        setPref: "writable", //     app.js -> used by options.js
        THEMES: "writable", //      app.js -> used by options.js
        familyOf: "writable", //   app.js  -> used by map.js
        fmtTime: "writable", //    app.js  -> used by player.js
        PLAYER: "writable", //     player.js -> used by app.js, panels.js
        OBJ_URLS: "writable", //   player.js -> used by app.js
        HASH_FILES: "writable", // player.js -> used by app.js, nowbar.js
        FSH: "writable", //        player.js -> used by app.js, nowbar.js (FS Access handles)
        attachPlayer: "writable", // player.js -> used by app.js
        AUDIO: "writable", //      audio.js -> used by player.js, nowbar.js, map.js
        // Rows (app.js) <-> side panels (panels.js) split:
        styleInfo: "writable", //  app.js  -> used by panels.js (sibling editor dots)
        results: "writable", //    app.js  -> used by panels.js (sibling editor re-applies to rows)
        GLOBAL: "writable", //     app.js  -> used by panels.js (current lens settings)
        SIBLING_MAP: "writable", //   app.js -> used by panels.js (rebuilt by the editor)
        SIBLING_GROUPS: "writable", // app.js -> used by panels.js (edited by the editor)
        renderTags: "writable", //       panels.js -> used by app.js (finishRow)
        renderLookup: "writable", //     panels.js -> used by app.js (finishRow)
        renderVibeMatches: "writable", // panels.js -> used by app.js (finishRow)
        // Key notation (Camelot vs. musical): one preference, read wherever a
        // key is written, so the map, the rows and the export cannot disagree.
        KEYVIEW: "writable", //    app.js -> used by options.js (marks the live one)
        keyText: "writable", //    app.js -> used by map.js (keyfmt, hover label)
        setKeyView: "writable", // app.js -> used by options.js (the control)
      },
    },
    rules: {
      "no-undef": "error",
      // Correctness only: catch real unused bindings, but not the intentional
      // throwaways -- `catch (e) {}` that swallows, and `_`-prefixed placeholders.
      "no-unused-vars": [
        "error",
        { caughtErrors: "none", argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
];
