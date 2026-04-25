"""Unit tests for incremental skills loading."""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from src.skills import SkillDatabase, SkillValidationError

TMP_DIR = Path(__file__).resolve().parent / ".tmp"


class SkillTests(unittest.TestCase):
    """Tests for skill listing/loading and dynamic tool activation."""

    @classmethod
    def setUpClass(cls) -> None:
        shutil.rmtree(TMP_DIR, ignore_errors=True)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(TMP_DIR, ignore_errors=True)

    def test_list_and_load_skill(self) -> None:
        skills_root = TMP_DIR / "skills-db"
        skill_dir = skills_root / "demo-skill"
        (skill_dir / "tool").mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            "# Demo Skill\n\nA compact skill description.\n\nDetails.\n",
            encoding="utf-8",
        )
        (skill_dir / "notes.md").write_text("Notes body\n", encoding="utf-8")
        (skill_dir / "tool" / "__init__.py").write_text(
            "def register_tools():\n"
            "    def ping(arguments):\n"
            '        value = arguments.get("name", "world")\n'
            "        if not isinstance(value, str):\n"
            '            value = "world"\n'
            '        return {"message": "pong:" + value}\n'
            '    return {"ping": ping}\n',
            encoding="utf-8",
        )
        database = SkillDatabase(root=skills_root)
        summaries = database.list_skills()
        assert len(summaries) == 1
        assert summaries[0].name == "demo-skill"
        assert summaries[0].description == "A compact skill description."

        files = database.list_skill_files("demo-skill")
        assert "SKILL.md" in files
        assert "notes.md" in files
        assert "tool/__init__.py" in files

        loaded = database.load_skill("demo-skill", files=["notes.md"])
        assert loaded["name"] == "demo-skill"
        loaded_files = loaded["files"]
        assert isinstance(loaded_files, dict)
        assert loaded_files["notes.md"] == "Notes body\n"

        activated = database.load_skill("demo-skill", activate=True)
        activated_tools = activated["activated_tools"]
        assert isinstance(activated_tools, list)
        assert "skill.demo-skill.ping" in activated_tools
        active_tools = database.get_active_skill_tools()
        ping_handler = active_tools["skill.demo-skill.ping"]
        ping_result = ping_handler({"name": "agent"})
        assert ping_result == {"message": "pong:agent"}
        active_tool_names = database.list_active_skill_tools()
        assert active_tool_names == ["skill.demo-skill.ping"]

    def test_load_skill_file_rejects_path_escape(self) -> None:
        skills_root = TMP_DIR / "skills-escape"
        skill_dir = skills_root / "safe-skill"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            "# Safe Skill\n\nDescription.\n",
            encoding="utf-8",
        )
        database = SkillDatabase(root=skills_root)
        failed = False
        try:
            database.load_skill_file("safe-skill", "../outside.txt")
        except SkillValidationError:
            failed = True
        assert failed is True

    def test_unknown_skill_tool_lookup_returns_empty(self) -> None:
        database = SkillDatabase(root=TMP_DIR / "does-not-exist")
        assert database.get_active_skill_tools() == {}


if __name__ == "__main__":
    unittest.main()
