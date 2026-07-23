# Vibe Native

Native-Windows rebuild of [Vibe_Identify](https://github.com/Sif0-Dyas/Vibe_Identify)'s
analysis engine: ONNX Runtime (+ DirectML GPU) instead of Essentia, same app,
same database, no WSL.

**Status: planned, not started.** Read `PROJECT_PLAN.md` — it contains the
full architecture, the phase-by-phase roadmap, and the Claude Code prompt for
each session. Start with Phase 0 (`tools/make_oracle.py`, run on the existing
WSL install), then Session A.

The existing WSL app is the validation oracle; nothing here changes it.
