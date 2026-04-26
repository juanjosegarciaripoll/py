# Py Agentic Coding

Py Agentic Coding is a Python 3.13 workspace for building LLM-powered agents with strong tool sandboxing.

This site is the user-facing documentation for:

- `llm-providers`: provider clients and streaming message types
- `py-agent`: stateful agent loop and tool orchestration
- `py-agent-tools`: reusable built-in tools and safe shell-subset runtime

## Start here

1. [Getting Started](./getting-started.md)
2. Library guides:
   - [llm-providers](./libraries/llm-providers.md)
   - [py-agent](./libraries/py-agent.md)
   - [py-agent-tools](./libraries/py-agent-tools.md)
3. Examples:
   - [Summarize a document with OpenAI](./examples/summarize-document.md)
   - [Create and run a custom agent tool](./examples/custom-agent-tool.md)
   - [Build a safe shell runtime with policy limits](./examples/safe-shell-runtime.md)
4. API references:
   - [llm-providers reference](./references/llm-providers.md)
   - [py-agent reference](./references/py-agent.md)
   - [py-agent-tools reference](./references/py-agent-tools.md)

## Who this is for

This documentation is for users integrating these libraries into applications and services. It focuses on practical usage, safe defaults, and integration patterns.

## GitHub Pages

Publish this documentation from the repository `docs/` folder:

1. Go to repository `Settings` -> `Pages`
2. Under `Build and deployment`, choose `Deploy from a branch`
3. Select your main branch and folder `/docs`
4. Save

GitHub will rebuild the site when docs change in the repository.
