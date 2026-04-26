"""CLI entry points and execution modes for py-coding-agent."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TextIO, cast

from .compaction import (
    CompactionSettings,
    CompactionSummaryRequest,
    CompactionThinkingLevel,
    build_summary_request,
)
from .config import AppConfig, load_config
from .extensions import (
    AppEvent,
    EventBus,
    EventListener,
    SessionBeforeCompactContext,
    SessionBeforeCompactHook,
)
from .integration import (
    AgenticResponder,
    AgentRuntimeError,
    RuntimeModelConfig,
)
from .session import CompactionRecord, SessionRecord, SessionStore, timestamp_ms
from .tools import (
    BashResult,
    BuiltinToolExecutor,
    GrepMatch,
    ToolError,
    ToolSandboxPolicy,
)
from .tui import has_textual_dependency, launch_tui_mode

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

type CompactionSummaryGenerator = Callable[[CompactionSummaryRequest], str]

type ExecutionMode = Literal["interactive", "print", "json", "rpc", "tui"]
MAX_OVERFLOW_RECOVERY_RETRIES = 1


class ContextOverflowError(RuntimeError):
    """Raised when model context is too large and requires compaction."""


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
    compaction_thinking_level: CompactionThinkingLevel = "medium"
    runtime_backend: Literal["echo", "agent"] = "echo"
    runtime_provider: Literal[
        "echo", "openai", "anthropic", "openai_compatible"
    ] = "echo"
    runtime_model: str = "echo-1"
    runtime_api_key_env: str | None = None
    runtime_base_url: str | None = None
    runtime_system_prompt: str = "You are a helpful coding assistant."


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
    compaction_thinking_level: CompactionThinkingLevel


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
        compaction_thinking_level=defaults.compaction_thinking_level,
        runtime_backend=defaults.runtime_backend,
        runtime_provider=defaults.runtime_provider,
        runtime_model=defaults.runtime_model,
        runtime_api_key_env=defaults.runtime_api_key_env,
        runtime_base_url=defaults.runtime_base_url,
        runtime_system_prompt=defaults.runtime_system_prompt,
    )


class CodingAgentApp:
    """Small execution harness with four user-facing modes."""

    def __init__(
        self,
        *,
        event_bus: EventBus | None = None,
        compaction_summary_generator: CompactionSummaryGenerator | None = None,
    ) -> None:
        self._event_bus = event_bus or EventBus()
        self._tool_executor = BuiltinToolExecutor(cwd=Path.cwd())
        self._compaction_summary_generator = compaction_summary_generator
        self._active_run_config: RunConfig | None = None
        self._active_store: SessionStore | None = None
        self._active_persistence: _PersistenceContext | None = None
        self._agentic_responder: AgenticResponder | None = None

    def subscribe(self, listener: EventListener) -> Callable[[], None]:
        """Subscribe to app events and return an unsubscribe callback."""
        return self._event_bus.subscribe(listener)

    def subscribe_session_before_compact(
        self,
        hook: SessionBeforeCompactHook,
    ) -> Callable[[], None]:
        """Subscribe to `session_before_compact` compaction hooks."""
        return self._event_bus.subscribe_session_before_compact(hook)

    def respond(self, prompt: str) -> str:
        """Produce a deterministic response for the current prompt."""
        if (
            self._active_run_config is not None
            and self._active_run_config.runtime_backend == "agent"
        ):
            try:
                return self._respond_with_integrated_runtime(prompt)
            except AgentRuntimeError:
                text = prompt.strip()
                if text:
                    return f"Echo: {text}"
                return "Echo: (empty prompt)"
        text = prompt.strip()
        if text:
            return f"Echo: {text}"
        return "Echo: (empty prompt)"

    def _respond_with_overflow_recovery(
        self,
        *,
        prompt: str,
        store: SessionStore | None,
        persistence: _PersistenceContext,
    ) -> str:
        attempts = 0
        while True:
            try:
                return self.respond(prompt)
            except ContextOverflowError:
                if attempts >= MAX_OVERFLOW_RECOVERY_RETRIES or store is None:
                    raise
                compaction = self._compact_with_extensions(
                    store=store,
                    persistence=persistence,
                )
                if compaction is None:
                    raise
                self._emit_compaction_event(
                    branch=persistence.branch,
                    session_file=persistence.session_file,
                    compaction=compaction,
                )
                attempts += 1

    def run(
        self,
        config: RunConfig,
        *,
        stdin: TextIO,
        stdout: TextIO,
    ) -> int:
        """Run one mode and return process exit code."""
        self._active_run_config = config
        self._configure_tools(config)
        store = self._build_store(config)
        self._active_store = store
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
            compaction_thinking_level=config.compaction_thinking_level,
        )
        self._active_persistence = persistence
        self._agentic_responder = self._build_agentic_responder(config)
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

    def _build_agentic_responder(self, config: RunConfig) -> AgenticResponder | None:
        if config.runtime_backend != "agent":
            return None
        return AgenticResponder(
            RuntimeModelConfig(
                backend=config.runtime_backend,
                provider=config.runtime_provider,
                model=config.runtime_model,
                api_key_env=config.runtime_api_key_env,
                base_url=config.runtime_base_url,
            )
        )

    def _respond_with_integrated_runtime(self, prompt: str) -> str:
        responder = self._agentic_responder
        if responder is None:
            msg = "Integrated responder is not configured."
            raise AgentRuntimeError(msg)
        system_prompt = self._build_system_prompt()
        return _run_async_maybe_threadsafe(
            responder.respond(prompt, system_prompt=system_prompt)
        )

    def _build_system_prompt(self) -> str:
        config = self._active_run_config
        if config is None:
            return "You are a helpful coding assistant."
        lines = [config.runtime_system_prompt.strip()]
        persistence = self._active_persistence
        if persistence is not None:
            lines.append(f"Branch: {persistence.branch}")
        lines.append(f"Mode: {config.mode}")
        store = self._active_store
        if store is not None:
            recent = store.load()[-2:]
            if recent:
                lines.append("Recent session context:")
                for item in recent:
                    lines.append(f"User: {item.prompt}")
                    lines.append(f"Assistant: {item.response}")
        return "\n".join(line for line in lines if line)

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
            try:
                response = self._respond_with_overflow_recovery(
                    prompt=prompt,
                    store=store,
                    persistence=persistence,
                )
            except ContextOverflowError:
                stdout.write("Error: context_overflow\n")
                continue
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
        try:
            response = self._respond_with_overflow_recovery(
                prompt=prompt,
                store=store,
                persistence=persistence,
            )
        except ContextOverflowError:
            stdout.write("Error: context_overflow\n")
            return 1
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
        try:
            response = self._respond_with_overflow_recovery(
                prompt=prompt,
                store=store,
                persistence=persistence,
            )
        except ContextOverflowError:
            stdout.write('{"error":"context_overflow"}\n')
            return 1
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
            should_shutdown = self._process_rpc_line(
                line=line,
                stdout=stdout,
                store=store,
                persistence=persistence,
            )
            if should_shutdown:
                return 0
        return 0

    def _process_rpc_line(
        self,
        *,
        line: str,
        stdout: TextIO,
        store: SessionStore | None,
        persistence: _PersistenceContext,
    ) -> bool:
        text = line.strip()
        if not text:
            return False
        try:
            parsed: object = json.loads(text)
        except json.JSONDecodeError:
            stdout.write('{"error":"invalid_json"}\n')
            return False
        request = _as_str_object_dict(parsed)
        if request is None:
            stdout.write('{"error":"invalid_request"}\n')
            return False
        return self._handle_rpc_request(
            request=request,
            stdout=stdout,
            store=store,
            persistence=persistence,
        )

    def _handle_rpc_request(
        self,
        *,
        request: dict[str, object],
        stdout: TextIO,
        store: SessionStore | None,
        persistence: _PersistenceContext,
    ) -> bool:
        method = request.get("method")
        if method == "shutdown":
            stdout.write('{"ok":true}\n')
            return True
        if method == "tool":
            response = self._rpc_tool_response(request=request)
            stdout.write(json.dumps(response) + "\n")
            tool_payload = _as_str_object_dict(request.get("params"))
            if tool_payload is not None:
                self._persist_rpc_tool_interaction(
                    store=store,
                    persistence=persistence,
                    tool_payload=tool_payload,
                    response=response,
                )
            return False
        if method != "prompt":
            stdout.write('{"error":"method_not_found"}\n')
            return False
        self._handle_rpc_prompt(
            request=request,
            stdout=stdout,
            store=store,
            persistence=persistence,
        )
        return False

    def _handle_rpc_prompt(
        self,
        *,
        request: dict[str, object],
        stdout: TextIO,
        store: SessionStore | None,
        persistence: _PersistenceContext,
    ) -> None:
        params = _as_str_object_dict(request.get("params"))
        if params is None:
            stdout.write('{"error":"invalid_params"}\n')
            return
        prompt_value = params.get("prompt", "")
        if not isinstance(prompt_value, str):
            stdout.write('{"error":"invalid_params"}\n')
            return
        request_id = request.get("id")
        try:
            response_text = self._respond_with_overflow_recovery(
                prompt=prompt_value,
                store=store,
                persistence=persistence,
            )
        except ContextOverflowError:
            error_response = {
                "id": request_id,
                "error": {"code": "context_overflow"},
            }
            stdout.write(json.dumps(error_response) + "\n")
            return
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

    def _persist_rpc_tool_interaction(
        self,
        *,
        store: SessionStore | None,
        persistence: _PersistenceContext,
        tool_payload: dict[str, object],
        response: dict[str, object],
    ) -> None:
        tool_name = tool_payload.get("name")
        arguments = _as_str_object_dict(tool_payload.get("arguments"))
        if not isinstance(tool_name, str) or arguments is None:
            return
        prompt_payload = {
            "tool_name": tool_name,
            "arguments": arguments,
        }
        self._persist_interaction(
            store=store,
            persistence=persistence,
            payload=_InteractionPayload(
                mode="rpc_tool",
                prompt=json.dumps(prompt_payload, sort_keys=True),
                response=json.dumps(response, sort_keys=True),
            ),
        )

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
        compaction = self._compact_with_extensions(
            store=store,
            persistence=persistence,
        )
        if compaction is None:
            return
        self._emit_compaction_event(
            branch=persistence.branch,
            session_file=persistence.session_file,
            compaction=compaction,
        )

    def _compact_with_extensions(
        self,
        *,
        store: SessionStore,
        persistence: _PersistenceContext,
    ) -> CompactionRecord | None:
        planned = store.plan_compaction(
            context_window_tokens=persistence.context_window_tokens,
            settings=persistence.compaction_settings,
        )
        if planned is None:
            return None

        context = SessionBeforeCompactContext(
            branch=persistence.branch,
            session_file=persistence.session_file,
            context_window_tokens=persistence.context_window_tokens,
            settings=persistence.compaction_settings,
            interactions_count=len(store.load()),
            proposed_summary=planned.summary,
            proposed_first_kept_id=planned.first_kept_id,
            proposed_tokens_before=planned.tokens_before,
            proposed_tokens_after=planned.tokens_after,
        )
        decision = self._event_bus.run_session_before_compact(context)
        if decision is not None and decision.cancel:
            return None

        summary = (
            planned.summary
            if decision is None or decision.summary is None
            else decision.summary
        )
        records = store.load()
        summary = self._maybe_generate_compaction_summary(
            summary=summary,
            records=records,
            kept_first_id=planned.first_kept_id,
            persistence=persistence,
        )
        first_kept_id = (
            planned.first_kept_id
            if decision is None or decision.first_kept_id is None
            else decision.first_kept_id
        )
        tokens_before = (
            planned.tokens_before
            if decision is None or decision.tokens_before is None
            else decision.tokens_before
        )
        tokens_after = (
            planned.tokens_after
            if decision is None or decision.tokens_after is None
            else decision.tokens_after
        )
        return store.append_compaction(
            summary=summary,
            first_kept_id=first_kept_id,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
        )

    def _maybe_generate_compaction_summary(
        self,
        *,
        summary: str,
        records: list[SessionRecord],
        kept_first_id: str,
        persistence: _PersistenceContext,
    ) -> str:
        generator = self._compaction_summary_generator
        if generator is None:
            return summary
        summarized_records, kept_records = _split_records_by_first_kept_id(
            records=records,
            first_kept_id=kept_first_id,
        )
        if not summarized_records or not kept_records:
            return summary
        request = build_summary_request(
            summarized=summarized_records,
            kept=kept_records,
            keep_recent_tokens=persistence.compaction_settings.keep_recent_tokens,
            thinking_level=persistence.compaction_thinking_level,
        )
        generated = generator(request).strip()
        if generated:
            return generated
        return summary

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


def _split_records_by_first_kept_id(
    *,
    records: list[SessionRecord],
    first_kept_id: str,
) -> tuple[list[SessionRecord], list[SessionRecord]]:
    for index, record in enumerate(records):
        if record.id == first_kept_id:
            return (records[:index], records[index:])
    return ([], [])


def _run_async_maybe_threadsafe(coro: Coroutine[object, object, str]) -> str:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(coro)).result()
