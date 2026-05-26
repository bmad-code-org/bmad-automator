from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from story_automator.commands.orchestrator import cmd_orchestrator_helper
from tests.tea_test_support import install_bundle


class OrchestratorProgressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        target_root = Path(self.tmp.name) / ".claude" / "skills"
        install_bundle(Path(self.tmp.name))
        self.state_file = Path(self.tmp.name) / "state.md"
        self.state_file.write_text(
            "\n".join(
                [
                    "| Story | create-story | code-review | git-commit | Status |",
                    "|-------|----------|----------|----------|----------|",
                    "| 1.1 | ⏳ | ⏳ | ⏳ | pending |",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_state_progress_rejects_markdown_unsafe_value(self) -> None:
        stdout = io.StringIO()
        with patch.dict("os.environ", {"PROJECT_ROOT": self.tmp.name}), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(
                [
                    "state-progress",
                    str(self.state_file),
                    "--story",
                    "1.1",
                    "--set",
                    "status=done|oops",
                ]
            )
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["error"], "invalid_progress_value")

    def test_state_progress_preserves_standard_aliases_without_policy(self) -> None:
        stdout = io.StringIO()
        with patch.dict("os.environ", {"PROJECT_ROOT": self.tmp.name}), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(
                [
                    "state-progress",
                    str(self.state_file),
                    "--story",
                    "1.1",
                    "--set",
                    "create=done",
                    "--set",
                    "review=done",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        text = self.state_file.read_text(encoding="utf-8")
        self.assertIn("| 1.1 | done | done | ⏳ | pending |", text)

    def test_policy_sequence_returns_pinned_sequence(self) -> None:
        snapshot_dir = Path(self.tmp.name) / "_bmad-output" / "story-automator" / "snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_dir / "snap.json"
        snapshot_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "runtime": {"parser": {"provider": "claude", "model": "sonnet", "timeoutSeconds": 30}},
                    "workflow": {"sequence": ["create", "atdd", "dev", "trace", "review"]},
                    "steps": {
                        "create": _session_exit_step("bmad-create-story"),
                        "dev": _session_exit_step("bmad-dev-story"),
                        "review": _review_step("bmad-qa-generate-e2e-tests"),
                        "atdd": _session_exit_step("bmad-testarch-atdd"),
                        "trace": _session_exit_step("bmad-testarch-trace"),
                    },
                }
            ),
            encoding="utf-8",
        )
        state_file = Path(self.tmp.name) / "orchestration.md"
        state_file.write_text(
            "\n".join(
                [
                    "---",
                    f'policySnapshotFile: "{snapshot_path.relative_to(self.tmp.name)}"',
                    f'policySnapshotHash: "{_md5_hex8(snapshot_path.read_text(encoding="utf-8"))}"',
                    "---",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        stdout = io.StringIO()
        with patch.dict("os.environ", {"PROJECT_ROOT": self.tmp.name}), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["policy-sequence", "--state-file", str(state_file)])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["sequence"], ["create", "atdd", "dev", "trace", "review"])


def _session_exit_step(skill_name: str) -> dict[str, object]:
    return {
        "label": skill_name,
        "assets": {
            "skillName": skill_name,
            "workflowCandidates": [],
            "instructionsCandidates": [],
            "checklistCandidates": [],
            "templateCandidates": [],
            "required": [],
        },
        "prompt": {"templateFile": "data/prompts/review.md", "interactionMode": "autonomous"},
        "parse": {"schemaFile": "data/parse/review.json"},
        "success": {"verifier": "session_exit"},
    }


def _review_step(skill_name: str) -> dict[str, object]:
    step = _session_exit_step(skill_name)
    step["success"] = {"verifier": "review_completion"}
    return step


def _md5_hex8(text: str) -> str:
    import hashlib

    return hashlib.md5(text.encode("utf-8")).hexdigest()[:8]


if __name__ == "__main__":
    unittest.main()
