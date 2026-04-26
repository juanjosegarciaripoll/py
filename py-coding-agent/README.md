# py-coding-agent

`py-coding-agent` is the CLI layer of this workspace.
It now integrates all three workspace libraries:

- `py-coding-agent` (CLI/runtime)
- `py-agent` (agent loop/orchestration)
- `llm-providers` (provider abstraction/streaming)

Current implementation status:

- Multi-mode execution scaffold
- Modes: `interactive`, `print`, `json`, `rpc`, `tui`
- Optional JSONL session persistence with branch support
- Optional TOML config defaults (`[agent]` section)
- Sandbox permission policy config via `[agent.permissions]` (or legacy `[agent.tools]`)
- Integrated runtime config via `[agent.runtime]` (`echo` fallback or `agent` backend)
- Initial extension hooks via event bus (`interaction_complete`)
- Unit tests for parsing and mode behavior

Documentation:

- Configuration schema: `docs/configuration.md`
