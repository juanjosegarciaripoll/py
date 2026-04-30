# Plan

Feature-by-feature port of `pi-mono` (TypeScript) to Python.

## Phase 1: `llm-providers` rebuild — in progress

Audit `FEATURES_LLM_PROVIDERS.md` (2026-04-30) found ~10–15% real parity with `pi-mono/packages/ai`: split message schema with no provider emitting the parity one, no top-level dispatch, missing reasoning/caching/abort, 4-model registry, OAuth as data only. Rewriting from scratch.

**Scope:** Anthropic + OpenAI (Completions + Responses) + OpenAI-compatible. Full feature depth. Architecture must not foreclose more providers.

**Decisions:** `ai/00-architecture.md`. **Tasks:** `ai/README.md` + `ai/NN-*.md`.

## Later phases

Re-planned after Phase 1:

- Phase 2: `py-agent` rebuild on new `llm-providers` schema.
- Phase 3: `py-coding-agent` rebuild (CLI, TUI, sessions, skills, sandbox).
- Phase 4: live validation with real credentials.

## Repo layout

- `llm-providers/` — Phase 1 target
- `py-agent/`, `py-coding-agent/`, `py-agent-tools/` — later phases
- `pi-mono/` — TS reference, kept in tree
- `ai/` — active-phase task files
- `docs/` — published docs
- `FEATURES_LLM_PROVIDERS.md` — audit
