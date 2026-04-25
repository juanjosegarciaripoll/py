"""CLI entry points and execution modes for py-coding-agent."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TextIO, cast

from .compaction import CompactionSettings
from .config import AppConfig, load_config
from .extensions import AppEvent, EventBus, EventListener
from .session import CompactionRecord, SessionStore, timestamp_ms
from .tools import (
    BashResult,
    BuiltinToolExecutor,
    GrepMatch,
    ToolError,
    ToolSandboxPolicy,
)
from .tui import has_textual_dependency, launch_tui_mode

if TYPE_CHECKING:
    from collections.abc import Callable

type ExecutionMode = Literal["interactive", "print", "json", "rpc", "tui"]


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
    config_file: str | None
    context_window_tokens: int = 272_000
    compaction_enabled: bool = True
    compaction_reserve_tokens: int = 16_384
    compaction_keep_recent_tokens: int = 20_000
    tool_allow_read: bool = True
    tool_allow_write: bool = True
    tool_allow_execute: bool = True
    tool_allowed_roots: tuple[str, ...] = ()
    skills_root: str = "skills"


@dataclass(slots=True)
class _InteractionPayload:
    mode: str
    prompt: str
    response: str


@dataclass(slots=True)
class _PersistenceContext:
    branch: str
    session_file: str | None
    context_window_tokens: int
    compaction_settings: CompactionSettings


def build_parser(*, defaults: AppConfig | None = None) -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    config_defaults = defaults or AppConfig()
    parser = argparse.ArgumentParser(prog="py-coding-agent")
    parser.add_argument(
        "--config",
        default=None,
        help="Optional TOML config file path",
    )
    parser.add_argument(
        "--mode",
        choices=["interactive", "print", "json", "rpc", "tui"],
        default=config_defaults.mode,
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
        default=config_defaults.session_file,
        help="Optional JSONL session file path",
    )
    parser.add_argument(
        "--branch",
        default=config_defaults.branch,
        help="Session branch name",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> RunConfig:
    """Parse command-line arguments into a typed RunConfig."""
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--config", default=None)
    pre_namespace, _unknown = pre_parser.parse_known_args(argv)
    config_path = (
        None
        if pre_namespace.config is None
        else Path(str(pre_namespace.config))
    )
    defaults = load_config(config_path)
    namespace = build_parser(defaults=defaults).parse_args(argv)
    mode: ExecutionMode = namespace.mode
    prompt: str = namespace.prompt
    session_file = namespace.session_file
    branch: str = namespace.branch
    config_file = namespace.config
    return RunConfig(
        mode=mode,
        prompt=prompt,
        session_file=session_file,
        branch=branch,
        config_file=config_file,
        context_window_tokens=defaults.context_window_tokens,
        compaction_enabled=defaults.compaction_enabled,
        compaction_reserve_tokens=defaults.compaction_reserve_tokens,
        compaction_keep_recent_tokens=defaults.compaction_keep_recent_tokens,
        tool_allow_read=defaults.tool_allow_read,
        tool_allow_write=defaults.tool_allow_write,
        tool_allow_execute=defaults.tool_allow_execute,
        tool_allowed_roots=defaults.tool_allowed_roots,
        skills_root=defaults.skills_root,
    )


class CodingAgentApp:
    """Small execution harness with four user-facing modes."""

    def __init__(self, *, event_bus: EventBus | None = None) -> None:
        self._event_bus = event_bus or EventBus()
        self._tool_executor = BuiltinToolExecutor(cwd=Path.cwd())

    def subscribe(self, listener: EventListener) -> Callable[[], None]:
        """Subscribe to app events and return an unsubscribe callback."""
        return self._event_bus.subscribe(listener)

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
        self._configure_tools(config)
        store = self._build_store(config)
        compaction_settings = CompactionSettings(
            enabled=config.compaction_enabled,
            reserve_tokens=config.compaction_reserve_tokens,
            keep_recent_tokens=config.compaction_keep_recent_tokens,
        )
        persistence = _PersistenceContext(
            branch=config.branch,
            session_file=config.session_file,
            context_window_tokens=config.context_window_tokens,
            compaction_settings=compaction_settings,
        )
        match config.mode:
            case "interactive":
                return self._run_interactive(
                    stdout=stdout,
                    stdin=stdin,
                    store=store,
                    persistence=persistence,
                )
            case "print":
                return self._run_print(
                    prompt=config.prompt,
                    stdout=stdout,
                    store=store,
                    persistence=persistence,
                )
            case "json":
                return self._run_json(
                    prompt=config.prompt,
                    stdout=stdout,
                    store=store,
                    persistence=persistence,
                )
            case "rpc":
                return self._run_rpc(
                    stdout=stdout,
                    stdin=stdin,
                    store=store,
                    persistence=persistence,
                )
            case "tui":
                return self._run_tui(
                    store=store,
                    persistence=persistence,
                    stdout=stdout,
                )

    def _configure_tools(self, config: RunConfig) -> None:
        if config.tool_allowed_roots:
            resolved_roots = tuple(
                _resolve_root_path(raw_path)
                for raw_path in config.tool_allowed_roots
            )
            policy = ToolSandboxPolicy(
                allowed_roots=resolved_roots,
                allow_read=config.tool_allow_read,
                allow_write=config.tool_allow_write,
                allow_execute=config.tool_allow_execute,
            )
            self._tool_executor = BuiltinToolExecutor(cwd=Path.cwd(), policy=policy)
            return
        default_policy = ToolSandboxPolicy.from_cwd(Path.cwd())
        policy = ToolSandboxPolicy(
            allowed_roots=default_policy.allowed_roots,
            allow_read=config.tool_allow_read,
            allow_write=config.tool_allow_write,
            allow_execute=config.tool_allow_execute,
        )
        self._tool_executor = BuiltinToolExecutor(cwd=Path.cwd(), policy=policy)

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
        persistence: _PersistenceContext,
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
                persistence=persistence,
                payload=_InteractionPayload(
                    mode="interactive",
                    prompt=prompt,
                    response=response,
                ),
            )

    def _run_print(
        self,
        *,
        prompt: str,
        stdout: TextIO,
        store: SessionStore | None,
        persistence: _PersistenceContext,
    ) -> int:
        response = self.respond(prompt)
        stdout.write(f"{response}\n")
        self._persist_interaction(
            store=store,
            persistence=persistence,
            payload=_InteractionPayload(
                mode="print",
                prompt=prompt,
                response=response,
            ),
        )
        return 0

    def _run_json(
        self,
        *,
        prompt: str,
        stdout: TextIO,
        store: SessionStore | None,
        persistence: _PersistenceContext,
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
            persistence=persistence,
            payload=_InteractionPayload(
                mode="json",
                prompt=prompt,
                response=response,
            ),
        )
        return 0

    def _run_rpc(
        self,
        *,
        stdout: TextIO,
        stdin: TextIO,
        store: SessionStore | None,
        persistence: _PersistenceContext,
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
            if method == "tool":
                response = self._rpc_tool_response(request=request)
                stdout.write(json.dumps(response) + "\n")
                continue
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
                persistence=persistence,
                payload=_InteractionPayload(
                    mode="rpc",
                    prompt=prompt_value,
                    response=response_text,
                ),
            )
        return 0

    def _rpc_tool_response(self, *, request: dict[str, object]) -> dict[str, object]:
        params = _as_str_object_dict(request.get("params"))
        if params is None:
            return {"id": request.get("id"), "error": {"code": "invalid_params"}}
        tool_name = params.get("name")
        arguments = _as_str_object_dict(params.get("arguments"))
        if not isinstance(tool_name, str) or arguments is None:
            return {"id": request.get("id"), "error": {"code": "invalid_params"}}
        try:
            result = self._tool_executor.execute(tool_name, arguments)
        except ToolError as error:
            return {
                "id": request.get("id"),
                "error": {"code": "tool_error", "message": str(error)},
            }
        return {"id": request.get("id"), "result": self._serialize_tool_result(result)}

    def _serialize_tool_result(self, result: object) -> object:
        match result:
            case BashResult() | GrepMatch():
                return asdict(result)
            case list():
                values = cast("list[object]", result)
                serialized: list[object] = []
                for item in values:
                    match item:
                        case GrepMatch():
                            serialized.append(asdict(item))
                        case _:
                            serialized.append(item)
                return serialized
            case _:
                return result

    def _run_tui(
        self,
        *,
        store: SessionStore | None,
        persistence: _PersistenceContext,
        stdout: TextIO,
    ) -> int:
        return self._launch_tui_mode(
            store=store,
            persistence=persistence,
            stdout=stdout,
        )

    def _launch_tui_mode(
        self,
        *,
        store: SessionStore | None,
        persistence: _PersistenceContext,
        stdout: TextIO,
    ) -> int:
        if not has_textual_dependency():
            stdout.write(
                "TUI mode is unavailable: install optional dependency 'textual'.\n"
            )
            return 1

        def persist(prompt: str, response: str) -> None:
            self._persist_interaction(
                store=store,
                persistence=persistence,
                payload=_InteractionPayload(
                    mode="tui",
                    prompt=prompt,
                    response=response,
                ),
            )

        return launch_tui_mode(
            responder=self.respond,
            persist_interaction=persist,
        )

    def _persist_interaction(
        self,
        *,
        store: SessionStore | None,
        persistence: _PersistenceContext,
        payload: _InteractionPayload,
    ) -> None:
        event = AppEvent(
            type="interaction_complete",
            mode=payload.mode,
            prompt=payload.prompt,
            response=payload.response,
            branch=persistence.branch,
            session_file=persistence.session_file,
            timestamp_ms=timestamp_ms(),
        )
        self._event_bus.emit(event)
        if store is None:
            return
        store.append_interaction(
            mode=payload.mode,
            prompt=payload.prompt,
            response=payload.response,
        )
        compaction = store.compact_if_needed(
            context_window_tokens=persistence.context_window_tokens,
            settings=persistence.compaction_settings,
        )
        if compaction is None:
            return
        self._emit_compaction_event(
            branch=persistence.branch,
            session_file=persistence.session_file,
            compaction=compaction,
        )

    def _emit_compaction_event(
        self,
        *,
        branch: str,
        session_file: str | None,
        compaction: CompactionRecord,
    ) -> None:
        event = AppEvent(
            type="session_compacted",
            branch=branch,
            session_file=session_file,
            timestamp_ms=compaction.timestamp_ms,
            summary=compaction.summary,
            first_kept_id=compaction.first_kept_id,
            tokens_before=compaction.tokens_before,
            tokens_after=compaction.tokens_after,
        )
        self._event_bus.emit(event)


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the `py-coding-agent` command."""
    app = CodingAgentApp()
    config = parse_args(argv)

    return app.run(config, stdin=sys.stdin, stdout=sys.stdout)


def _resolve_root_path(path_value: str) -> Path:
    raw = Path(path_value)
    if raw.is_absolute():
        return raw.resolve()
    return (Path.cwd() / raw).resolve()
