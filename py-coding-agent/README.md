# py-coding-agent

`py-coding-agent` is the CLI layer of this workspace.

Current implementation status:

- Multi-mode execution scaffold
- Modes: `interactive`, `print`, `json`, `rpc`, `tui`
- Optional JSONL session persistence with branch support
- Optional TOML config defaults (`[agent]` section)
- Sandbox permission policy config via `[agent.permissions]` (or legacy `[agent.tools]`)
- Initial extension hooks via event bus (`interaction_complete`)
- Unit tests for parsing and mode behavior

Documentation:

- Configuration schema: `docs/configuration.md`
