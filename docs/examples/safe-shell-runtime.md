# Example: Build a Safe Shell Runtime with Policy Limits

This example uses `py-agent-tools` directly to run bounded shell commands inside a filesystem sandbox.

## 1) Create `safe_shell.py`

```python
from __future__ import annotations

from pathlib import Path

from py_agent_tools import BashExecutionLimits, BuiltinToolExecutor, ToolSandboxPolicy

workspace = Path.cwd()
policy = ToolSandboxPolicy(
    allowed_roots=(workspace,),
    allow_read=True,
    allow_write=True,
    allow_execute=True,
)
limits = BashExecutionLimits(
    max_execution_seconds=5.0,
    max_output_bytes=65536,
    max_pipelines=4,
    max_commands=16,
)
executor = BuiltinToolExecutor(cwd=workspace, policy=policy, bash_limits=limits)

# Safe file write/read via built-in tools
executor.write("demo.txt", "alpha\nbeta\ngamma\n")
print(executor.read("demo.txt"))

# Bounded shell-subset command
result = executor.bash("cat demo.txt | grep beta")
print(result.exit_code)
print(result.stdout)
print(result.stderr)
```

## 2) Security posture

- `allowed_roots` prevents path escape from your selected workspace.
- Permission gates enforce read/write/execute independently.
- Runtime limits prevent unbounded output, command fan-out, and long execution.

## 3) Failure behavior

- Timeout returns `exit_code = 124`.
- Limit violations return `exit_code = 125`.

## Related docs

- [py-agent-tools guide](../libraries/py-agent-tools.md)
- [py-agent-tools reference](../references/py-agent-tools.md)
