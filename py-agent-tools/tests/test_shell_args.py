"""Unit tests for shared shell argument parser."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from py_agent_tools.shell_args import ShellArgParser, ShellArgsError


class ShellArgsTests(unittest.TestCase):
    """Tests for common option/flag parsing behavior."""

    def test_parse_flags_values_and_positionals(self) -> None:
        parser = ShellArgParser(
            allowed_flags=frozenset({"-a", "--all"}),
            value_options=frozenset({"-n", "--lines"}),
        )
        parsed = parser.parse(("--all", "-n", "3", "file.txt"))
        assert parsed.has_flag("--all") is True
        assert parsed.get_value("-n") == "3"
        assert parsed.positionals == ("file.txt",)

    def test_parse_compact_short_flags_and_inline_value(self) -> None:
        parser = ShellArgParser(
            allowed_flags=frozenset({"-a"}),
            value_options=frozenset({"-n"}),
        )
        parsed = parser.parse(("-an5",))
        assert parsed.has_flag("-a") is True
        assert parsed.get_value("-n") == "5"

    def test_parse_rejects_unknown_option(self) -> None:
        parser = ShellArgParser()
        failed = False
        try:
            parser.parse(("--unknown",))
        except ShellArgsError:
            failed = True
        assert failed is True

    def test_parse_long_option_with_equals(self) -> None:
        parser = ShellArgParser(value_options=frozenset({"--lines"}))
        parsed = parser.parse(("--lines=8",))
        assert parsed.get_value("--lines") == "8"

    def test_parse_missing_option_value(self) -> None:
        parser = ShellArgParser(value_options=frozenset({"-n"}))
        failed = False
        try:
            parser.parse(("-n",))
        except ShellArgsError:
            failed = True
        assert failed is True

    def test_parse_double_dash_stops_option_parsing(self) -> None:
        parser = ShellArgParser(allowed_flags=frozenset({"-a"}))
        parsed = parser.parse(("--", "-a"))
        assert parsed.has_flag("-a") is False
        assert parsed.positionals == ("-a",)


if __name__ == "__main__":
    unittest.main()
