from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from story_automator.commands.orchestrator import cmd_orchestrator_helper
from story_automator.commands.orchestrator_epic_agents import parse_agent_config
from story_automator.commands.state import cmd_build_run_policy, cmd_build_state_doc, cmd_state_metrics
from story_automator.commands.tmux import _build_cmd, cmd_tmux_wrapper
from tests.tea_test_support import (
    install_bundle,
    install_required_skills,
    install_tea_skills,
    patch_env,
    tea_steps_override,
)


class TeaStateRenderingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)
        self.output_dir = self.project_root / "_bmad-output" / "story-automator"
        install_bundle(self.project_root)
        install_required_skills(self.project_root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_build_state_doc_renders_tea_progress_columns_from_pinned_policy(self) -> None:
        install_tea_skills(self.project_root)
        self._write_policy_override(
            {
                "workflow": {"sequence": ["create", "atdd", "dev", "test_automate", "test_review", "trace", "review"]},
                "steps": tea_steps_override(),
            }
        )
        state_file = self._build_state({"workflowTrack": "tea"})
        text = state_file.read_text(encoding="utf-8")
        self.assertIn(
            "| Story | create-story | atdd | dev-story | test-automate | test-review | trace | code-review | git-commit | Status |",
            text,
        )
        self.assertIn("| 1.1 | ⏳ | ⏳ | ⏳ | ⏳ | ⏳ | ⏳ | ⏳ | ⏳ | pending |", text)

    def test_build_run_policy_generates_tea_sequence_with_optional_nfr_and_manual_checkpoint(self) -> None:
        install_tea_skills(self.project_root, include_nfr=True)
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_build_run_policy(
                [
                    "--config-json",
                    json.dumps(
                        {
                            "workflowTrack": "tea",
                            "selectedOptionalSteps": ["nfr", "retro", "qa-generate-e2e-tests", "validate-create-story"],
                            "manualCheckpoints": ["checkpoint-preview"],
                        }
                    ),
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(
            payload["policyOverride"]["workflow"]["sequence"],
            ["create", "atdd", "dev", "test_automate", "test_review", "nfr", "trace", "review", "retro"],
        )
        self.assertEqual(payload["manualCheckpoints"], [])
        self.assertEqual(payload["selectedOptionalSteps"], ["nfr", "retro"])
        self.assertTrue(any("superseded by TEA test_automate" in note for note in payload["notes"]))
        self.assertTrue(any("not yet automated by story-automator" in note for note in payload["notes"]))
        self.assertTrue(any("out of scope for story-automator" in note for note in payload["notes"]))

    def test_build_state_doc_returns_structured_snapshot_error_for_unrunnable_tea_track(self) -> None:
        stdout = io.StringIO()
        template = self.project_root / ".claude" / "skills" / "bmad-story-automator" / "templates" / "state-document.md"
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_build_state_doc(
                [
                    "--template",
                    str(template),
                    "--output-folder",
                    str(self.output_dir),
                    "--config-json",
                    json.dumps({**self._base_config(), "workflowTrack": "tea"}),
                ]
            )
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["error"], "policy_snapshot_failed")

    def test_build_state_doc_snapshots_generated_tea_policy_and_renders_nfr_column(self) -> None:
        install_tea_skills(self.project_root, include_nfr=True)
        state_file = self._build_state(
            {"workflowTrack": "tea", "selectedOptionalSteps": ["nfr"], "manualCheckpoints": ["checkpoint-preview"]}
        )
        text = state_file.read_text(encoding="utf-8")
        self.assertIn('workflowTrack: "tea"', text)
        self.assertIn('selectedOptionalSteps: ["nfr"]', text)
        self.assertIn('manualCheckpoints: []', text)
        self.assertIn("**TEA Configuration:**", text)
        self.assertIn("- Mandatory TEA Core: atdd, test_automate, test_review, trace", text)
        self.assertIn(
            "| Story | create-story | atdd | dev-story | test-automate | test-review | nfr | trace | code-review | git-commit | Status |",
            text,
        )

    def test_build_state_doc_standard_track_ignores_explicit_tea_override_steps(self) -> None:
        install_tea_skills(self.project_root, canonical=True)
        self._write_policy_override(
            {
                "workflow": {
                    "sequence": ["create", "atdd", "dev", "test_automate", "test_review", "nfr", "trace", "review"]
                },
                "steps": tea_steps_override(include_nfr=True),
            }
        )
        state_file = self._build_state({"workflowTrack": "standard"})
        text = state_file.read_text(encoding="utf-8")
        self.assertNotIn("**TEA Configuration:**", text)
        self.assertIn("| Story | create-story | dev-story | automate | code-review | git-commit | Status |", text)

    def test_build_state_doc_legacy_config_stays_standard_despite_explicit_tea_override(self) -> None:
        install_tea_skills(self.project_root, canonical=True)
        self._write_policy_override(
            {
                "workflow": {"sequence": ["create", "atdd", "dev", "test_automate", "test_review", "trace", "review"]},
                "steps": tea_steps_override(),
            }
        )
        state_file = self._build_state()
        text = state_file.read_text(encoding="utf-8")
        self.assertNotIn("**TEA Configuration:**", text)
        self.assertIn("| Story | create-story | dev-story | automate | code-review | git-commit | Status |", text)

    def test_build_state_doc_uses_pinned_standard_override_metadata_for_explicit_policy_override(self) -> None:
        state_file = self._build_state(
            {
                "workflowTrack": "tea",
                "selectedOptionalSteps": ["nfr", "retro"],
                "policyOverride": {"workflow": {"sequence": ["create", "dev", "review"]}},
            }
        )
        text = state_file.read_text(encoding="utf-8")
        self.assertNotIn('workflowTrack: "tea"', text)
        self.assertNotIn("**TEA Configuration:**", text)
        self.assertIn("| Story | create-story | dev-story | code-review | git-commit | Status |", text)

    def test_build_run_policy_uses_canonical_tea_skill_names_when_installed(self) -> None:
        install_tea_skills(self.project_root, include_nfr=True, canonical=True, write_assets=False)
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_build_run_policy(
                ["--config-json", json.dumps({"workflowTrack": "tea", "selectedOptionalSteps": ["nfr"]})]
            )
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["policyOverride"]["steps"]["atdd"]["assets"]["skillName"], "bmad-testarch-atdd")
        self.assertEqual(payload["policyOverride"]["steps"]["test_automate"]["assets"]["skillName"], "bmad-testarch-automate")
        self.assertEqual(
            payload["policyOverride"]["steps"]["test_review"]["assets"]["skillName"], "bmad-testarch-test-review"
        )
        self.assertEqual(payload["policyOverride"]["steps"]["trace"]["assets"]["skillName"], "bmad-testarch-trace")
        self.assertEqual(payload["policyOverride"]["steps"]["nfr"]["assets"]["skillName"], "bmad-testarch-nfr")
        self.assertEqual(
            payload["policyOverride"]["steps"]["atdd"]["prompt"]["templateFile"],
            "data/tea-story-automator/prompts/tea_step.md",
        )
        self.assertEqual(
            payload["policyOverride"]["steps"]["nfr"]["parse"]["schemaFile"],
            "data/tea-story-automator/parse/tea_step.json",
        )

    def test_build_run_policy_normalizes_workflow_track_for_explicit_override(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_build_run_policy(
                [
                    "--config-json",
                    json.dumps({"workflowTrack": "TEA", "policyOverride": {"workflow": {"sequence": ["create", "dev", "review"]}}}),
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["workflowTrack"], "standard")
        self.assertEqual(payload["selectedOptionalSteps"], [])

    def test_build_run_policy_normalizes_selected_optional_steps_for_explicit_override(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_build_run_policy(
                [
                    "--config-json",
                    json.dumps(
                        {
                            "workflowTrack": "TEA",
                            "selectedOptionalSteps": ["NFR", "Retro", None],
                            "policyOverride": {"workflow": {"sequence": ["create", "review"]}},
                        }
                    ),
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["selectedOptionalSteps"], [])

    def test_build_run_policy_ignores_manual_checkpoints_for_explicit_override(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_build_run_policy(
                [
                    "--config-json",
                    json.dumps(
                        {
                            "workflowTrack": "TEA",
                            "manualCheckpoints": ["checkpoint-preview"],
                            "policyOverride": {"workflow": {"sequence": ["create", "review"]}},
                        }
                    ),
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["manualCheckpoints"], [])
        self.assertIn("checkpoint-preview is out of scope", payload["notes"][0])

    def test_build_run_policy_rejects_invalid_explicit_override(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_build_run_policy(
                [
                    "--config-json",
                    json.dumps({"workflowTrack": "TEA", "policyOverride": {"workflow": {"sequence": ["create", "ship"]}}}),
                ]
            )
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["error"], "policy_invalid")

    def test_build_run_policy_distinguishes_invalid_json_from_missing_config(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_build_run_policy(["--config-json", "{"])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["error"], "invalid_config_json")

    def test_build_run_policy_rejects_non_object_json(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_build_run_policy(["--config-json", "[]"])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["error"], "config_must_be_object")

    def test_build_run_policy_drops_nfr_when_nfr_skill_is_missing(self) -> None:
        install_tea_skills(self.project_root, canonical=True, write_assets=False)
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_build_run_policy(["--config-json", json.dumps({"workflowTrack": "tea", "selectedOptionalSteps": ["nfr"]})])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(
            payload["policyOverride"]["workflow"]["sequence"],
            ["create", "atdd", "dev", "test_automate", "test_review", "trace", "review"],
        )
        self.assertNotIn("nfr", payload["policyOverride"]["steps"])
        self.assertEqual(payload["selectedOptionalSteps"], [])
        self.assertTrue(any("TEA NFR skill is not installed" in note for note in payload["notes"]))

    def test_build_run_policy_normalizes_selected_optional_steps_on_tea_track(self) -> None:
        install_tea_skills(self.project_root, include_nfr=True, canonical=True, write_assets=False)
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_build_run_policy(
                [
                    "--config-json",
                    json.dumps({"workflowTrack": "TEA", "selectedOptionalSteps": ["NFR", "Retro", None]}),
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(
            payload["policyOverride"]["workflow"]["sequence"],
            ["create", "atdd", "dev", "test_automate", "test_review", "nfr", "trace", "review", "retro"],
        )
        self.assertEqual(payload["selectedOptionalSteps"], ["nfr", "retro"])

    def test_state_progress_updates_named_columns_in_tea_table(self) -> None:
        install_tea_skills(self.project_root, include_nfr=True)
        state_file = self._build_state({"workflowTrack": "tea", "selectedOptionalSteps": ["nfr"]})
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(
                [
                    "state-progress",
                    str(state_file),
                    "--story",
                    "1.1",
                    "--set",
                    "atdd=done",
                    "--set",
                    "nfr=done",
                    "--set",
                    "status=in-progress",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        text = state_file.read_text(encoding="utf-8")
        self.assertIn("| 1.1 | ⏳ | done | ⏳ | ⏳ | ⏳ | done | ⏳ | ⏳ | ⏳ | in-progress |", text)

    def test_state_progress_rejects_invalid_set_argument(self) -> None:
        state_file = self._build_state()
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["state-progress", str(state_file), "--story", "1.1", "--set", "status"])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["error"], "invalid_set_argument")
        self.assertEqual(payload["argument"], "status")

    def test_state_progress_rejects_story_column_updates(self) -> None:
        state_file = self._build_state()
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["state-progress", str(state_file), "--story", "1.1", "--set", "story=1.2"])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["error"], "story_column_immutable")

    def test_state_progress_returns_structured_error_when_state_file_is_unreadable(self) -> None:
        state_file = self._build_state()
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            with patch("story_automator.core.state_document.read_text", side_effect=OSError("permission denied")):
                code = cmd_orchestrator_helper(
                    ["state-progress", str(state_file), "--story", "1.1", "--set", "status=done"]
                )
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["error"], "state_file_unreadable")

    def test_state_progress_returns_structured_error_when_state_file_stat_is_unreadable(self) -> None:
        state_file = self._build_state()
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            with patch("story_automator.commands.orchestrator.file_exists", side_effect=PermissionError("permission denied")):
                code = cmd_orchestrator_helper(
                    ["state-progress", str(state_file), "--story", "1.1", "--set", "status=done"]
                )
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["error"], "state_file_unreadable")

    def test_state_progress_returns_structured_error_when_state_file_is_unwritable(self) -> None:
        state_file = self._build_state()
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            with patch("pathlib.Path.write_text", side_effect=OSError("permission denied")):
                code = cmd_orchestrator_helper(
                    ["state-progress", str(state_file), "--story", "1.1", "--set", "status=done"]
                )
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["error"], "state_file_unwritable")

    def test_state_metrics_skips_markdown_divider_row(self) -> None:
        state_file = self.project_root / "metrics-state.md"
        state_file.write_text(
            "\n".join(
                [
                    "---",
                    "epic: 1",
                    "---",
                    "| Story | create-story | Status |",
                    "|-------\t|--------------|--------|",
                    "| 1.1 | done | pending |",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_state_metrics(["--state", str(state_file)])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["storiesCompleted"], 0)

    def test_build_state_doc_keeps_standard_summary_shape_unchanged(self) -> None:
        state_file = self._build_state()
        text = state_file.read_text(encoding="utf-8")
        self.assertNotIn("**TEA Configuration:**", text)
        self.assertNotIn("Workflow Track:", text)
        self.assertNotIn("Optional Steps:", text)
        self.assertNotIn("Manual Checkpoints:", text)

    def test_build_cmd_rejects_unknown_step_via_policy(self) -> None:
        stderr = io.StringIO()
        with patch_env(self.project_root), redirect_stderr(stderr):
            code = _build_cmd(["ship", "1.1"])
        self.assertEqual(code, 1)
        self.assertIn("unknown step: ship", stderr.getvalue())

    def test_build_cmd_help_mentions_state_file(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = cmd_tmux_wrapper(["build-cmd", "--help"])
        self.assertEqual(code, 0)
        self.assertIn("--state-file", stdout.getvalue())

    def test_parse_agent_config_keeps_default_fallback_false(self) -> None:
        payload = parse_agent_config(json.dumps({"defaultPrimary": "auto", "defaultFallback": False}))
        self.assertEqual(payload["defaultFallback"], "false")

    def _write_policy_override(self, payload: dict[str, object]) -> None:
        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "story-automator.policy.json").write_text(json.dumps(payload), encoding="utf-8")

    def _build_state(self, overrides: dict[str, object] | None = None) -> Path:
        stdout = io.StringIO()
        template = self.project_root / ".claude" / "skills" / "bmad-story-automator" / "templates" / "state-document.md"
        config = self._base_config()
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

    def _base_config(self) -> dict[str, object]:
        return {
            "epic": "1",
            "epicName": "Epic 1",
            "storyRange": ["1.1"],
            "status": "READY",
            "aiCommand": "claude --dangerously-skip-permissions",
        }


if __name__ == "__main__":
    unittest.main()
