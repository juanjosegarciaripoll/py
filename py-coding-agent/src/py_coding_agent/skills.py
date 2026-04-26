"""Incremental skills loading and dynamic skill tool activation."""

from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass
from pathlib import Path  # noqa: TC003
from types import ModuleType  # noqa: TC003
from typing import Protocol, cast

_SKILL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


class SkillError(Exception):
    """Base error for skill operations."""


class SkillNotFoundError(SkillError):
    """Raised when a skill folder does not exist."""


class SkillValidationError(SkillError):
    """Raised when skill metadata or file requests are invalid."""


class SkillToolCallable(Protocol):
    """Callable signature for dynamically loaded skill tools."""

    def __call__(self, arguments: dict[str, object]) -> object: ...


@dataclass(slots=True, frozen=True)
class SkillSummary:
    """Brief skill listing for progressive LLM loading."""

    name: str
    description: str


@dataclass(slots=True, frozen=True)
class SkillDescriptor:
    """Resolved skill location and parsed summary fields."""

    name: str
    path: Path
    description: str


class SkillDatabase:
    """Loads skill metadata/files incrementally and activates skill tools."""

    def __init__(self, *, root: Path) -> None:
        self._root = root.resolve()
        self._active_tools: dict[str, SkillToolCallable] = {}
        self._active_skills: dict[str, ModuleType | None] = {}

    def list_skills(self) -> list[SkillSummary]:
        """Return `(name, description)` summaries for all skills."""
        if not self._root.exists():
            return []
        summaries: list[SkillSummary] = []
        for entry in sorted(self._root.iterdir(), key=lambda item: item.name):
            if not entry.is_dir():
                continue
            descriptor = self._descriptor_for_folder(entry)
            if descriptor is None:
                continue
            summaries.append(
                SkillSummary(
                    name=descriptor.name,
                    description=descriptor.description,
                )
            )
        return summaries

    def list_skill_files(self, skill_name: str) -> list[str]:
        """List relative files for a skill folder."""
        descriptor = self._resolve_skill(skill_name)
        files: list[str] = []
        for path in sorted(descriptor.path.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(descriptor.path).as_posix()
            files.append(relative)
        return files

    def load_skill(
        self,
        skill_name: str,
        *,
        files: list[str] | None = None,
        activate: bool = False,
    ) -> dict[str, object]:
        """Load selected files for a skill and optionally activate tool module."""
        descriptor = self._resolve_skill(skill_name)
        selected_files = files or ["SKILL.md"]
        payload_files: dict[str, str] = {}
        for relative_path in selected_files:
            payload_files[relative_path] = self.load_skill_file(
                skill_name,
                relative_path,
            )
        activated_tools: list[str] = []
        if activate:
            activated_tools = self.activate_skill(skill_name)
        return {
            "name": descriptor.name,
            "description": descriptor.description,
            "files": payload_files,
            "activated_tools": activated_tools,
        }

    def load_skill_file(self, skill_name: str, relative_path: str) -> str:
        """Load one file from a skill by relative path."""
        descriptor = self._resolve_skill(skill_name)
        candidate = (descriptor.path / relative_path).resolve()
        if not _is_within_root(candidate, descriptor.path):
            message = f"Path escapes skill root: {relative_path}"
            raise SkillValidationError(message)
        if not candidate.is_file():
            message = f"Skill file does not exist: {relative_path}"
            raise SkillValidationError(message)
        return candidate.read_text(encoding="utf-8")

    def activate_skill(self, skill_name: str) -> list[str]:
        """Activate tools from `<skill>/tool` and return exposed tool names."""
        descriptor = self._resolve_skill(skill_name)
        if skill_name in self._active_skills:
            return self._active_tool_names_for_skill(skill_name)
        tool_module = self._load_tool_module(descriptor)
        if tool_module is None:
            self._active_skills[skill_name] = None
            return []
        tool_mapping = self._extract_tool_mapping(tool_module)
        exposed_names: list[str] = []
        for local_name, callable_obj in tool_mapping.items():
            full_name = f"skill.{skill_name}.{local_name}"
            self._active_tools[full_name] = callable_obj
            exposed_names.append(full_name)
        self._active_skills[skill_name] = tool_module
        return sorted(exposed_names)

    def list_active_skill_tools(self) -> list[str]:
        """Return names of currently active dynamic skill tools."""
        return sorted(self._active_tools.keys())

    def get_active_skill_tools(self) -> dict[str, SkillToolCallable]:
        """Return a copy of currently active tool callables by full name."""
        return dict(self._active_tools)

    def _resolve_skill(self, skill_name: str) -> SkillDescriptor:
        self._validate_skill_name(skill_name)
        skill_path = (self._root / skill_name).resolve()
        if not _is_within_root(skill_path, self._root):
            message = f"Skill path escapes root: {skill_name}"
            raise SkillValidationError(message)
        if not skill_path.is_dir():
            message = f"Skill not found: {skill_name}"
            raise SkillNotFoundError(message)
        descriptor = self._descriptor_for_folder(skill_path)
        if descriptor is None:
            message = f"Invalid skill folder: {skill_name}"
            raise SkillValidationError(message)
        return descriptor

    def _descriptor_for_folder(self, folder: Path) -> SkillDescriptor | None:
        name = folder.name
        if not _SKILL_NAME_PATTERN.match(name):
            return None
        readme_path = folder / "SKILL.md"
        if not readme_path.is_file():
            return None
        description = _extract_description(readme_path)
        return SkillDescriptor(
            name=name,
            path=folder,
            description=description,
        )

    def _validate_skill_name(self, skill_name: str) -> None:
        if _SKILL_NAME_PATTERN.match(skill_name):
            return
        message = f"Invalid skill name: {skill_name}"
        raise SkillValidationError(message)

    def _load_tool_module(self, descriptor: SkillDescriptor) -> ModuleType | None:
        tool_package = descriptor.path / "tool"
        init_path = tool_package / "__init__.py"
        if not init_path.is_file():
            return None
        module_name = f"py_coding_agent_skill_{descriptor.name}"
        spec = importlib.util.spec_from_file_location(module_name, init_path)
        if spec is None or spec.loader is None:
            message = f"Unable to load tool module for skill: {descriptor.name}"
            raise SkillValidationError(message)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _extract_tool_mapping(
        self,
        module: ModuleType,
    ) -> dict[str, SkillToolCallable]:
        raw_mapping: object
        if hasattr(module, "register_tools"):
            register_tools = cast("object", module.register_tools)
            if not callable(register_tools):
                message = "`register_tools` must be callable."
                raise SkillValidationError(message)
            raw_mapping = register_tools()
        elif hasattr(module, "TOOLS"):
            raw_mapping = cast("object", module.TOOLS)
        else:
            return {}

        if not isinstance(raw_mapping, dict):
            message = "Skill tool mapping must be a dict."
            raise SkillValidationError(message)
        raw_dict = cast("dict[object, object]", raw_mapping)
        result: dict[str, SkillToolCallable] = {}
        for key, value in raw_dict.items():
            if not isinstance(key, str) or not key:
                message = "Skill tool names must be non-empty strings."
                raise SkillValidationError(message)
            if not callable(value):
                message = f"Skill tool '{key}' must be callable."
                raise SkillValidationError(message)
            result[key] = cast("SkillToolCallable", value)
        return result

    def _active_tool_names_for_skill(self, skill_name: str) -> list[str]:
        prefix = f"skill.{skill_name}."
        names = [name for name in self._active_tools if name.startswith(prefix)]
        return sorted(names)


def _extract_description(readme_path: Path) -> str:
    text = readme_path.read_text(encoding="utf-8")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        return line
    return "No description provided."


def _is_within_root(path: Path, root: Path) -> bool:
    resolved_root = root.resolve()
    if path == resolved_root:
        return True
    return resolved_root in path.parents
