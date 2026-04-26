"""Reusable command-line style argument parsing for shell handlers."""

from __future__ import annotations

from dataclasses import dataclass


class ShellArgsError(ValueError):
    """Raised when command arguments are invalid."""

    @classmethod
    def unknown_option(cls, option: str) -> ShellArgsError:
        """Create unknown-option error."""
        message = f"Unknown option: {option}"
        return cls(message)

    @classmethod
    def missing_option_value(cls, option: str) -> ShellArgsError:
        """Create missing-option-value error."""
        message = f"Option requires a value: {option}"
        return cls(message)


@dataclass(slots=True, frozen=True)
class ParsedShellArgs:
    """Normalized parsed arguments."""

    flags: frozenset[str]
    values: dict[str, str]
    positionals: tuple[str, ...]

    def has_flag(self, name: str) -> bool:
        """Whether flag is present."""
        return name in self.flags

    def get_value(self, name: str, default: str | None = None) -> str | None:
        """Return option value."""
        return self.values.get(name, default)


@dataclass(slots=True, frozen=True)
class ShellArgParser:
    """Small reusable parser for short/long options and positionals."""

    allowed_flags: frozenset[str] = frozenset()
    value_options: frozenset[str] = frozenset()

    def parse(self, arguments: tuple[str, ...]) -> ParsedShellArgs:
        """Parse shell command arguments."""
        flags: set[str] = set()
        values: dict[str, str] = {}
        positionals: list[str] = []
        index = 0
        in_positional_mode = False
        while index < len(arguments):
            arg = arguments[index]
            if in_positional_mode or arg == "-" or not arg.startswith("-"):
                positionals.append(arg)
                index += 1
                continue
            if arg == "--":
                in_positional_mode = True
                index += 1
                continue
            if arg.startswith("--"):
                index = self._parse_long(
                    arguments=arguments,
                    index=index,
                    arg=arg,
                    flags=flags,
                    values=values,
                )
                continue
            index = self._parse_short(
                arguments=arguments,
                index=index,
                arg=arg,
                flags=flags,
                values=values,
            )
        return ParsedShellArgs(
            flags=frozenset(flags),
            values=values,
            positionals=tuple(positionals),
        )

    def _parse_long(
        self,
        *,
        arguments: tuple[str, ...],
        index: int,
        arg: str,
        flags: set[str],
        values: dict[str, str],
    ) -> int:
        option, has_equals, value = arg.partition("=")
        if option in self.allowed_flags:
            if has_equals:
                raise ShellArgsError.unknown_option(arg)
            flags.add(option)
            return index + 1
        if option in self.value_options:
            if has_equals:
                values[option] = value
                return index + 1
            next_index = index + 1
            if next_index >= len(arguments):
                raise ShellArgsError.missing_option_value(option)
            values[option] = arguments[next_index]
            return next_index + 1
        raise ShellArgsError.unknown_option(option)

    def _parse_short(
        self,
        *,
        arguments: tuple[str, ...],
        index: int,
        arg: str,
        flags: set[str],
        values: dict[str, str],
    ) -> int:
        option_group = arg[1:]
        if not option_group:
            raise ShellArgsError.unknown_option(arg)
        consumed_index = index + 1
        for short_index, short_name in enumerate(option_group):
            option = f"-{short_name}"
            if option in self.allowed_flags:
                flags.add(option)
                continue
            if option in self.value_options:
                inline_value = option_group[short_index + 1 :]
                if inline_value:
                    values[option] = inline_value
                    return consumed_index
                if consumed_index >= len(arguments):
                    raise ShellArgsError.missing_option_value(option)
                values[option] = arguments[consumed_index]
                return consumed_index + 1
            raise ShellArgsError.unknown_option(option)
        return consumed_index

