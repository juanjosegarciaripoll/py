# 29 — Contract-test fixture-replay infrastructure

## Goal

Build the harness that replays HTTP request/response pairs captured from `pi-mono/packages/ai/test/` against the Python providers and compares the resulting event sequence to a Python-side golden file.

This is the engine; per-provider suites (tasks 30, 31) supply the fixtures.

## Refs

- `00-architecture.md` §14
- `pi-mono/packages/ai/test/` (TS fixtures — directory structure, file shapes)
- `httpx.MockTransport` docs

## Concept

A **contract fixture** is a directory containing:

- `request.json` — expected outbound HTTP request (method, url, headers subset, body)
- `response.txt` (SSE) or `response.json` (non-streaming) — canned response body
- `golden_events.json` — Python-side expected event sequence
- `input.json` — `{"context": {...}, "stream_kwargs": {...}, "model": "..."}`

Harness:

1. Reads the fixture.
2. Configures `httpx.MockTransport` to return `response.txt` for any request matching `request.json`'s url+method.
3. Drives the Python provider with `input.json`.
4. Collects the resulting events.
5. Diffs against `golden_events.json`.

## Files

```
tests/contract/
  __init__.py
  harness.py             # replay engine
  helpers.py             # serialization helpers
  fixtures/              # populated by tasks 30, 31
    __init__.py
    README.md            # how to add a fixture
```

## `harness.py`

```python
"""Contract-test harness: replay HTTP fixtures, diff event streams."""
from __future__ import annotations
import asyncio
import json
import unittest
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Callable

import httpx

from llm_providers.events import Event
from llm_providers.models import ModelInfo
from llm_providers.provider import Provider
from llm_providers.types import Context


def load_fixture(path: Path) -> dict[str, Any]:
    """Load a fixture directory into a dict.

    Expected files:
      input.json       → {"context": {...}, "stream_kwargs": {...}, "model": "..."}
      request.json     → {"method": "POST", "url": "...", "body_match": {...}}
      response.txt     → SSE body (or response.json for non-streaming, currently unused)
      golden_events.json → list of event dicts (one per emitted event)
    """
    return {
        "input": json.loads((path / "input.json").read_text()),
        "request": json.loads((path / "request.json").read_text()),
        "response_body": (path / "response.txt").read_text(),
        "golden_events": json.loads((path / "golden_events.json").read_text()),
    }


def make_mock_transport(
    response_body: str,
    *,
    status_code: int = 200,
    content_type: str = "text/event-stream",
    captured_request: list[httpx.Request] | None = None,
) -> httpx.MockTransport:
    """Build a MockTransport returning the canned response and capturing requests."""

    def handler(request: httpx.Request) -> httpx.Response:
        if captured_request is not None:
            captured_request.append(request)
        return httpx.Response(
            status_code,
            content=response_body.encode("utf-8"),
            headers={"content-type": content_type},
        )

    return httpx.MockTransport(handler)


def event_to_dict(event: Event) -> dict[str, Any]:
    """Serialize an event dataclass to a comparable dict.

    Strips `Error.error` (an exception) down to message+type for diff stability.
    """
    if not is_dataclass(event):
        raise TypeError(f"not a dataclass: {event!r}")
    d = asdict(event)
    err = d.get("error")
    if isinstance(err, Exception):
        d["error"] = {"type": type(err).__name__, "message": str(err)}
    return d


async def collect_events(
    provider: Provider, model: ModelInfo, context: Context, **kwargs: Any
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    async for ev in provider.stream(model, context, **kwargs):
        out.append(event_to_dict(ev))
    return out


def assert_event_sequence(actual: list[dict], expected: list[dict]) -> None:
    """Diff two event sequences; raise AssertionError with a clear message."""
    if actual == expected:
        return
    for i, (a, e) in enumerate(zip(actual, expected)):
        if a != e:
            raise AssertionError(
                f"event {i} mismatch:\n  actual:   {a!r}\n  expected: {e!r}"
            )
    if len(actual) != len(expected):
        raise AssertionError(
            f"event count mismatch: actual={len(actual)} expected={len(expected)}"
            f"\nextra actual: {actual[len(expected):]}"
            f"\nmissing expected: {expected[len(actual):]}"
        )


def assert_request_matches(captured: httpx.Request, spec: dict[str, Any]) -> None:
    """Check captured outbound request matches the spec.

    Spec fields:
      method (str)
      url    (str — exact)
      body_match (dict — every key must be present in the parsed body
                  with matching value; extra keys allowed)
    """
    if captured.method != spec["method"]:
        raise AssertionError(f"method mismatch: {captured.method} != {spec['method']}")
    if captured.url != httpx.URL(spec["url"]):
        raise AssertionError(f"url mismatch: {captured.url} != {spec['url']}")
    if "body_match" in spec:
        body = json.loads(captured.content) if captured.content else {}
        for k, v in spec["body_match"].items():
            if body.get(k) != v:
                raise AssertionError(
                    f"body field {k!r} mismatch: {body.get(k)!r} != {v!r}"
                )
```

## `helpers.py`

```python
"""Helpers for fixture authoring."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any


def write_fixture(
    target: Path,
    *,
    input: dict[str, Any],
    request: dict[str, Any],
    response_body: str,
    golden_events: list[dict[str, Any]],
) -> None:
    target.mkdir(parents=True, exist_ok=True)
    (target / "input.json").write_text(json.dumps(input, indent=2))
    (target / "request.json").write_text(json.dumps(request, indent=2))
    (target / "response.txt").write_text(response_body)
    (target / "golden_events.json").write_text(json.dumps(golden_events, indent=2))
```

## Base test class

`unittest.IsolatedAsyncioTestCase` subclass for per-fixture tests:

```python
class ContractTestCase(unittest.IsolatedAsyncioTestCase):
    """Base for per-fixture tests."""

    fixture_path: Path  # set in subclass
    provider_factory: Callable[[httpx.AsyncClient], Provider]  # set in subclass
    model_factory: Callable[[], ModelInfo]  # set in subclass

    async def run_fixture(self, fixture_dir: Path) -> None:
        fx = load_fixture(fixture_dir)
        captured: list[httpx.Request] = []
        transport = make_mock_transport(
            fx["response_body"], captured_request=captured
        )
        async with httpx.AsyncClient(transport=transport) as client:
            provider = self.provider_factory(client)
            try:
                ctx = self._context_from_dict(fx["input"]["context"])
                events = await collect_events(
                    provider,
                    self.model_factory(),
                    ctx,
                    **fx["input"].get("stream_kwargs", {}),
                )
            finally:
                await provider.aclose()
        assert_request_matches(captured[0], fx["request"])
        assert_event_sequence(events, fx["golden_events"])

    def _context_from_dict(self, d: dict) -> Context:
        # JSON → Context; provider-specific subclasses can override
        ...  # implementer fills in basic deserialization
```

## `fixtures/README.md`

```markdown
# Contract-test fixtures

Each subdirectory is a single replay test. Files:

- `input.json` — Python-side input: `{"context": {...}, "stream_kwargs": {...}}`
- `request.json` — expected outbound HTTP: `{"method": "POST", "url": "...", "body_match": {...}}`
- `response.txt` — canned response body (SSE).
- `golden_events.json` — expected Python event sequence.

To add a fixture:

1. Capture an HTTP pair from the TS pi-ai test suite, OR run a real provider
   call against `httpx`'s recording transport.
2. Compose the input that should produce that request.
3. Run the harness with `python -m tests.contract.harness <dir>` to see what
   events come out, then save them as `golden_events.json`.
4. Hand-verify the golden against the architecture event protocol (§5).
```

## Acceptance

- [ ] `harness.py` exports `load_fixture`, `make_mock_transport`, `event_to_dict`, `collect_events`, `assert_event_sequence`, `assert_request_matches`, `ContractTestCase`.
- [ ] `helpers.py` exports `write_fixture`.
- [ ] `fixtures/README.md` documents the layout.
- [ ] Smoke test (`tests/contract/test_harness_smoke.py`): in-memory fixture (no disk I/O) through the harness against a stub `Provider`, passing diff. Includes a deliberate-mismatch case verifying the diff reports cleanly.
- [ ] `basedpyright` clean.

## Notes

- Harness uses `httpx.MockTransport` injected via `transport=` on `AsyncClient`. Provider must accept an externally-supplied client (already does — task 14).
- Fixture format JSON for input/request/golden so PRs can diff and edit them. Response body plain text (SSE is line-oriented; JSON-quoting is annoying).
- Avoid timestamps in golden events. Python types use `timestamp_ms` defaulting to 0; events don't carry timestamps. Re-verify if a future task adds wall-clock fields.
