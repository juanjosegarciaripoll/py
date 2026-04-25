## Plan: Implement Py Agentic Coding Framework

Recreate the Pi agentic framework in Python using standard libraries and minimal dependencies, focusing on llm-providers, py-agent, and py-coding-agent components with flexible sandboxing.

**Steps**

### Phase 1: Project Setup and Structure

**Status:** In progress

1. Set up workspace structure with uv workspaces for llm-providers, py-agent, py-coding-agent subprojects.
2. Update pyproject.toml with workspace configuration and basic metadata.
3. Create initial directory structure and stub pyproject.toml files for each component.
4. Set up linting and type checking tools (ruff, basedpyright, mypy) in root pyproject.toml.

### Phase 2: LLM Providers (llm-providers)

**Status:** Completed

1. Port core API registry and provider interfaces from pi-mono/packages/ai.
2. Implement Anthropic provider with streaming support.
3. Implement OpenAI provider with streaming support.
4. Add OpenAI-compatible provider for local models.
5. Implement OAuth handling and API key management.
6. Add model registry and generated model definitions.
7. Implement an optional TUI interface to select providers.
8. Configuration serializable as Python dicts and JSON.
9. Define and implement unified communication message schema parity:
   assistant/user/tool-result message blocks, tool-call identifiers, timestamps, and error payloads.
10. Implement full streaming event lifecycle parity:
    start/delta/end events for text, thinking, and tool calls, plus done/error terminal events.
11. Implement tool-call communication behavior parity:
    partial JSON argument streaming, end-of-tool-call normalization, and tool-call ID consistency.
12. Implement tool-result communication parity:
    text and image tool-result content routing, provider-specific conversion rules, and compatibility handling.
13. Implement reasoning/thinking communication parity:
    unified reasoning interface and provider-specific reasoning/thinking options and replay behavior.
14. Implement stop-reason and interruption parity:
    stop/length/tool-use/error/aborted handling and continuation-after-abort semantics.
15. Implement cross-provider handoff communication parity:
    transformation of assistant messages (including thinking blocks) between provider formats.
16. Implement context serialization and replay parity:
    stable JSON serialization/deserialization of full communication context.
17. Implement communication robustness parity:
    partial JSON cleanup, unicode sanitization, overflow detection, and malformed stream recovery.
18. Implement communication telemetry parity:
    token usage and response identifiers across providers, with extensible cost accounting hooks.
19. Implement provider-level model accessibility checks used by interactive configuration flows.
20. Create comprehensive unit tests for communication semantics and edge cases.

### Phase 3: Agent Framework (py-agent)

**Status:** In progress

1. Mirror `pi-mono/packages/agent/src/types.ts` contracts in Python:
   `AgentMessage` abstraction, agent context/state, tool/result types, event union, queue modes, tool execution modes, and hook context/result types.
2. Implement low-level loop parity with `agent-loop.ts`:
   `agent_loop()` and `agent_loop_continue()` behavior, `convert_to_llm` boundary, optional `transform_context`, dynamic API key resolver, and strict continue preconditions.
3. Implement agent event lifecycle parity:
   `agent_start/end`, `turn_start/end`, `message_start/update/end`, `tool_execution_start/update/end`, including ordering guarantees and terminal error/aborted handling.
4. Implement tool execution parity:
   sequential and parallel modes, per-tool mode override, preflight argument preparation/validation, `before_tool_call` blocking, `after_tool_call` override semantics, streaming tool updates, and batch `terminate` behavior.
5. Implement steering/follow-up parity:
   one-at-a-time vs all queue modes, queue drain/clear behavior, and turn-loop injection semantics matching `runLoop`.
6. Implement high-level `Agent` class parity with `agent.ts`:
   stateful wrapper, prompt normalization (text/image/message), `continue()`, abort/wait/reset, subscription semantics (await listeners in order), runtime streaming state, and queue APIs.
7. Implement proxy transport parity with `proxy.ts`:
   proxy stream function, proxy event decoding/reconstruction, partial tool-call JSON handling, and done/error finalization into assistant messages.
8. Implement unit test parity against `packages/agent/test` behavior:
   event order, continue edge cases, queue semantics, tool execution ordering in parallel/sequential, hook behavior, termination rules, and proxy stream parsing.
9. Raise py-agent test coverage toward the project target and document any justified exclusions if 100% line coverage is not practical.

### Phase 4: Coding Agent CLI (py-coding-agent)

**Status:** Not Started

1. Implement multi-mode execution (interactive, print, JSON, RPC).
2. Set up Textual-based TUI with editor, keyboard shortcuts, and slash commands.
3. Add session management with JSONL persistence and branching.
4. Implement compaction system with token management and summarization.
5. Add extension system with hooks and event-driven architecture.
6. Integrate built-in tools (read, write, edit, bash, find, grep) with sandboxing policies.
7. Add skills system with Markdown-based definitions.
8. Implement settings and configuration with TOML files.
9. Create unit tests for CLI components.

### Phase 5: Sandboxing Implementation

**Status:** Not Started

1. Define permission system for read/write/execute policies.
2. Implement safe bash interpreter as Python-based sh subset parser.
3. Integrate permissions into read, write, and bash tools.
4. Add configuration options for permission policies.

### Phase 6: Integration and CLI Installation

1. Integrate components: py-coding-agent uses py-agent and llm-providers.
2. Set up CLI tool installation as standalone program.
3. Add configuration loading and environment setup.
4. Implement system prompt construction with context injection.

**Relevant files**

- `pyproject.toml` — Root workspace configuration
- `llm-providers/pyproject.toml` — Provider package setup
- `py-agent/pyproject.toml` — Agent framework setup
- `py-coding-agent/pyproject.toml` — CLI tool setup
- `llm-providers/src/` — Ported provider code from pi-mono/packages/ai/src/
- `py-agent/src/` — Ported agent code from pi-mono/packages/agent/src/
- `py-coding-agent/src/` — Ported coding agent code from pi-mono/packages/coding-agent/src/

**Verification**

1. Run ruff, basedpyright, mypy on each component after implementation to ensure type safety.
2. Execute unit tests with python -m unittest for each package.
3. Test CLI installation and basic interactive mode functionality.
4. Verify LLM provider connections with smoke tests for Anthropic and OpenAI.
5. Test tool execution with sandboxing policies enabled.
6. Validate session persistence and compaction with sample sessions.
7. Validate event-stream compatibility against expected communication lifecycle semantics.
8. Validate cross-provider handoff and context replay behavior with mixed-provider conversations.
9. Validate abort/error/overflow communication paths and tool-call/tool-result edge cases.
10. Validate `py-agent` behavior against `pi-mono/packages/agent` reference scenarios (loop, queues, tools, proxy) with explicit parity tests.

**Decisions**

- LLM providers: Start with Anthropic, OpenAI, OpenAI-compatible; extensible for others.
- Provider scope remains limited to current providers for now; parity work focuses on communication behavior.
- Sandboxing: Permission-based policies on tools, safe bash interpreter.
- TUI: Use Textual library for Python CLI interface.
- Exclusions: web-ui, pods, mom packages not implemented.
- Testing: Python unittests only, no pytest.

**Further Considerations**

1. For local model support via OpenAI-compatible, clarify which local servers to target (e.g., Ollama, vLLM).
2. Consider adding Docker-based sandboxing as an optional advanced mode beyond permission policies.
