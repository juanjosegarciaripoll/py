# `llm-providers` rebuild — task index

Self-contained tasks for the rebuild. Pick one whose deps are met, execute.

**Read first:** `00-architecture.md` (decisions, source of truth). Project rules: `../AGENTS.md`.

## Workflow

1. Pick lowest-numbered task with met deps.
2. Read its file end-to-end. It cites the architecture sections that apply — read those.
3. Implement. Tests are part of the deliverable, not a follow-up.
4. Verify acceptance checklist. Run `ruff`, `basedpyright`, `mypy`, `coverage` (≥ 90%).
5. If a task forces a schema change, stop and update the foundation task before forking.

## Dependencies

```
                          00-architecture.md
                                  │
       ┌──────────────────────────┼──────────────────────────┐
       ▼                          ▼                          ▼
  01 types               05 utils/json_parse         11 env
  02 events              06 utils/overflow           12 config
  03 errors              07 utils/sanitize_unicode   13 registry  (needs 14)
  04 models              08 utils/event_stream       14 provider base
                         09 utils/headers            15 generate_models  (needs 04 + 13)
                         10 cancellation
                                  │
       ┌──────────────────────────┴───────────────────────────┐
       ▼                                                      ▼
  16 anthropic basics                              21 openai completions basics
  17 anthropic tools                               22 openai responses basics
  18 anthropic reasoning                           23 openai tools
  19 anthropic caching                             24 openai reasoning
  20 anthropic errors+abort                        25 openai errors+abort
                                                   26 openai-compatible
                                  │
                                  ▼
                         27 public API + assemble + sync wrappers
                                  │
                                  ▼
                         28 unit-test sweep (≥ 90% line)
                         29 contract-test harness
                         30 anthropic contract suite
                         31 openai contract suite
                         32 live smoke (env-gated)
```

Within each provider chain, tasks are sequential: 17 needs 16, 18 needs 17, etc.

## Files

| # | File | Subject |
|---|---|---|
| 01 | `01-types.md` | Message / content / tool dataclasses |
| 02 | `02-events.md` | Streaming event dataclasses |
| 03 | `03-errors.md` | Exception hierarchy |
| 04 | `04-models.md` | `ModelInfo` + cost helper |
| 05 | `05-utils-json-parse.md` | Tolerant partial-JSON parser |
| 06 | `06-utils-overflow.md` | Context-overflow detection |
| 07 | `07-utils-sanitize-unicode.md` | Surrogate scrub |
| 08 | `08-utils-event-stream.md` | SSE async iterator |
| 09 | `09-utils-headers.md` | Header helpers |
| 10 | `10-cancellation.md` | Abort helpers |
| 11 | `11-env.md` | Per-provider env-var resolution |
| 12 | `12-config.md` | TOML config |
| 13 | `13-registry.md` | API + model registry, dispatch |
| 14 | `14-provider-base.md` | `Provider` ABC |
| 15 | `15-generate-models.md` | `models.dev` generator + run |
| 16 | `16-anthropic-basics.md` | Anthropic — request, basic streaming |
| 17 | `17-anthropic-tools.md` | Anthropic — tool calling |
| 18 | `18-anthropic-reasoning.md` | Anthropic — thinking with signature |
| 19 | `19-anthropic-caching.md` | Anthropic — `cache_control` + `auto_cache` |
| 20 | `20-anthropic-errors-abort.md` | Anthropic — error mapping + cancel |
| 21 | `21-openai-completions-basics.md` | OpenAI Chat Completions — basic |
| 22 | `22-openai-responses-basics.md` | OpenAI Responses — basic |
| 23 | `23-openai-tools.md` | OpenAI — tool calling (both APIs) |
| 24 | `24-openai-reasoning.md` | OpenAI Responses — reasoning round-trip |
| 25 | `25-openai-errors-abort.md` | OpenAI — error mapping + cancel |
| 26 | `26-openai-compatible.md` | OpenAI-compatible adapter |
| 27 | `27-public-api.md` | `__init__.py` + `assemble` + sync wrappers |
| 28 | `28-unit-test-sweep.md` | Coverage backfill |
| 29 | `29-contract-test-infra.md` | Fixture-replay harness |
| 30 | `30-anthropic-contract-tests.md` | Anthropic contract suite |
| 31 | `31-openai-contract-tests.md` | OpenAI contract suite |
| 32 | `32-live-smoke.md` | Live smoke (env-gated) |

## Out of scope

- Google / Mistral / Bedrock / Azure / Codex / Copilot providers
- OAuth (Anthropic third-party closed; not porting)
- TUI / wizard (lives in `py-coding-agent`)
- pydantic in `llm-providers`
- Sync HTTP fallback (sync wrappers use `asyncio.run`)
- CLI shipped from this package
