from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from story_automator.commands.state import cmd_build_run_policy
from story_automator.core.runtime_policy import PolicyError, load_effective_policy
from tests.tea_test_support import install_bundle, install_required_skills, install_tea_skills, patch_env, tea_steps_override


class PolicyInvariantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)
        install_bundle(self.project_root)
        install_required_skills(self.project_root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_workflow_sequence_requires_review(self) -> None:
        self._write_override({"workflow": {"sequence": ["create", "dev"]}})
        with self.assertRaisesRegex(PolicyError, "workflow.sequence must include review"):
            load_effective_policy(str(self.project_root))

    def test_workflow_sequence_rejects_duplicates(self) -> None:
        self._write_override({"workflow": {"sequence": ["create", "dev", "dev", "review"]}})
        with self.assertRaisesRegex(PolicyError, "workflow.sequence contains duplicate steps: dev"):
            load_effective_policy(str(self.project_root))

    def test_unknown_workflow_track_fails_closed(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_build_run_policy(["--config-json", json.dumps({"workflowTrack": "teaa"})])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["error"], "policy_invalid")
        self.assertIn("unknown workflowTrack: teaa", payload["reason"])

    def test_explicit_tea_policy_ignores_include_retro_with_note(self) -> None:
        install_tea_skills(self.project_root, canonical=True)
        self._write_override(
            {
                "workflow": {"sequence": ["create", "atdd", "dev", "test_automate", "test_review", "trace", "review"]},
                "steps": tea_steps_override(canonical=True),
            }
        )
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_build_run_policy(["--config-json", json.dumps({"workflowTrack": "tea", "includeRetro": True})])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(any("Per-run TEA optional-step selection was ignored" in note for note in payload["notes"]))

    def _write_override(self, payload: dict[str, object]) -> None:
        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "story-automator.policy.json").write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
