# Getting Started

## Prerequisites

- Python 3.13
- `uv` installed
- API keys for provider-backed examples (`OPENAI_API_KEY` and/or `ANTHROPIC_API_KEY`)

## Workspace setup

From repository root:

```bash
uv sync --no-cache
```

## Install package dependencies in editable mode (optional)

For local app development, install only the package you are using:

```bash
uv pip install -e llm-providers
uv pip install -e py-agent
uv pip install -e py-agent-tools
```

## Package quick links

- [llm-providers guide](./libraries/llm-providers.md)
- [py-agent guide](./libraries/py-agent.md)
- [py-agent-tools guide](./libraries/py-agent-tools.md)

## Example-driven path

1. Start with [Summarize a document](./examples/summarize-document.md) to test provider connectivity.
2. Continue with [Create and run a custom agent tool](./examples/custom-agent-tool.md) to build a complete tool-call loop.
3. Add [safe shell runtime controls](./examples/safe-shell-runtime.md) for bounded execution and path policy.
