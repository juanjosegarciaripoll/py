"""Unit tests for TOML config loading."""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from src.config import AppConfig, load_config

TMP_DIR = Path(__file__).resolve().parent / ".tmp"


class ConfigTests(unittest.TestCase):
    """Tests for configuration loading semantics."""

    def test_load_config_defaults_for_missing_path(self) -> None:
        missing = TMP_DIR / "does-not-exist.toml"
        config = load_config(missing)
        assert config == AppConfig()

    def test_load_config_reads_agent_section(self) -> None:
        test_dir = TMP_DIR / "config-read"
        shutil.rmtree(test_dir, ignore_errors=True)
        test_dir.mkdir(parents=True, exist_ok=True)
        path = test_dir / "agent.toml"
        path.write_text(
            "[agent]\nmode='rpc'\nbranch='feature-z'\nsession_file='run.jsonl'\n",
            encoding="utf-8",
        )
        try:
            config = load_config(path)
            assert config.mode == "rpc"
            assert config.branch == "feature-z"
            assert config.session_file == "run.jsonl"
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_load_config_ignores_invalid_values(self) -> None:
        test_dir = TMP_DIR / "config-invalid"
        shutil.rmtree(test_dir, ignore_errors=True)
        test_dir.mkdir(parents=True, exist_ok=True)
        path = test_dir / "agent.toml"
        path.write_text(
            "[agent]\nmode='bad-mode'\nbranch=7\nsession_file=1\n",
            encoding="utf-8",
        )
        try:
            config = load_config(path)
            assert config.mode == "interactive"
            assert config.branch == "main"
            assert config.session_file is None
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_load_config_without_agent_section(self) -> None:
        test_dir = TMP_DIR / "config-empty"
        shutil.rmtree(test_dir, ignore_errors=True)
        test_dir.mkdir(parents=True, exist_ok=True)
        path = test_dir / "agent.toml"
        path.write_text("[other]\nvalue='x'\n", encoding="utf-8")
        try:
            config = load_config(path)
            assert config == AppConfig()
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
