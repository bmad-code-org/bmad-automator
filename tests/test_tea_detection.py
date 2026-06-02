from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from story_automator.commands.orchestrator import cmd_orchestrator_helper
from story_automator.commands.state import cmd_build_state_doc, cmd_detect_workflow_track
from tests.tea_test_support import (
    install_bundle,
    install_required_skills,
    install_tea_skills,
    patch_env,
    tea_steps_override,
    write_tea_assets,
)


class TeaDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)
        self.output_dir = self.project_root / "_bmad-output" / "story-automator"
        install_bundle(self.project_root)
        install_required_skills(self.project_root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_detect_workflow_track_recommends_tea_when_project_is_capable(self) -> None:
        install_tea_skills(self.project_root)
        payload = self._detect()
        self.assertEqual(payload["recommendedTrack"], "tea")
        self.assertTrue(payload["requiresConfirmation"])
        self.assertTrue(payload["teaCapable"])
        self.assertIn("Detected TEA support for this project", payload["prompt"])

    def test_detect_workflow_track_accepts_canonical_tea_skill_names(self) -> None:
        install_tea_skills(self.project_root, canonical=True)
        payload = self._detect()
        self.assertEqual(payload["recommendedTrack"], "tea")
        self.assertTrue(payload["teaCapable"])
        self.assertEqual(
            payload["availableSkills"],
            [
                "bmad-testarch-atdd",
                "bmad-testarch-automate",
                "bmad-testarch-test-review",
                "bmad-testarch-trace",
            ],
        )

    def test_detect_workflow_track_uses_bundled_tea_adapter_assets(self) -> None:
        install_tea_skills(self.project_root, canonical=True, write_assets=False)
        payload = self._detect()
        self.assertEqual(payload["recommendedTrack"], "tea")
        self.assertTrue(payload["teaCapable"])
        self.assertEqual(payload["assetsRoot"], "data/tea-story-automator")
        self.assertEqual(payload["missingAssets"], [])

    def test_detect_workflow_track_falls_back_when_project_tea_assets_are_incomplete(self) -> None:
        install_tea_skills(self.project_root, canonical=True, write_assets=False)
        incomplete_dir = self.project_root / "_bmad" / "tea" / "story-automator" / "prompts"
        incomplete_dir.mkdir(parents=True, exist_ok=True)
        payload = self._detect()
        self.assertEqual(payload["recommendedTrack"], "tea")
        self.assertTrue(payload["teaCapable"])
        self.assertEqual(payload["assetsRoot"], "data/tea-story-automator")
        self.assertEqual(payload["missingAssets"], [])

    def test_detect_workflow_track_stays_standard_when_skills_are_missing(self) -> None:
        write_tea_assets(self.project_root)
        payload = self._detect()
        self.assertEqual(payload["recommendedTrack"], "standard")
        self.assertFalse(payload["teaCapable"])
        self.assertTrue(payload["missingSkills"])

    def test_detect_workflow_track_honors_explicit_standard_override_even_when_project_is_tea_capable(self) -> None:
        install_tea_skills(self.project_root, canonical=True, write_assets=False)
        self._write_policy_override({"workflow": {"sequence": ["create", "dev", "review"]}})
        payload = self._detect()
        self.assertEqual(payload["recommendedTrack"], "standard")
        self.assertFalse(payload["requiresConfirmation"])
        self.assertFalse(payload["explicitTeaPolicy"])
        self.assertTrue(any("explicit standard story-automator policy override" in note for note in payload["reasons"]))

    def test_detect_workflow_track_rejects_invalid_explicit_standard_override(self) -> None:
        self._write_policy_override({"workflow": {"sequence": ["create", "bogus", "review"]}})
        payload = self._detect()
        self.assertEqual(payload["recommendedTrack"], "standard")
        self.assertFalse(payload["teaCapable"])
        self.assertTrue(any("explicit standard story-automator policy override, but it is invalid" in note for note in payload["reasons"]))
        self.assertTrue(any("workflow.sequence references missing step: bogus" in note for note in payload["reasons"]))

    def test_detect_workflow_track_honors_explicit_tea_policy(self) -> None:
        install_tea_skills(self.project_root)
        self._write_policy_override(
            {
                "workflow": {"sequence": ["create", "atdd", "dev", "test_automate", "test_review", "trace", "review"]},
                "steps": tea_steps_override(),
            }
        )
        payload = self._detect()
        self.assertEqual(payload["recommendedTrack"], "tea")
        self.assertFalse(payload["requiresConfirmation"])
        self.assertTrue(payload["explicitTeaPolicy"])

    def test_detect_workflow_track_trusts_valid_explicit_tea_policy_with_custom_asset_root(self) -> None:
        install_tea_skills(self.project_root, canonical=True, write_assets=False)
        custom_root = self.project_root / "custom-tea-assets"
        write_tea_assets(self.project_root, root=custom_root)
        self._write_policy_override(
            {
                "workflow": {"sequence": ["create", "atdd", "dev", "test_automate", "test_review", "trace", "review"]},
                "steps": tea_steps_override(canonical=True, assets_root="custom-tea-assets"),
            }
        )
        payload = self._detect()
        self.assertEqual(payload["recommendedTrack"], "tea")
        self.assertTrue(payload["teaCapable"])
        self.assertEqual(payload["assetsRoot"], "custom-tea-assets")
        self.assertEqual(payload["missingAssets"], [])
        self.assertEqual(
            payload["availableSkills"],
            [
                "bmad-testarch-atdd",
                "bmad-testarch-automate",
                "bmad-testarch-test-review",
                "bmad-testarch-trace",
            ],
        )

    def test_detect_workflow_track_reports_multiple_asset_roots_for_valid_explicit_policy(self) -> None:
        install_tea_skills(self.project_root, canonical=True, write_assets=False)
        write_tea_assets(self.project_root)
        custom_root = self.project_root / "custom-tea-assets"
        write_tea_assets(self.project_root, root=custom_root)
        override_steps = tea_steps_override(canonical=True)
        override_steps["trace"] = tea_steps_override(canonical=True, assets_root="custom-tea-assets")["trace"]
        self._write_policy_override(
            {
                "workflow": {"sequence": ["create", "atdd", "dev", "test_automate", "test_review", "trace", "review"]},
                "steps": override_steps,
            }
        )
        payload = self._detect()
        self.assertEqual(payload["recommendedTrack"], "tea")
        self.assertTrue(payload["teaCapable"])
        self.assertEqual(payload["missingAssets"], [])
        self.assertEqual(payload["assetsRoot"], "_bmad/tea/story-automator, custom-tea-assets")

    def test_detect_workflow_track_rejects_explicit_tea_policy_missing_step_contract(self) -> None:
        install_tea_skills(self.project_root, canonical=True)
        self._write_policy_override({"workflow": {"sequence": ["create", "atdd", "dev", "review"]}, "steps": {}})
        payload = self._detect()
        self.assertEqual(payload["recommendedTrack"], "standard")
        self.assertFalse(payload["teaCapable"])
        self.assertTrue(any("workflow.sequence references missing step: atdd" in note for note in payload["reasons"]))

    def test_detect_workflow_track_reports_invalid_explicit_override_file(self) -> None:
        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "story-automator.policy.json").write_text("{bad json", encoding="utf-8")
        payload = self._detect()
        self.assertEqual(payload["recommendedTrack"], "standard")
        self.assertFalse(payload["teaCapable"])
        self.assertFalse(payload["teaDetected"])
        self.assertTrue(any("story-automator policy override, but it is invalid" in note for note in payload["reasons"]))
        self.assertTrue(any("invalid JSON" in note for note in payload["reasons"]))

    def test_detect_workflow_track_rejects_explicit_tea_policy_when_skills_missing(self) -> None:
        write_tea_assets(self.project_root)
        self._write_policy_override(
            {
                "workflow": {"sequence": ["create", "atdd", "dev", "test_automate", "test_review", "trace", "review"]},
                "steps": tea_steps_override(),
            }
        )
        payload = self._detect()
        self.assertEqual(payload["recommendedTrack"], "standard")
        self.assertFalse(payload["teaCapable"])
        self.assertTrue(payload["explicitTeaPolicy"])
        self.assertTrue(any("required TEA skills or assets are missing" in note for note in payload["reasons"]))

    def test_detect_workflow_track_rejects_explicit_tea_policy_when_nfr_skill_is_missing(self) -> None:
        install_tea_skills(self.project_root, canonical=True)
        self._write_policy_override(
            {
                "workflow": {
                    "sequence": ["create", "atdd", "dev", "test_automate", "test_review", "nfr", "trace", "review"]
                },
                "steps": tea_steps_override(include_nfr=True),
            }
        )
        payload = self._detect()
        self.assertEqual(payload["recommendedTrack"], "standard")
        self.assertFalse(payload["teaCapable"])
        self.assertTrue(payload["explicitTeaPolicy"])
        self.assertIn("bmad-testarch-nfr", payload["missingSkills"])

    def test_detect_workflow_track_reports_explicit_invalid_custom_asset_root_consistently(self) -> None:
        install_tea_skills(self.project_root, canonical=True, write_assets=False)
        self._write_policy_override(
            {
                "workflow": {"sequence": ["create", "atdd", "dev", "test_automate", "test_review", "trace", "review"]},
                "steps": tea_steps_override(canonical=True, assets_root="missing-custom-root"),
            }
        )
        payload = self._detect()
        self.assertEqual(payload["recommendedTrack"], "standard")
        self.assertFalse(payload["teaCapable"])
        self.assertEqual(payload["assetsRoot"], "missing-custom-root")
        self.assertEqual(payload["missingAssets"], ["missing TEA story-automator assets root"])
        self.assertTrue(any("missing-custom-root" in item for item in payload["reasons"]))

    def test_agents_build_uses_pinned_tea_story_sequence(self) -> None:
        install_tea_skills(self.project_root)
        self._write_policy_override(
            {
                "workflow": {"sequence": ["create", "atdd", "dev", "test_automate", "test_review", "trace", "review"]},
                "steps": tea_steps_override(),
            }
        )
        state_file = self._build_state({"workflowTrack": "tea"})
        complexity_file = self.project_root / "complexity.json"
        complexity_file.write_text(
            json.dumps({"stories": [{"storyId": "1.1", "title": "Story 1", "complexity": {"level": "medium"}}]}),
            encoding="utf-8",
        )
        agents_file = self.project_root / "agents.md"
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(
                [
                    "agents-build",
                    "--state-file",
                    str(state_file),
                    "--complexity-file",
                    str(complexity_file),
                    "--output",
                    str(agents_file),
                    "--config-json",
                    json.dumps({"defaultPrimary": "claude", "defaultFallback": False}),
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        text = agents_file.read_text(encoding="utf-8")
        self.assertIn('"atdd"', text)
        self.assertIn('"test_automate"', text)
        self.assertIn('"test_review"', text)
        self.assertIn('"trace"', text)

    def _detect(self) -> dict[str, object]:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_detect_workflow_track([])
        self.assertEqual(code, 0)
        return json.loads(stdout.getvalue())

    def _write_policy_override(self, payload: dict[str, object]) -> None:
        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "story-automator.policy.json").write_text(json.dumps(payload), encoding="utf-8")

    def _build_state(self, overrides: dict[str, object] | None = None) -> Path:
        stdout = io.StringIO()
        template = self.project_root / ".claude" / "skills" / "bmad-story-automator" / "templates" / "state-document.md"
        config = {
            "epic": "1",
            "epicName": "Epic 1",
            "storyRange": ["1.1"],
            "status": "READY",
            "aiCommand": "claude --dangerously-skip-permissions",
        }
        if overrides:
            config.update(overrides)
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_build_state_doc(
                [
                    "--template",
                    str(template),
                    "--output-folder",
                    str(self.output_dir),
                    "--config-json",
                    json.dumps(config),
                ]
            )
        self.assertEqual(code, 0)
        return Path(json.loads(stdout.getvalue())["path"])


if __name__ == "__main__":
    unittest.main()
