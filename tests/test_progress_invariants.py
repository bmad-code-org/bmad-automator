from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from story_automator.commands.orchestrator import cmd_orchestrator_helper
from story_automator.commands.state import cmd_build_state_doc
from tests.tea_test_support import install_bundle, install_required_skills, patch_env


class ProgressInvariantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)
        self.output_dir = self.project_root / "_bmad-output" / "story-automator"
        install_bundle(self.project_root)
        install_required_skills(self.project_root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_build_state_doc_rejects_duplicate_story_ids(self) -> None:
        payload = self._build_state_payload({"storyRange": ["1.1", "1.1"]}, expect_code=1)
        self.assertEqual(payload["error"], "storyRange_contains_duplicates")

    def test_build_state_doc_rejects_markdown_unsafe_story_ids(self) -> None:
        payload = self._build_state_payload({"storyRange": ["1|1"]}, expect_code=1)
        self.assertEqual(payload["error"], "storyRange_contains_invalid_ids")

    def test_standard_progress_rejects_atdd_updates(self) -> None:
        state_file = Path(self._build_state_payload({}, expect_code=0)["path"])
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(
                ["state-progress", str(state_file), "--story", "1.1", "--set", "atdd=done", "--set", "status=in-progress"]
            )
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["error"], "progress_columns_not_found")
        self.assertEqual(payload["missing"], ["atdd"])

    def test_standard_progress_rejects_auto_updates_when_auto_column_missing(self) -> None:
        state_file = self._write_minimal_state_without_auto()
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(
                ["state-progress", str(state_file), "--story", "1.1", "--set", "auto=done", "--set", "status=in-progress"]
            )
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["error"], "progress_columns_not_found")
        self.assertEqual(payload["missing"], ["automate"])

    def _build_state_payload(self, overrides: dict[str, object], *, expect_code: int) -> dict[str, object]:
        stdout = io.StringIO()
        template = self.project_root / ".claude" / "skills" / "bmad-story-automator" / "templates" / "state-document.md"
        config = {
            "epic": "1",
            "epicName": "Epic 1",
            "storyRange": ["1.1"],
            "status": "READY",
            "aiCommand": "claude --dangerously-skip-permissions",
        }
        config.update(overrides)
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_build_state_doc(
                ["--template", str(template), "--output-folder", str(self.output_dir), "--config-json", json.dumps(config)]
            )
        self.assertEqual(code, expect_code)
        return json.loads(stdout.getvalue())

    def _write_minimal_state_without_auto(self) -> Path:
        state_file = self.project_root / "state-no-auto.md"
        state_file.write_text(
            "\n".join(
                [
                    "| Story | create-story | dev-story | code-review | git-commit | Status |",
                    "|-------|----------|----------|----------|----------|----------|",
                    "| 1.1 | ⏳ | ⏳ | ⏳ | ⏳ | pending |",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return state_file


if __name__ == "__main__":
    unittest.main()
