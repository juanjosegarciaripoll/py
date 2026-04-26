# py-agent-tools User Guide

`py-agent-tools` provides reusable tool executors and a safe shell-subset runtime.

## What it solves

- Built-in coding tools: `read`, `write`, `edit`, `bash`, `find`, `grep`
- Path-based sandbox policy (`ToolSandboxPolicy`)
- Permission controls (`read` / `write` / `execute`)
- Bounded shell execution with strict limits

## Builtin tool executor

```python
from pathlib import Path
from py_agent_tools import BuiltinToolExecutor

executor = BuiltinToolExecutor(cwd=Path.cwd())
result = executor.read("README.md")
```

## Safety model

- Restrict filesystem access with `allowed_roots`
- Disable execution when needed (`allow_execute=False`)
- Bound shell behavior using `BashExecutionLimits`
  - timeout => exit code `124`
  - limit violations => exit code `125`

## Recommended examples

- [Build a safe shell runtime with policy limits](../examples/safe-shell-runtime.md)
- [Create and run a custom agent tool](../examples/custom-agent-tool.md)

## Next reading

- [py-agent-tools reference](../references/py-agent-tools.md)
