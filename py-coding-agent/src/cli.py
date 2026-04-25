"""CLI entry points and execution modes for py-coding-agent."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TextIO, cast

from .session import SessionStore

type ExecutionMode = Literal["interactive", "print", "json", "rpc"]


def _as_str_object_dict(value: object) -> dict[str, object] | None:
    """Return a `dict[str, object]` when keys are valid strings."""
    if not isinstance(value, dict):
        return None
    raw_dict = cast("dict[object, object]", value)
    normalized: dict[str, object] = {}
    for key, item in raw_dict.items():
        if not isinstance(key, str):
            return None
        normalized[key] = item
    return normalized


@dataclass(slots=True)
class RunConfig:
    """Normalized CLI configuration."""

    mode: ExecutionMode
    prompt: str
    session_file: str | None
    branch: str


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(prog="py-coding-agent")
    parser.add_argument(
        "--mode",
        choices=["interactive", "print", "json", "rpc"],
        default="interactive",
        help="Execution mode",
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        default="",
        help="Prompt to process",
    )
    parser.add_argument(
        "--session-file",
        default=None,
        help="Optional JSONL session file path",
    )
    parser.add_argument(
        "--branch",
        default="main",
        help="Session branch name",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> RunConfig:
    """Parse command-line arguments into a typed RunConfig."""
    namespace = build_parser().parse_args(argv)
    mode: ExecutionMode = namespace.mode
    prompt: str = namespace.prompt
    session_file = namespace.session_file
    branch: str = namespace.branch
    return RunConfig(
        mode=mode,
        prompt=prompt,
        session_file=session_file,
        branch=branch,
    )


class CodingAgentApp:
    """Small execution harness with four user-facing modes."""

    def respond(self, prompt: str) -> str:
        """Produce a deterministic response for the current prompt."""
        text = prompt.strip()
        if text:
            return f"Echo: {text}"
        return "Echo: (empty prompt)"

    def run(
        self,
        config: RunConfig,
        *,
        stdin: TextIO,
        stdout: TextIO,
    ) -> int:
        """Run one mode and return process exit code."""
        store = self._build_store(config)
        match config.mode:
            case "interactive":
                return self._run_interactive(stdout=stdout, stdin=stdin, store=store)
            case "print":
                return self._run_print(prompt=config.prompt, stdout=stdout, store=store)
            case "json":
                return self._run_json(prompt=config.prompt, stdout=stdout, store=store)
            case "rpc":
                return self._run_rpc(stdout=stdout, stdin=stdin, store=store)

    def _build_store(self, config: RunConfig) -> SessionStore | None:
        if config.session_file is None:
            return None
        return SessionStore(path=Path(config.session_file), branch=config.branch)

    def _run_interactive(
        self,
        *,
        stdout: TextIO,
        stdin: TextIO,
        store: SessionStore | None,
    ) -> int:
        stdout.write("Interactive mode. Type 'exit' to quit.\n")
        while True:
            stdout.write("> ")
            line = stdin.readline()
            if line == "":
                return 0
            prompt = line.strip()
            if prompt in {"exit", "quit"}:
                return 0
            response = self.respond(prompt)
            stdout.write(f"{response}\n")
            self._persist_interaction(
                store=store,
                mode="interactive",
                prompt=prompt,
                response=response,
            )

    def _run_print(
        self,
        *,
        prompt: str,
        stdout: TextIO,
        store: SessionStore | None,
    ) -> int:
        response = self.respond(prompt)
        stdout.write(f"{response}\n")
        self._persist_interaction(
            store=store,
            mode="print",
            prompt=prompt,
            response=response,
        )
        return 0

    def _run_json(
        self,
        *,
        prompt: str,
        stdout: TextIO,
        store: SessionStore | None,
    ) -> int:
        response = self.respond(prompt)
        payload = {
            "mode": "json",
            "prompt": prompt,
            "response": response,
        }
        stdout.write(json.dumps(payload) + "\n")
        self._persist_interaction(
            store=store,
            mode="json",
            prompt=prompt,
            response=response,
        )
        return 0

    def _run_rpc(
        self,
        *,
        stdout: TextIO,
        stdin: TextIO,
        store: SessionStore | None,
    ) -> int:
        for line in stdin:
            text = line.strip()
            if not text:
                continue
            try:
                parsed: object = json.loads(text)
            except json.JSONDecodeError:
                stdout.write('{"error":"invalid_json"}\n')
                continue
            request = _as_str_object_dict(parsed)
            if request is None:
                stdout.write('{"error":"invalid_request"}\n')
                continue
            method = request.get("method")
            if method == "shutdown":
                stdout.write('{"ok":true}\n')
                return 0
            if method != "prompt":
                stdout.write('{"error":"method_not_found"}\n')
                continue
            params = _as_str_object_dict(request.get("params"))
            if params is None:
                stdout.write('{"error":"invalid_params"}\n')
                continue
            prompt_value = params.get("prompt", "")
            if not isinstance(prompt_value, str):
                stdout.write('{"error":"invalid_params"}\n')
                continue
            request_id = request.get("id")
            response_text = self.respond(prompt_value)
            response = {
                "id": request_id,
                "result": {"response": response_text},
            }
            stdout.write(json.dumps(response) + "\n")
            self._persist_interaction(
                store=store,
                mode="rpc",
                prompt=prompt_value,
                response=response_text,
            )
        return 0

    def _persist_interaction(
        self,
        *,
        store: SessionStore | None,
        mode: str,
        prompt: str,
        response: str,
    ) -> None:
        if store is None:
            return
        store.append_interaction(mode=mode, prompt=prompt, response=response)


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the `py-coding-agent` command."""
    app = CodingAgentApp()
    config = parse_args(argv)

    return app.run(config, stdin=sys.stdin, stdout=sys.stdout)
