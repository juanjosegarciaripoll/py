# Py agentic coding

This project aims to recreate the Pi agentic framework using standard Python libraries and minimal dependencies, with a flexible and solid sandboxing for the provided LLM tools.

## Components

- llm-providers: A library to handle connections to LLM APIs. Is the equivalent to pi-mono/packages/ai
- py-agent: Agentic framework to invoke LLMs with context, toolings, skills, etc.
- py-coding-agent: The CLI coding agent, with a TUI and a simple interface, similar to the "pi" harness (equivalent to the pi-mono/packages/coding-agent software)

## Project structure

- The software is fully developed in Python 3.13
- Minimal dependencies, with a focus on standard libraries
- Pydantic is allowed when it clearly simplifies data parsing, validation, and serialization
- Libraries and software handled using "uv"
- Python programs are invoked using "uv run"
- Unit testing with Python unittests (not pytest)
- Unit tests are run through coverage.py to measure coverage
- Project structured as workspaces
- CLI tool installable as standalone program
- Configuration based on TOML files

## Engineering constraints

- Python code with type declarations
- Strict type checking
- Each development phase that modifies python files is checked using ruff, basedpyright and mypy.
- Code autoformatting and linting problems fixed with ruff.
- Type checking problems are solved, not silenced
- Functions, classes and methods adequately documented
- Use --no-cache when calling uv
- Compact code, with minimal redundancies
- Each phase involves creating the tests for all components, aiming for very high coverage, with a hard minimum gate of 90%.
- Test runs for modified components use coverage.py, for example `uv run --no-cache coverage run -m unittest discover -s <component>/tests -v` followed by `uv run --no-cache coverage report --fail-under=90`.
- A phase is not considered complete untill all unit tests pass under coverage, the coverage report passes the configured threshold, all type checkers pass and all linting errors are corrected.
- You are not allowed to use --unsafe-fixes in ruff.
- Avoid using cast() when possible.
- Tests should focus on public APIs for libraries, avoiding private methods.
- Avoid long chains of ifs. Look for alternatives, such as match/case statements or dispatch based on dictionaries.
