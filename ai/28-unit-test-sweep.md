# 28 — Unit-test coverage sweep

## Goal

Backfill missing unit tests so the package hits ≥ 90% line coverage measured by `coverage.py`. Each prior task included its own tests; this is the final pass.

## Refs

- `00-architecture.md` §14
- All prior task files

## Procedure

1. Run existing tests under coverage:
   ```
   uv run coverage run -m unittest discover -s tests
   uv run coverage report --fail-under=90
   ```
2. For any module under 90%, identify uncovered branches and add tests.
3. Common gaps:
   - Error-classification edge cases (one test per error-table row)
   - SSE edge cases (empty stream, malformed data line, comment lines, no trailing newline)
   - Sync-wrapper failures (running inside an existing async loop should raise a clear error)
   - Cost computation with `cache_*_per_mtok=None`
   - `auto_cache` on contexts with no system prompt / no tools / no messages
   - JSON-parse repair on weird inputs (`'{"a":'`, `'"abc'`, `'null'`)
   - Overflow patterns: positive case per pattern in the list
   - Provider self-registration when env vars missing (must not raise on import)
4. Update CI / `Makefile` to run `coverage report --fail-under=90` as a gate.

## Acceptance

- [ ] `coverage report` shows ≥ 90% on every module under `src/llm_providers/`.
- [ ] No module excluded from coverage measurement (no `# pragma: no cover` except on the `if sys.version_info < (3, 11): raise` line in `config.py` and on sync-wrapper error branches that genuinely cannot be reproduced in a test).
- [ ] Coverage gate wired into the test command (or documented in CI).
- [ ] New tests follow the naming + style of existing ones.

## Notes

- Checkbox task — no architectural decisions. Don't add `assert True` filler. Each new test must check a real behavior.
- If a module is genuinely hard to cover (justified `# pragma: no cover`), document the reason in a one-line comment.
- Don't lower the gate.
