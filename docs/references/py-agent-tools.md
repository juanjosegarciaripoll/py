# py-agent-tools Reference

## Core modules

- `py_agent_tools.builtin`
- `py_agent_tools.shell_subset`
- `py_agent_tools.shell_parser`
- `py_agent_tools.shell_registry`
- `py_agent_tools.shell_runtime`
- `py_agent_tools.shell_args`

## Public API exports

From `py_agent_tools/__init__.py`:

- Tool executor and policy:
  - `BuiltinToolExecutor`
  - `ToolSandboxPolicy`, `ToolPermissionPolicy`
  - `ToolError`, `ToolPermissionError`
  - `BashExecutionLimits`, `BashResult`
- Shell parser and validation:
  - `parse_shell_command`, `ShellSubsetParser`, `ShlexTokenizer`
  - `validate_shell_program`, `ShellSubsetFeatures`, `ShellLimits`
- Shell registry/runtime:
  - `ShellCommandRegistry`, `ShellCommandContext`, `ShellCommandResult`
  - `ShellExecutionEvent`, `ShellExecutionEventKind`, `emit_shell_event`

## Built-in executor tools

`BuiltinToolExecutor.execute(...)` supports:

- `read`
- `write`
- `edit`
- `bash`
- `find`
- `grep`

## Bash runtime limits

`BashExecutionLimits` defaults:

- `max_execution_seconds = 10.0`
- `max_output_bytes = 262144`
- `max_pipelines = 8`
- `max_commands = 32`

Exit behavior:

- timeout => `124`
- limits exceeded => `125`

## Package docs replaced by this page

This page subsumes package-level README material in `py-agent-tools/README.md`.
