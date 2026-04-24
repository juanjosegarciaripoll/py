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
9. Create unit tests for providers.

### Phase 3: Agent Framework (py-agent)

**Status:** Not Started

1. Define message types and AgentMessage hierarchy with extensible custom messages.
2. Implement agent loop with steering and follow-up message handling.
3. Add tool execution pipeline with parallel execution support.
4. Implement event system for streaming updates and UI notifications.
5. Create Agent class with state management and lifecycle methods.
6. Add proxy pattern for server-side routing if needed.
7. Create unit tests for agent logic.

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

**Decisions**

- LLM providers: Start with Anthropic, OpenAI, OpenAI-compatible; extensible for others.
- Sandboxing: Permission-based policies on tools, safe bash interpreter.
- TUI: Use Textual library for Python CLI interface.
- Exclusions: web-ui, pods, mom packages not implemented.
- Testing: Python unittests only, no pytest.

**Further Considerations**

1. For local model support via OpenAI-compatible, clarify which local servers to target (e.g., Ollama, vLLM).
2. Consider adding Docker-based sandboxing as an optional advanced mode beyond permission policies.
