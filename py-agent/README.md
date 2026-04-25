# py-agent

Stateful agent runtime for Python, modeled after `pi-mono/packages/agent`.

## What it provides

- Low-level loop APIs:
  - `agent_loop(...)`
  - `agent_loop_continue(...)`
  - `run_agent_loop(...)`
  - `run_agent_loop_continue(...)`
- High-level stateful wrapper:
  - `Agent`
- Proxy stream reconstruction helpers:
  - `stream_proxy_from_events(...)`
- Typed contracts for:
  - messages, tool calls/results, events, hooks, and agent state

## Public modules

- [src/__init__.py](/c:/Users/juanj/src/py/py-agent/src/__init__.py)
- [src/types.py](/c:/Users/juanj/src/py/py-agent/src/types.py)
- [src/agent_loop.py](/c:/Users/juanj/src/py/py-agent/src/agent_loop.py)
- [src/agent.py](/c:/Users/juanj/src/py/py-agent/src/agent.py)
- [src/proxy.py](/c:/Users/juanj/src/py/py-agent/src/proxy.py)

## Test suite

Run:

```powershell
uv run --no-cache python -m unittest discover -s py-agent/tests -v
```
