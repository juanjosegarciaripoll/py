# Py agentic coding

Python port of the Pi agentic framework. Standard libraries, minimal deps, sandboxed tools.

## Components

- `llm-providers` — LLM API connectors. Mirrors `pi-mono/packages/ai`.
- `py-agent` — agent loop / context / tools / skills.
- `py-coding-agent` — CLI + TUI harness. Mirrors `pi-mono/packages/coding-agent`.
- `py-agent-tools` — shared tool definitions.

## Project rules

- Python 3.13. uv workspace. `uv run --no-cache <cmd>` for everything.
- Stdlib-first. Pydantic only when it clearly simplifies parsing/validation/serialization.
- Strict type checking: every PR passes `ruff`, `basedpyright`, `mypy`. Fix problems, don't silence them. No `--unsafe-fixes`. Avoid `cast()`.
- Tests: `unittest` only (no pytest). Run under `coverage`. ≥ 90% line, hard gate. Tests target public APIs, not privates.
- Code: type annotations everywhere. Compact. Document non-obvious behavior. Prefer `match` / dispatch dict over long if-chains.
- Config: TOML. CLI installs as standalone program.
- `git commit`: request escalated execution directly.

## Doc map

- Phase status & scope → `PLAN.md`.
- Active phase architecture decisions → `ai/00-architecture.md` (single source of truth).
- Task list for active phase → `ai/README.md`, individual files `ai/NN-*.md`.
- Audit motivating current phase → `FEATURES_LLM_PROVIDERS.md`.
- User-facing docs → `docs/`.
