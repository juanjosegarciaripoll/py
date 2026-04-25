"""Session compaction helpers for py-coding-agent."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from .session import SessionRecord

MIN_RECORDS_FOR_COMPACTION = 2
SUMMARY_ITEM_MAX_CHARS = 120


@dataclass(slots=True)
class CompactionSettings:
    """Configuration knobs controlling automatic compaction behavior."""

    enabled: bool = True
    reserve_tokens: int = 16_384
    keep_recent_tokens: int = 20_000


@dataclass(slots=True)
class CompactionResult:
    """Result payload produced by one compaction pass."""

    summary: str
    first_kept_id: str
    tokens_before: int
    tokens_after: int


def estimate_text_tokens(text: str) -> int:
    """Estimate token count from UTF-8 text using a chars/4 heuristic."""
    if not text:
        return 0
    return math.ceil(len(text) / 4)


def estimate_interaction_tokens(record: SessionRecord) -> int:
    """Estimate token count for one interaction record."""
    return estimate_text_tokens(record.prompt) + estimate_text_tokens(record.response)


def estimate_context_tokens(records: list[SessionRecord]) -> int:
    """Estimate total tokens for a set of interaction records."""
    return sum(estimate_interaction_tokens(record) for record in records)


def should_compact(
    *,
    context_tokens: int,
    context_window_tokens: int,
    settings: CompactionSettings,
) -> bool:
    """Return True when compaction should trigger for the current context usage."""
    if not settings.enabled:
        return False
    if context_window_tokens <= settings.reserve_tokens:
        return False
    return context_tokens > (context_window_tokens - settings.reserve_tokens)


def compact_records(
    *,
    records: list[SessionRecord],
    context_window_tokens: int,
    settings: CompactionSettings,
) -> CompactionResult | None:
    """Compact older interaction records and return a summary payload when needed."""
    if len(records) < MIN_RECORDS_FOR_COMPACTION:
        return None

    tokens_before = estimate_context_tokens(records)
    if not should_compact(
        context_tokens=tokens_before,
        context_window_tokens=context_window_tokens,
        settings=settings,
    ):
        return None

    summarized, kept = split_for_compaction(
        records,
        keep_recent_tokens=settings.keep_recent_tokens,
    )
    if not summarized or not kept:
        return None

    summary = build_structured_summary(summarized=summarized, kept=kept)
    tokens_after = estimate_text_tokens(summary) + estimate_context_tokens(kept)
    return CompactionResult(
        summary=summary,
        first_kept_id=kept[0].id,
        tokens_before=tokens_before,
        tokens_after=tokens_after,
    )


def split_for_compaction(
    records: list[SessionRecord],
    *,
    keep_recent_tokens: int,
) -> tuple[list[SessionRecord], list[SessionRecord]]:
    """Split records into summarized and kept spans via reverse token budget walk."""
    if not records:
        return ([], [])

    tokens = 0
    cut_index = 0
    for index in range(len(records) - 1, -1, -1):
        tokens += estimate_interaction_tokens(records[index])
        if tokens >= keep_recent_tokens:
            cut_index = index
            break

    if cut_index <= 0:
        cut_index = 1

    return (records[:cut_index], records[cut_index:])


def build_structured_summary(
    *,
    summarized: list[SessionRecord],
    kept: list[SessionRecord],
) -> str:
    """Build a deterministic structured summary compatible with future LLM replay."""
    last_prompt = summarized[-1].prompt.strip() if summarized else "(none)"
    done_items = _sample_lines([record.prompt for record in summarized], limit=5)
    progress_hint = kept[0].prompt.strip() if kept else "(none)"
    read_files, modified_files = _extract_file_tracking(summarized)

    lines = [
        "## Goal",
        last_prompt or "(none)",
        "",
        "## Constraints & Preferences",
        "- (none)",
        "",
        "## Progress",
        "### Done",
    ]
    if done_items:
        lines.extend(f"- [x] {item}" for item in done_items)
    else:
        lines.append("- [x] (none)")

    lines.extend(
        [
            "",
            "### In Progress",
            f"- [ ] {progress_hint or '(none)'}",
            "",
            "### Blocked",
            "- (none)",
            "",
            "## Key Decisions",
            (
                "- **Compaction**: Older turns were summarized to preserve "
                "recent context budget."
            ),
            "",
            "## Next Steps",
            "1. Continue from the most recent kept interactions.",
            "",
            "## Critical Context",
            "- Preserve exact file names, commands, and errors from kept turns.",
            f"- <read-files>: {_format_file_tracking(read_files)}",
            f"- <modified-files>: {_format_file_tracking(modified_files)}",
        ]
    )

    return "\n".join(lines)


def _sample_lines(items: list[str], *, limit: int) -> list[str]:
    sampled: list[str] = []
    for raw in items:
        text = " ".join(raw.split()).strip()
        if not text:
            continue
        if len(text) > SUMMARY_ITEM_MAX_CHARS:
            text = f"{text[:117]}..."
        sampled.append(text)
        if len(sampled) >= limit:
            break
    return sampled


def _extract_file_tracking(records: list[SessionRecord]) -> tuple[list[str], list[str]]:
    read_files: set[str] = set()
    modified_files: set[str] = set()
    for record in records:
        if record.mode != "rpc_tool":
            continue
        try:
            payload = _as_str_object_dict(json.loads(record.prompt))
        except json.JSONDecodeError:
            continue
        if payload is None:
            continue
        tool_name = payload.get("tool_name")
        arguments = _as_str_object_dict(payload.get("arguments"))
        if not isinstance(tool_name, str) or arguments is None:
            continue
        path_value = arguments.get("path")
        if not isinstance(path_value, str):
            continue
        if tool_name == "read":
            read_files.add(path_value)
            continue
        if tool_name in {"write", "edit"}:
            modified_files.add(path_value)
    return (sorted(read_files), sorted(modified_files))


def _format_file_tracking(paths: list[str]) -> str:
    if not paths:
        return "(none)"
    return ", ".join(paths)


def _as_str_object_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    raw = cast("dict[object, object]", value)
    result: dict[str, object] = {}
    for key, item in raw.items():
        if not isinstance(key, str):
            return None
        result[key] = item
    return result
