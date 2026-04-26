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

- `py_agent`
- `py_agent.types`
- `py_agent.agent_loop`
- `py_agent.agent`
- `py_agent.proxy`

## Test suite

Run:

```powershell
uv run --no-cache python -m unittest discover -s py-agent/tests -v
```
