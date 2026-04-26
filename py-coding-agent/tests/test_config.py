"""Unit tests for TOML config loading."""

from __future__ import annotations

import os
import shutil
import unittest
from pathlib import Path

from src.config import (
    AppConfig,
    default_config_path,
    load_config,
    local_config_path,
    resolve_config_path,
)

TMP_DIR = Path(__file__).resolve().parent / ".tmp"
CUSTOM_CONTEXT_WINDOW = 12_345
CUSTOM_RESERVE_TOKENS = 500
CUSTOM_KEEP_RECENT_TOKENS = 600
CUSTOM_THINKING_LEVEL = "high"


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
            "[agent]\nmode='rpc'\nbranch='feature-z'\nsession_file='run.jsonl'\ncontext_window_tokens=12345\n[agent.compaction]\nenabled=false\nreserve_tokens=500\nkeep_recent_tokens=600\n",
            encoding="utf-8",
        )
        try:
            config = load_config(path)
            assert config.mode == "rpc"
            assert config.branch == "feature-z"
            assert config.session_file == "run.jsonl"
            assert config.context_window_tokens == CUSTOM_CONTEXT_WINDOW
            assert config.compaction_enabled is False
            assert config.compaction_reserve_tokens == CUSTOM_RESERVE_TOKENS
            assert config.compaction_keep_recent_tokens == CUSTOM_KEEP_RECENT_TOKENS
            assert config.compaction_thinking_level == "medium"
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

    def test_load_config_accepts_tui_mode(self) -> None:
        test_dir = TMP_DIR / "config-tui"
        shutil.rmtree(test_dir, ignore_errors=True)
        test_dir.mkdir(parents=True, exist_ok=True)
        path = test_dir / "agent.toml"
        path.write_text("[agent]\nmode='tui'\n", encoding="utf-8")
        try:
            config = load_config(path)
            assert config.mode == "tui"
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

    def test_load_config_reads_tool_and_skills_sections(self) -> None:
        test_dir = TMP_DIR / "config-tools-skills"
        shutil.rmtree(test_dir, ignore_errors=True)
        test_dir.mkdir(parents=True, exist_ok=True)
        path = test_dir / "agent.toml"
        path.write_text(
            "[agent]\n"
            "mode='rpc'\n"
            "[agent.tools]\n"
            "allow_read=false\n"
            "allow_write=true\n"
            "allow_execute=false\n"
            "allowed_roots=['src','docs']\n"
            "[agent.skills]\n"
            "root='custom-skills'\n",
            encoding="utf-8",
        )
        try:
            config = load_config(path)
            assert config.tool_allow_read is False
            assert config.tool_allow_write is True
            assert config.tool_allow_execute is False
            assert config.tool_allowed_roots == ("src", "docs")
            assert config.skills_root == "custom-skills"
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_load_config_reads_permissions_section(self) -> None:
        test_dir = TMP_DIR / "config-permissions"
        shutil.rmtree(test_dir, ignore_errors=True)
        test_dir.mkdir(parents=True, exist_ok=True)
        path = test_dir / "agent.toml"
        path.write_text(
            "[agent]\n"
            "[agent.permissions]\n"
            "allow_read=true\n"
            "allow_write=false\n"
            "allow_execute=false\n"
            "allowed_roots=['workspace']\n",
            encoding="utf-8",
        )
        try:
            config = load_config(path)
            assert config.tool_allow_read is True
            assert config.tool_allow_write is False
            assert config.tool_allow_execute is False
            assert config.tool_allowed_roots == ("workspace",)
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_permissions_section_overrides_tools_section(self) -> None:
        test_dir = TMP_DIR / "config-permissions-overrides-tools"
        shutil.rmtree(test_dir, ignore_errors=True)
        test_dir.mkdir(parents=True, exist_ok=True)
        path = test_dir / "agent.toml"
        path.write_text(
            "[agent]\n"
            "[agent.tools]\n"
            "allow_read=false\n"
            "allow_write=true\n"
            "allow_execute=true\n"
            "allowed_roots=['tools-root']\n"
            "[agent.permissions]\n"
            "allow_read=true\n"
            "allow_execute=false\n"
            "allowed_roots=['permissions-root']\n",
            encoding="utf-8",
        )
        try:
            config = load_config(path)
            assert config.tool_allow_read is True
            assert config.tool_allow_write is True
            assert config.tool_allow_execute is False
            assert config.tool_allowed_roots == ("permissions-root",)
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_resolve_config_path_prefers_environment(self) -> None:
        test_dir = TMP_DIR / "config-env-resolution"
        shutil.rmtree(test_dir, ignore_errors=True)
        test_dir.mkdir(parents=True, exist_ok=True)
        original_cwd = Path.cwd()
        original = os.environ.get("PY_CODING_AGENT_CONFIG")
        os.environ["PY_CODING_AGENT_CONFIG"] = "tmp/custom.toml"
        try:
            os.chdir(test_dir)
            resolved = resolve_config_path(None)
            assert resolved is not None
            assert str(resolved).endswith("tmp\\custom.toml")
        finally:
            os.chdir(original_cwd)
            if original is None:
                del os.environ["PY_CODING_AGENT_CONFIG"]
            else:
                os.environ["PY_CODING_AGENT_CONFIG"] = original
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_resolve_config_path_prefers_local_dot_py_config(self) -> None:
        test_dir = TMP_DIR / "config-local-resolution"
        shutil.rmtree(test_dir, ignore_errors=True)
        (test_dir / ".py").mkdir(parents=True, exist_ok=True)
        config_path = test_dir / ".py" / "config.toml"
        config_path.write_text("[agent]\nmode='json'\n", encoding="utf-8")
        original_cwd = Path.cwd()
        original_env = os.environ.get("PY_CODING_AGENT_CONFIG")
        os.environ["PY_CODING_AGENT_CONFIG"] = "tmp/custom.toml"
        try:
            os.chdir(test_dir)
            resolved = resolve_config_path(None)
            assert resolved == config_path
            assert local_config_path() == config_path
        finally:
            os.chdir(original_cwd)
            if original_env is None:
                del os.environ["PY_CODING_AGENT_CONFIG"]
            else:
                os.environ["PY_CODING_AGENT_CONFIG"] = original_env
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_default_config_path_returns_toml(self) -> None:
        path = default_config_path()
        assert path.name == "config.toml"
        assert "py-coding-agent" in str(path)

    def test_default_skills_root_uses_dot_py_folder(self) -> None:
        config = AppConfig()
        assert config.skills_root == ".py/skills"

    def test_load_config_reads_compaction_thinking_level(self) -> None:
        test_dir = TMP_DIR / "config-compaction-thinking"
        shutil.rmtree(test_dir, ignore_errors=True)
        test_dir.mkdir(parents=True, exist_ok=True)
        path = test_dir / "agent.toml"
        path.write_text(
            "[agent]\n"
            "[agent.compaction]\n"
            "thinking_level='high'\n",
            encoding="utf-8",
        )
        try:
            config = load_config(path)
            assert config.compaction_thinking_level == CUSTOM_THINKING_LEVEL
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_load_config_reads_runtime_section(self) -> None:
        test_dir = TMP_DIR / "config-runtime"
        shutil.rmtree(test_dir, ignore_errors=True)
        test_dir.mkdir(parents=True, exist_ok=True)
        path = test_dir / "agent.toml"
        path.write_text(
            "[agent]\n"
            "[agent.runtime]\n"
            "backend='agent'\n"
            "provider='openai_compatible'\n"
            "model='coder-model'\n"
            "api_key_env='OPENAI_API_KEY'\n"
            "base_url='http://localhost:11434/v1'\n"
            "system_prompt='You are integrated.'\n",
            encoding="utf-8",
        )
        try:
            config = load_config(path)
            assert config.runtime_backend == "agent"
            assert config.runtime_provider == "openai_compatible"
            assert config.runtime_model == "coder-model"
            assert config.runtime_api_key_env == "OPENAI_API_KEY"
            assert config.runtime_base_url == "http://localhost:11434/v1"
            assert config.runtime_system_prompt == "You are integrated."
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
