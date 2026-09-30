// ESLint flat config for the static frontend JS.
//
// The frontend is ES modules (index.html loads main.js; every file imports what
// it uses and exports what others use), so no-undef needs no list of shared
// names: an import that names something the other file doesn't export, or a
// name used without an import, is an error in the file that has it.
//
// Scope: correctness only (no-undef, no-unused-vars). No stylistic rules --
// ruff owns Python style and there's no appetite for a JS style war here.

const globals = require("globals");

module.exports = [
  {
    files: ["src/vibenative/static/*.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { ...globals.browser },
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
