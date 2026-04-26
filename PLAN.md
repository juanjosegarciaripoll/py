## Plan: Implement Py Agentic Coding Framework

Recreate the Pi agentic framework in Python using standard libraries and minimal dependencies, focusing on llm-providers, py-agent, and py-coding-agent components with flexible sandboxing.

## Status Summary (2026-04-26)

- Completed phases: 2 (llm-providers), 3 (py-agent), 4 (py-coding-agent), 5 (sandboxing), 6 (integration/installation)
- Active next task: Run live provider validation with real Anthropic/OpenAI credentials in a non-sandboxed environment

## Tasks

### Phase 1: Project Setup and Structure

**Status:** Completed

- [x] Set up workspace structure with uv workspaces for llm-providers, py-agent, py-coding-agent subprojects.
- [x] Update `pyproject.toml` with workspace configuration and basic metadata.
- [x] Create initial directory structure and stub `pyproject.toml` files for each component.
- [x] Set up linting and type checking tools (ruff, basedpyright, mypy) in root `pyproject.toml`.

### Phase 2: LLM Providers (`llm-providers`)

**Status:** Completed

- [x] Port core API registry and provider interfaces from `pi-mono/packages/ai`.
- [x] Implement Anthropic provider with streaming support.
- [x] Implement OpenAI provider with streaming support.
- [x] Add OpenAI-compatible provider for local models.
- [x] Implement OAuth handling and API key management.
- [x] Add model registry and generated model definitions.
- [x] Implement optional TUI interface to select providers.
- [x] Make configuration serializable as Python dicts and JSON.
- [x] Implement unified communication schema parity (messages/tool-calls/timestamps/errors).
- [x] Implement full streaming lifecycle parity (start/delta/end + done/error).
- [x] Implement tool-call communication parity (partial JSON, normalization, stable IDs).
- [x] Implement tool-result parity (text/image routing and compatibility).
- [x] Implement reasoning/thinking parity.
- [x] Implement stop-reason/interruption parity.
- [x] Implement cross-provider handoff parity.
- [x] Implement context serialization/replay parity.
- [x] Implement robustness parity (partial JSON cleanup, unicode sanitization, overflow/malformed recovery).
- [x] Implement telemetry parity (usage IDs + extensible cost hooks).
- [x] Implement provider model accessibility checks for interactive config.
- [x] Add comprehensive unit tests for communication semantics and edge cases.

### Phase 3: Agent Framework (`py-agent`)

**Status:** Completed

- [x] Mirror `types.ts` contracts in Python (`AgentMessage`, context/state, tool/result, events, queue/tool modes, hooks).
- [x] Implement low-level loop parity with `agent-loop.ts` (`agent_loop`, `agent_loop_continue`, transforms, key resolver, continue preconditions).
- [x] Implement agent event lifecycle parity (`agent_start/end`, `turn_start/end`, `message_*`, `tool_execution_*`).
- [x] Implement tool execution parity (sequential/parallel, overrides, hooks, streaming updates, terminate semantics).
- [x] Implement steering/follow-up parity (queue modes, drain/clear, turn-loop injection).
- [x] Implement high-level `Agent` class parity (`continue`, abort/wait/reset, subscriptions, streaming/queue state).
- [x] Implement proxy transport parity (`proxy.ts` stream decode/reconstruct, partial JSON, finalization).
- [x] Add parity unit tests matching `packages/agent/test` behaviors.
- [x] Raise test coverage to project target (completed at 96% line coverage).

### Phase 4: Coding Agent CLI (`py-coding-agent`)

**Status:** Completed

- [x] Implement multi-mode execution (interactive, print, JSON, RPC).
- [x] Implement Textual TUI (editor, shortcuts, slash commands).
- [x] Add session management with JSONL persistence and branching.
- [x] Implement compaction with token management and summarization.
- [x] Add extension system with hooks and event-driven architecture.
- [x] Integrate built-in tools (`read`, `write`, `edit`, `bash`, `find`, `grep`) with sandbox policy enforcement.
- [x] Add incremental folder-based skills system (`list_skills`, `list_skill_files`, `load_skill`, `load_skill_file`, activation + namespaced tools).
- [x] Implement TOML settings/config plus CLI overrides.
- [x] Add unit tests for CLI components.

### Phase 5: Sandboxing Implementation

**Status:** Completed

- [x] Define permission system for read/write/execute policies.
- [x] Implement safe bash interpreter as Python-based sh subset parser.
  - [x] Define shell subset and typed AST nodes (commands, args, env assignments, redirections, pipelines).
  - [x] Implement parser stages as composable elements (tokenizer, parser, validator, planner).
  - [x] Add conditional connectors (`&&`, `||`) with short-circuit semantics.
  - [x] Add runtime cancellation/signal propagation execution model.
  - [x] Design extensibility hooks for safe syntax/handler extension.
  - [x] Integrate parser/registry/runtime into `bash` execution with redirection policy checks.
  - [x] Implement reusable command argument parsing infrastructure.
  - [x] Implement parser-level glob expansion with expanded argv dispatch.
  - [x] Implement built-in command handlers: `grep`, `ls`, `dir`, `cd`, `pwd`, `cp`, `mv`, `cat`, `head`, `tail`, `mkdir`.
  - [x] Add execution safety limits (timeouts/output size/pipeline/command bounds) and strict behavior docs.
- [x] Integrate permissions into read, write, and bash tools.
- [x] Add configuration options for permission policies.

### Phase 6: Integration and CLI Installation

**Status:** Completed

- [x] Integrate all three workspace libraries so `py-coding-agent` uses both `py-agent` and `llm-providers`.
- [x] Set up CLI installation as a standalone program.
- [x] Add configuration loading and environment setup for integrated runtime/provider selection.
- [x] Implement system prompt construction with context injection.

## Relevant files

- `pyproject.toml` - Root workspace configuration
- `llm-providers/pyproject.toml` - Provider package setup
- `py-agent/pyproject.toml` - Agent framework setup
- `py-coding-agent/pyproject.toml` - CLI tool setup
- `llm-providers/src/` - Provider implementation
- `py-agent/src/` - Agent framework implementation
- `py-coding-agent/src/` - Coding agent implementation

## Verification Checklist

- [x] Run ruff, basedpyright, and mypy on modified components.
- [x] Run unit tests for modified components through coverage (`coverage run ...`, `coverage report --fail-under=90`).
- [x] Validate CLI installation and baseline interactive mode.
- [x] Validate provider smoke tests (Anthropic/OpenAI).
- [x] Validate sandboxed tool execution paths.
- [x] Validate session persistence and compaction behavior.
- [x] Validate event-stream lifecycle semantics.
- [x] Validate cross-provider handoff/context replay.
- [x] Validate abort/error/overflow and tool-call/tool-result edge cases.
- [x] Validate `py-agent` parity against `pi-mono/packages/agent` loop/queue/tools/proxy scenarios.

Validation notes:
- Anthropic/OpenAI smoke coverage is currently based on deterministic unit smoke tests with mocked HTTP clients.
- Live provider validation remains pending on availability of real API credentials and external network access.

## Decisions

- LLM providers: Anthropic, OpenAI, OpenAI-compatible first.
- Sandboxing: permission-based policies plus safe bash interpreter.
- TUI: Textual for CLI.
- Exclusions: web-ui/pods/mom packages.
- Testing: `unittest` only.

## Further Considerations

- [ ] Clarify target local model servers for OpenAI-compatible provider (for example, Ollama or vLLM).
- [ ] Consider optional Docker sandbox mode beyond permission policies.
