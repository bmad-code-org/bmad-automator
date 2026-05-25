from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from story_automator.commands.orchestrator_epic_agents import parse_agent_config
from story_automator.commands.orchestrator import cmd_orchestrator_helper
from story_automator.commands.state import cmd_build_run_policy, cmd_build_state_doc, cmd_detect_workflow_track, cmd_validate_state
from story_automator.commands.tmux import _build_cmd, cmd_tmux_wrapper


REPO_ROOT = Path(__file__).resolve().parents[1]


class StatePolicyMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)
        self.output_dir = self.project_root / "_bmad-output" / "story-automator"
        self._install_bundle()
        self._install_required_skills()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_state_doc_writes_policy_metadata(self) -> None:
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
                    json.dumps(self._config()),
                ]
            )
        self.assertEqual(code, 0)
        state_file = Path(json.loads(stdout.getvalue())["path"])
        text = state_file.read_text(encoding="utf-8")
        self.assertIn("policySnapshotFile:", text)
        self.assertIn("policySnapshotHash:", text)

    def test_summary_surfaces_policy_metadata(self) -> None:
        state_file = self._build_state()
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["state-summary", str(state_file)])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["policySnapshotFile"])
        self.assertTrue(payload["policySnapshotHash"])

    def test_legacy_state_without_policy_metadata_remains_valid(self) -> None:
        legacy = self.project_root / "legacy.md"
        legacy.write_text(
            "---\nepic: \"1\"\nepicName: \"Epic 1\"\nstoryRange: [\"1.1\"]\nstatus: \"READY\"\nlastUpdated: \"2026-04-13T00:00:00Z\"\naiCommand: \"claude\"\n---\n",
            encoding="utf-8",
        )
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_state(["--state", str(legacy)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["structure"], "ok")

    def test_validate_state_accepts_agent_config_without_legacy_ai_command(self) -> None:
        stdout = io.StringIO()
        template = self.project_root / ".claude" / "skills" / "bmad-story-automator" / "templates" / "state-document.md"
        config = self._config()
        config.pop("aiCommand", None)
        config["agentConfig"] = {"defaultPrimary": "auto", "defaultFallback": False}
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
        state_file = Path(json.loads(stdout.getvalue())["path"])
        text = state_file.read_text(encoding="utf-8")
        self.assertIn('aiCommand: ""', text)
        self.assertIn('agentConfig:\n  defaultPrimary: "auto"\n  defaultFallback: false\n', text)

        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_state(["--state", str(state_file)])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["structure"], "ok")
        self.assertFalse(any("aiCommand" in issue for issue in payload["issues"]))

    def test_validate_state_rejects_state_without_runtime_command_config(self) -> None:
        state_file = self.project_root / "missing-runtime-config.md"
        state_file.write_text(
            "---\nepic: \"1\"\nepicName: \"Epic 1\"\nstoryRange: [\"1.1\"]\nstatus: \"READY\"\nlastUpdated: \"2026-04-13T00:00:00Z\"\naiCommand: \"\"\n---\n",
            encoding="utf-8",
        )
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_state(["--state", str(state_file)])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["structure"], "issues")
        self.assertIn("Missing or empty aiCommand", payload["issues"])

    def test_summary_infers_legacy_policy_for_old_state(self) -> None:
        legacy = self.project_root / "legacy.md"
        legacy.write_text(
            "---\nepic: \"1\"\nepicName: \"Epic 1\"\nstoryRange: [\"1.1\"]\nstatus: \"READY\"\nlastUpdated: \"2026-04-13T00:00:00Z\"\naiCommand: \"claude\"\n---\n",
            encoding="utf-8",
        )
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["state-summary", str(legacy)])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["policySnapshotFile"], "")
        self.assertEqual(payload["policySnapshotHash"], "")
        self.assertEqual(payload["legacyPolicy"], "true")

    def test_validate_state_rejects_new_state_with_missing_snapshot(self) -> None:
        state_file = self.project_root / "orchestration.md"
        state_file.write_text(
            "---\nepic: \"1\"\nepicName: \"Epic 1\"\nstoryRange: [\"1.1\"]\nstatus: \"READY\"\nlastUpdated: \"2026-04-13T00:00:00Z\"\naiCommand: \"claude\"\npolicySnapshotFile: \"_bmad-output/story-automator/snapshots/missing.json\"\npolicySnapshotHash: \"deadbeef\"\n---\n",
            encoding="utf-8",
        )
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_state(["--state", str(state_file)])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["structure"], "issues")
        self.assertTrue(any("policy snapshot missing" in issue for issue in payload["issues"]))

    def test_validate_state_rejects_new_state_missing_snapshot_metadata(self) -> None:
        state_file = self.project_root / "orchestration.md"
        state_file.write_text(
            "---\nepic: \"1\"\nepicName: \"Epic 1\"\nstoryRange: [\"1.1\"]\nstatus: \"READY\"\nlastUpdated: \"2026-04-13T00:00:00Z\"\naiCommand: \"claude\"\npolicyVersion: 1\nlegacyPolicy: false\n---\n",
            encoding="utf-8",
        )
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_state(["--state", str(state_file)])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["structure"], "issues")
        self.assertTrue(any("state policy snapshot missing" in issue for issue in payload["issues"]))

    def test_summary_does_not_infer_legacy_for_new_state_missing_snapshot_metadata(self) -> None:
        state_file = self.project_root / "orchestration.md"
        state_file.write_text(
            "---\nepic: \"1\"\nepicName: \"Epic 1\"\nstoryRange: [\"1.1\"]\nstatus: \"READY\"\nlastUpdated: \"2026-04-13T00:00:00Z\"\naiCommand: \"claude\"\npolicyVersion: 1\n---\n",
            encoding="utf-8",
        )
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["state-summary", str(state_file)])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["legacyPolicy"], "false")

    def test_summary_does_not_mark_contradictory_legacy_flag_as_legacy(self) -> None:
        state_file = self.project_root / "orchestration.md"
        state_file.write_text(
            "---\nepic: \"1\"\nepicName: \"Epic 1\"\nstoryRange: [\"1.1\"]\nstatus: \"READY\"\nlastUpdated: \"2026-04-13T00:00:00Z\"\naiCommand: \"claude\"\npolicyVersion: 1\nlegacyPolicy: true\n---\n",
            encoding="utf-8",
        )
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["state-summary", str(state_file)])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["legacyPolicy"], "false")
        self.assertEqual(payload["policyError"], "state policy snapshot missing")

    def test_summary_clears_contradictory_snapshot_metadata(self) -> None:
        state_file = self.project_root / "orchestration.md"
        state_file.write_text(
            "---\npolicySnapshotFile: \"snap.json\"\npolicySnapshotHash: \"deadbeef\"\nlegacyPolicy: true\n---\n",
            encoding="utf-8",
        )
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["state-summary", str(state_file)])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["policySnapshotFile"], "")
        self.assertEqual(payload["policySnapshotHash"], "")
        self.assertEqual(payload["legacyPolicy"], "false")
        self.assertEqual(payload["policyError"], "state policy metadata contradictory")

    def test_summary_clears_incomplete_snapshot_metadata(self) -> None:
        state_file = self.project_root / "orchestration.md"
        state_file.write_text(
            "---\npolicySnapshotFile: \"snap.json\"\n---\n",
            encoding="utf-8",
        )
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["state-summary", str(state_file)])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["policySnapshotFile"], "")
        self.assertEqual(payload["policySnapshotHash"], "")
        self.assertEqual(payload["legacyPolicy"], "false")
        self.assertEqual(payload["policyError"], "state policy metadata incomplete")

    def test_summary_reports_missing_snapshot_reference(self) -> None:
        state_file = self.project_root / "orchestration.md"
        state_file.write_text(
            "---\npolicySnapshotFile: \"missing.json\"\npolicySnapshotHash: \"deadbeef\"\n---\n",
            encoding="utf-8",
        )
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["state-summary", str(state_file)])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["policySnapshotFile"], "")
        self.assertEqual(payload["policySnapshotHash"], "")
        self.assertIn("policy snapshot missing", payload["policyError"])

    def test_summary_reports_snapshot_hash_mismatch(self) -> None:
        state_file = self._build_state()
        lines = []
        for line in state_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("policySnapshotHash: "):
                lines.append('policySnapshotHash: "deadbeef"')
            else:
                lines.append(line)
        state_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["state-summary", str(state_file)])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["policySnapshotFile"], "")
        self.assertEqual(payload["policySnapshotHash"], "")
        self.assertIn("policy snapshot hash mismatch", payload["policyError"])

    def test_summary_uses_runtime_root_for_relative_snapshot_validation(self) -> None:
        outside = self.project_root.parent / "outside-state"
        outside.mkdir(parents=True, exist_ok=True)
        shadow = outside / "snap.json"
        shadow.write_text("{}", encoding="utf-8")
        state_file = outside / "orchestration.md"
        state_file.write_text(
            "---\npolicySnapshotFile: \"snap.json\"\npolicySnapshotHash: \"99999999\"\n---\n",
            encoding="utf-8",
        )
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["state-summary", str(state_file)])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["policySnapshotFile"], "")
        self.assertEqual(payload["policySnapshotHash"], "")
        self.assertIn("policy snapshot missing", payload["policyError"])

    def test_escalate_uses_pinned_snapshot_when_state_file_provided(self) -> None:
        state_file = self._build_state()
        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "story-automator.policy.json").write_text(
            json.dumps({"workflow": {"repeat": {"review": {"maxCycles": 1}}}}),
            encoding="utf-8",
        )
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["escalate", "review-loop", "cycles=2", "--state-file", str(state_file)])
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(stdout.getvalue())["escalate"])

    def test_escalate_returns_json_when_state_snapshot_is_invalid(self) -> None:
        state_file = self.project_root / "orchestration.md"
        state_file.write_text(
            "---\npolicySnapshotFile: \"missing.json\"\npolicySnapshotHash: \"deadbeef\"\n---\n",
            encoding="utf-8",
        )
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["escalate", "review-loop", "cycles=1", "--state-file", str(state_file)])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["escalate"])
        self.assertIn("policy snapshot missing", payload["reason"])

    def test_build_cmd_does_not_treat_state_file_flag_as_prompt_text(self) -> None:
        state_file = self._build_state()
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = _build_cmd(["review", "1.1", "--state-file", str(state_file)])
        self.assertEqual(code, 0)
        rendered = stdout.getvalue()
        self.assertNotIn("--state-file", rendered)
        self.assertNotIn(str(state_file), rendered)

    def test_build_cmd_rejects_incomplete_state_file_flag(self) -> None:
        stderr = io.StringIO()
        with patch_env(self.project_root), redirect_stderr(stderr):
            code = _build_cmd(["review", "1.1", "--state-file"])
        self.assertEqual(code, 1)
        self.assertIn("--state-file requires a value", stderr.getvalue())

    def test_build_cmd_returns_exit_code_one_when_prompt_template_is_missing(self) -> None:
        state_file = self._build_state()
        template = self.project_root / ".claude" / "skills" / "bmad-story-automator" / "data" / "prompts" / "review.md"
        template.unlink()
        stderr = io.StringIO()
        with patch_env(self.project_root), redirect_stderr(stderr):
            code = _build_cmd(["review", "1.1", "--state-file", str(state_file)])
        self.assertEqual(code, 1)
        self.assertIn("review.md", stderr.getvalue())

    def test_build_cmd_supports_codex_retro_prompt(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = _build_cmd(["retro", "2", "--agent", "codex"])
        self.assertEqual(code, 0)
        rendered = stdout.getvalue()
        self.assertIn('CODEX_HOME="/tmp/sa-codex-home-', rendered)
        self.assertIn("codex exec -s workspace-write", rendered)
        self.assertIn("Execute the BMAD retrospective workflow for epic 2.", rendered)

    def test_build_cmd_uses_legacy_ai_command_consistently_for_claude(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root, extra={"AI_COMMAND": "claude --print"}), redirect_stdout(stdout):
            code = _build_cmd(["review", "1.2"])
        self.assertEqual(code, 0)
        rendered = stdout.getvalue()
        self.assertIn("unset CLAUDECODE && claude --print", rendered)

    def test_retro_agent_uses_per_task_override_from_state(self) -> None:
        state_file = self.project_root / "retro-state.md"
        state_file.write_text(
            "---\nagentConfig:\n  defaultPrimary: \"claude\"\n  defaultFallback: \"codex\"\n  perTask:\n    retro:\n      primary: \"codex\"\n      fallback: false\n---\n",
            encoding="utf-8",
        )
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["retro-agent", "--state-file", str(state_file)])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["primary"], "codex")
        self.assertEqual(payload["fallback"], "false")

    def test_parse_agent_config_ignores_null_per_task(self) -> None:
        config = parse_agent_config(
            json.dumps(
                {
                    "defaultPrimary": "codex",
                    "defaultFallback": "claude",
                    "perTask": None,
                    "retro": {"primary": "claude", "fallback": False},
                }
            )
        )

        self.assertEqual(config["perTask"]["retro"]["primary"], "claude")
        self.assertEqual(config["perTask"]["retro"]["fallback"], False)

    def test_parse_agent_config_disables_fallback_when_missing(self) -> None:
        config = parse_agent_config(json.dumps({}))

        self.assertEqual(config["defaultFallback"], "false")

    def test_parse_agent_config_disables_fallback_for_primary_only(self) -> None:
        config = parse_agent_config(json.dumps({"defaultPrimary": "claude"}))

        self.assertEqual(config["defaultFallback"], "false")

    def test_parse_agent_config_keeps_explicit_disabled_fallback(self) -> None:
        config = parse_agent_config(json.dumps({"defaultPrimary": "claude", "defaultFallback": False}))

        self.assertEqual(config["defaultFallback"], "false")

    def test_retro_agent_inherits_default_primary_when_unset(self) -> None:
        state_file = self.project_root / "retro-default-state.md"
        state_file.write_text(
            "---\nagentConfig:\n  defaultPrimary: \"codex\"\n  defaultFallback: \"claude\"\n---\n",
            encoding="utf-8",
        )
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["retro-agent", "--state-file", str(state_file)])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["primary"], "codex")
        self.assertEqual(payload["fallback"], "claude")

    def test_build_state_doc_coerces_null_default_fallback_to_false(self) -> None:
        state_file = self._build_state({"agentConfig": {"defaultPrimary": "codex", "defaultFallback": None}})

        self.assertIn("defaultFallback: false", state_file.read_text(encoding="utf-8"))

    def test_build_state_doc_coerces_null_default_primary_to_auto(self) -> None:
        state_file = self._build_state({"agentConfig": {"defaultPrimary": None, "defaultFallback": False}})

        self.assertIn('defaultPrimary: "auto"', state_file.read_text(encoding="utf-8"))

    def test_build_cmd_returns_exit_code_one_when_prompt_template_becomes_directory(self) -> None:
        state_file = self._build_state()
        template = self.project_root / ".claude" / "skills" / "bmad-story-automator" / "data" / "prompts" / "review.md"
        template.unlink()
        template.mkdir()
        stderr = io.StringIO()
        with patch_env(self.project_root), redirect_stderr(stderr):
            code = _build_cmd(["review", "1.1", "--state-file", str(state_file)])
        self.assertEqual(code, 1)
        self.assertIn("review.md", stderr.getvalue())

    def test_tmux_subcommand_help_matches_step_preflight_contract(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = cmd_tmux_wrapper(["spawn", "--help"])
        self.assertEqual(code, 0)
        self.assertIn("--command", stdout.getvalue())

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = cmd_tmux_wrapper(["build-cmd", "--help"])
        self.assertEqual(code, 0)
        self.assertIn("--state-file", stdout.getvalue())

    def test_build_state_doc_returns_json_on_policy_snapshot_failure(self) -> None:
        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "story-automator.policy.json").write_text(
            json.dumps({"snapshot": {"relativeDir": "../outside"}}),
            encoding="utf-8",
        )
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
                    json.dumps(self._config()),
                ]
            )
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "policy_snapshot_failed")

    def test_build_state_doc_renders_tea_progress_columns_from_pinned_policy(self) -> None:
        self._install_tea_skills()
        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "story-automator.policy.json").write_text(
            json.dumps(
                {
                    "workflow": {"sequence": ["create", "atdd", "dev", "test_automate", "test_review", "trace", "review"]},
                    "steps": _tea_steps_override(self.project_root),
                }
            ),
            encoding="utf-8",
        )
        state_file = self._build_state({"workflowTrack": "tea"})
        text = state_file.read_text(encoding="utf-8")
        self.assertIn("| Story | create-story | atdd | dev-story | test-automate | test-review | trace | code-review | git-commit | Status |", text)
        self.assertIn("| 1.1 | ⏳ | ⏳ | ⏳ | ⏳ | ⏳ | ⏳ | ⏳ | ⏳ | pending |", text)

    def test_build_run_policy_generates_tea_sequence_with_optional_nfr_and_manual_checkpoint(self) -> None:
        self._install_tea_skills(include_nfr=True)
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

    def test_detect_workflow_track_recommends_tea_when_project_is_capable(self) -> None:
        self._install_tea_skills()
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_detect_workflow_track([])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["recommendedTrack"], "tea")
        self.assertTrue(payload["requiresConfirmation"])
        self.assertTrue(payload["teaCapable"])
        self.assertIn("Detected TEA support for this project", payload["prompt"])

    def test_detect_workflow_track_accepts_canonical_tea_skill_names(self) -> None:
        self._install_tea_skills(canonical=True)
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_detect_workflow_track([])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
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
        self._install_tea_skills(canonical=True, write_assets=False)
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_detect_workflow_track([])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["recommendedTrack"], "tea")
        self.assertTrue(payload["teaCapable"])
        self.assertEqual(payload["assetsRoot"], "data/tea-story-automator")
        self.assertEqual(payload["missingAssets"], [])

    def test_detect_workflow_track_falls_back_when_project_tea_assets_are_incomplete(self) -> None:
        self._install_tea_skills(canonical=True, write_assets=False)
        incomplete_dir = self.project_root / "_bmad" / "tea" / "story-automator" / "prompts"
        incomplete_dir.mkdir(parents=True, exist_ok=True)
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_detect_workflow_track([])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["recommendedTrack"], "tea")
        self.assertTrue(payload["teaCapable"])
        self.assertEqual(payload["assetsRoot"], "data/tea-story-automator")
        self.assertEqual(payload["missingAssets"], [])

    def test_detect_workflow_track_stays_standard_when_skills_are_missing(self) -> None:
        _write_tea_assets(self.project_root)
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_detect_workflow_track([])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["recommendedTrack"], "standard")
        self.assertFalse(payload["teaCapable"])
        self.assertTrue(payload["missingSkills"])

    def test_detect_workflow_track_honors_explicit_tea_policy(self) -> None:
        self._install_tea_skills()
        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "story-automator.policy.json").write_text(
            json.dumps(
                {
                    "workflow": {"sequence": ["create", "atdd", "dev", "test_automate", "test_review", "trace", "review"]},
                    "steps": _tea_steps_override(self.project_root),
                }
            ),
            encoding="utf-8",
        )
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_detect_workflow_track([])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["recommendedTrack"], "tea")
        self.assertFalse(payload["requiresConfirmation"])
        self.assertTrue(payload["explicitTeaPolicy"])

    def test_detect_workflow_track_trusts_valid_explicit_tea_policy_with_custom_asset_root(self) -> None:
        self._install_tea_skills(canonical=True, write_assets=False)
        custom_root = self.project_root / "custom-tea-assets"
        _write_tea_assets(self.project_root, root=custom_root)
        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        override_steps = _tea_steps_override(self.project_root, canonical=True, assets_root="custom-tea-assets")
        (override_dir / "story-automator.policy.json").write_text(
            json.dumps(
                {
                    "workflow": {"sequence": ["create", "atdd", "dev", "test_automate", "test_review", "trace", "review"]},
                    "steps": override_steps,
                }
            ),
            encoding="utf-8",
        )
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_detect_workflow_track([])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
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

    def test_detect_workflow_track_rejects_explicit_tea_policy_missing_step_contract(self) -> None:
        self._install_tea_skills(canonical=True)
        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "story-automator.policy.json").write_text(
            json.dumps(
                {
                    "workflow": {"sequence": ["create", "atdd", "dev", "review"]},
                    "steps": {},
                }
            ),
            encoding="utf-8",
        )
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_detect_workflow_track([])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["recommendedTrack"], "standard")
        self.assertFalse(payload["teaCapable"])
        self.assertTrue(any("workflow.sequence references missing step: atdd" in note for note in payload["reasons"]))

    def test_detect_workflow_track_rejects_explicit_tea_policy_when_skills_missing(self) -> None:
        _write_tea_assets(self.project_root)
        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "story-automator.policy.json").write_text(
            json.dumps(
                {
                    "workflow": {"sequence": ["create", "atdd", "dev", "test_automate", "test_review", "trace", "review"]},
                    "steps": _tea_steps_override(self.project_root),
                }
            ),
            encoding="utf-8",
        )
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_detect_workflow_track([])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["recommendedTrack"], "standard")
        self.assertFalse(payload["teaCapable"])
        self.assertTrue(payload["explicitTeaPolicy"])
        self.assertTrue(any("required TEA skills or assets are missing" in note for note in payload["reasons"]))

    def test_detect_workflow_track_rejects_explicit_tea_policy_when_nfr_skill_is_missing(self) -> None:
        self._install_tea_skills(canonical=True)
        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "story-automator.policy.json").write_text(
            json.dumps(
                {
                    "workflow": {"sequence": ["create", "atdd", "dev", "test_automate", "test_review", "nfr", "trace", "review"]},
                    "steps": _tea_steps_override(self.project_root, include_nfr=True),
                }
            ),
            encoding="utf-8",
        )
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_detect_workflow_track([])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["recommendedTrack"], "standard")
        self.assertFalse(payload["teaCapable"])
        self.assertTrue(payload["explicitTeaPolicy"])
        self.assertIn("bmad-testarch-nfr", payload["missingSkills"])

    def test_build_state_doc_snapshots_generated_tea_policy_and_renders_nfr_column(self) -> None:
        self._install_tea_skills(include_nfr=True)
        state_file = self._build_state(
            {
                "workflowTrack": "tea",
                "selectedOptionalSteps": ["nfr"],
                "manualCheckpoints": ["checkpoint-preview"],
            }
        )
        text = state_file.read_text(encoding="utf-8")
        self.assertIn('workflowTrack: "tea"', text)
        self.assertIn('selectedOptionalSteps: ["nfr"]', text)
        self.assertIn('manualCheckpoints: []', text)
        self.assertIn("**TEA Configuration:**", text)
        self.assertIn("- Mandatory TEA Core: atdd, test_automate, test_review, trace", text)
        self.assertIn("| Story | create-story | atdd | dev-story | test-automate | test-review | nfr | trace | code-review | git-commit | Status |", text)

    def test_build_state_doc_standard_track_ignores_explicit_tea_override_steps(self) -> None:
        self._install_tea_skills(canonical=True)
        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "story-automator.policy.json").write_text(
            json.dumps(
                {
                    "workflow": {"sequence": ["create", "atdd", "dev", "test_automate", "test_review", "nfr", "trace", "review"]},
                    "steps": _tea_steps_override(self.project_root, include_nfr=True),
                }
            ),
            encoding="utf-8",
        )
        state_file = self._build_state({"workflowTrack": "standard"})
        text = state_file.read_text(encoding="utf-8")
        self.assertNotIn("**TEA Configuration:**", text)
        self.assertIn("| Story | create-story | dev-story | automate | code-review | git-commit | Status |", text)

    def test_build_state_doc_legacy_config_stays_standard_despite_explicit_tea_override(self) -> None:
        self._install_tea_skills(canonical=True)
        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "story-automator.policy.json").write_text(
            json.dumps(
                {
                    "workflow": {"sequence": ["create", "atdd", "dev", "test_automate", "test_review", "trace", "review"]},
                    "steps": _tea_steps_override(self.project_root),
                }
            ),
            encoding="utf-8",
        )
        state_file = self._build_state()
        text = state_file.read_text(encoding="utf-8")
        self.assertNotIn("**TEA Configuration:**", text)
        self.assertIn("| Story | create-story | dev-story | automate | code-review | git-commit | Status |", text)

    def test_build_run_policy_uses_canonical_tea_skill_names_when_installed(self) -> None:
        self._install_tea_skills(include_nfr=True, canonical=True, write_assets=False)
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_build_run_policy(
                [
                    "--config-json",
                    json.dumps(
                        {
                            "workflowTrack": "tea",
                            "selectedOptionalSteps": ["nfr"],
                        }
                    ),
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["policyOverride"]["steps"]["atdd"]["assets"]["skillName"], "bmad-testarch-atdd")
        self.assertEqual(payload["policyOverride"]["steps"]["test_automate"]["assets"]["skillName"], "bmad-testarch-automate")
        self.assertEqual(payload["policyOverride"]["steps"]["test_review"]["assets"]["skillName"], "bmad-testarch-test-review")
        self.assertEqual(payload["policyOverride"]["steps"]["trace"]["assets"]["skillName"], "bmad-testarch-trace")
        self.assertEqual(payload["policyOverride"]["steps"]["nfr"]["assets"]["skillName"], "bmad-testarch-nfr")
        self.assertEqual(payload["policyOverride"]["steps"]["atdd"]["prompt"]["templateFile"], "data/tea-story-automator/prompts/tea_step.md")
        self.assertEqual(payload["policyOverride"]["steps"]["nfr"]["parse"]["schemaFile"], "data/tea-story-automator/parse/tea_step.json")

    def test_build_run_policy_normalizes_workflow_track_for_explicit_override(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_build_run_policy(
                [
                    "--config-json",
                    json.dumps(
                        {
                            "workflowTrack": "TEA",
                            "policyOverride": {"workflow": {"sequence": ["create", "dev", "review"]}},
                        }
                    ),
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["workflowTrack"], "tea")

    def test_build_run_policy_drops_nfr_when_nfr_skill_is_missing(self) -> None:
        self._install_tea_skills(canonical=True, write_assets=False)
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_build_run_policy(
                [
                    "--config-json",
                    json.dumps(
                        {
                            "workflowTrack": "tea",
                            "selectedOptionalSteps": ["nfr"],
                        }
                    ),
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(
            payload["policyOverride"]["workflow"]["sequence"],
            ["create", "atdd", "dev", "test_automate", "test_review", "trace", "review"],
        )
        self.assertNotIn("nfr", payload["policyOverride"]["steps"])
        self.assertEqual(payload["selectedOptionalSteps"], [])
        self.assertTrue(any("TEA NFR skill is not installed" in note for note in payload["notes"]))

    def test_state_progress_updates_named_columns_in_tea_table(self) -> None:
        self._install_tea_skills(include_nfr=True)
        state_file = self._build_state(
            {
                "workflowTrack": "tea",
                "selectedOptionalSteps": ["nfr"],
            }
        )
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
            code = cmd_orchestrator_helper(
                [
                    "state-progress",
                    str(state_file),
                    "--story",
                    "1.1",
                    "--set",
                    "status",
                ]
            )
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["error"], "invalid_set_argument")
        self.assertEqual(payload["argument"], "status")

    def test_build_state_doc_keeps_standard_summary_shape_unchanged(self) -> None:
        state_file = self._build_state()
        text = state_file.read_text(encoding="utf-8")
        self.assertNotIn("**TEA Configuration:**", text)
        self.assertNotIn("Workflow Track:", text)
        self.assertNotIn("Optional Steps:", text)
        self.assertNotIn("Manual Checkpoints:", text)

    def test_agents_build_uses_pinned_tea_story_sequence(self) -> None:
        self._install_tea_skills()
        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "story-automator.policy.json").write_text(
            json.dumps(
                {
                    "workflow": {"sequence": ["create", "atdd", "dev", "test_automate", "test_review", "trace", "review"]},
                    "steps": _tea_steps_override(self.project_root),
                }
            ),
            encoding="utf-8",
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

    def test_build_cmd_rejects_unknown_step_via_policy(self) -> None:
        stderr = io.StringIO()
        with patch_env(self.project_root), redirect_stderr(stderr):
            code = _build_cmd(["ship", "1.1"])
        self.assertEqual(code, 1)
        self.assertIn("unknown step: ship", stderr.getvalue())

    def test_escalate_returns_json_on_incomplete_state_file_flag(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["escalate", "review-loop", "cycles=1", "--state-file"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["escalate"])
        self.assertEqual(payload["reason"], "--state-file requires a value")

    def _build_state(self, overrides: dict[str, object] | None = None) -> Path:
        stdout = io.StringIO()
        template = self.project_root / ".claude" / "skills" / "bmad-story-automator" / "templates" / "state-document.md"
        config = self._config()
        if overrides:
            config.update(overrides)
        with patch_env(self.project_root), redirect_stdout(stdout):
            cmd_build_state_doc(
                [
                    "--template",
                    str(template),
                    "--output-folder",
                    str(self.output_dir),
                    "--config-json",
                    json.dumps(config),
                ]
            )
        return Path(json.loads(stdout.getvalue())["path"])

    def _config(self) -> dict[str, object]:
        return {
            "epic": "1",
            "epicName": "Epic 1",
            "storyRange": ["1.1"],
            "status": "READY",
            "aiCommand": "claude --dangerously-skip-permissions",
        }

    def _install_bundle(self) -> None:
        source_skill = REPO_ROOT / "skills" / "bmad-story-automator"
        source_review = REPO_ROOT / "skills" / "bmad-story-automator-review"
        target_root = self.project_root / ".claude" / "skills"
        target_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_skill, target_root / "bmad-story-automator")
        shutil.copytree(source_review, target_root / "bmad-story-automator-review")

    def _install_required_skills(self) -> None:
        for name in ("bmad-create-story", "bmad-dev-story", "bmad-retrospective", "bmad-qa-generate-e2e-tests"):
            skill_dir = self.project_root / ".claude" / "skills" / name
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
            (skill_dir / "workflow.md").write_text(f"# {name}\n", encoding="utf-8")
        (self.project_root / ".claude" / "skills" / "bmad-create-story" / "discover-inputs.md").write_text("# discover\n", encoding="utf-8")
        (self.project_root / ".claude" / "skills" / "bmad-create-story" / "checklist.md").write_text("# checklist\n", encoding="utf-8")
        (self.project_root / ".claude" / "skills" / "bmad-create-story" / "template.md").write_text("# template\n", encoding="utf-8")
        (self.project_root / ".claude" / "skills" / "bmad-dev-story" / "checklist.md").write_text("# checklist\n", encoding="utf-8")
        (self.project_root / ".claude" / "skills" / "bmad-qa-generate-e2e-tests" / "checklist.md").write_text("# checklist\n", encoding="utf-8")

    def _install_tea_skills(self, *, include_nfr: bool = False, canonical: bool = False, write_assets: bool = True) -> None:
        if write_assets:
            _write_tea_assets(self.project_root)
        else:
            (self.project_root / "_bmad" / "tea" / "workflows" / "testarch").mkdir(parents=True, exist_ok=True)
        prefix = "bmad-testarch" if canonical else "bmad-tea-testarch"
        names = [
            f"{prefix}-atdd",
            f"{prefix}-automate",
            f"{prefix}-test-review",
            f"{prefix}-trace",
        ]
        if include_nfr:
            names.append(f"{prefix}-nfr")
        for name in names:
            skill_dir = self.project_root / ".claude" / "skills" / name
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
            (skill_dir / "workflow.md").write_text(f"# {name}\n", encoding="utf-8")


class patch_env:
    def __init__(self, project_root: Path, extra: dict[str, str] | None = None) -> None:
        self.project_root = str(project_root)
        self.extra = extra or {}
        self.previous: dict[str, str | None] = {}

    def __enter__(self) -> None:
        import os

        self.previous["PROJECT_ROOT"] = os.environ.get("PROJECT_ROOT")
        os.environ["PROJECT_ROOT"] = self.project_root
        for key, value in self.extra.items():
            self.previous[key] = os.environ.get(key)
            os.environ[key] = value

    def __exit__(self, exc_type, exc, tb) -> None:
        import os

        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _write_tea_assets(project_root: Path, *, root: Path | None = None) -> None:
    base = root or (project_root / "_bmad" / "tea" / "story-automator")
    prompts = base / "prompts"
    parse = base / "parse"
    prompts.mkdir(parents=True, exist_ok=True)
    parse.mkdir(parents=True, exist_ok=True)
    (prompts / "atdd.md").write_text("ATDD {{story_id}}\n", encoding="utf-8")
    (prompts / "test_automate.md").write_text("TEST AUTOMATE {{story_id}}\n", encoding="utf-8")
    (prompts / "test_review.md").write_text("TEST REVIEW {{story_id}}\n", encoding="utf-8")
    (prompts / "nfr.md").write_text("NFR {{story_id}}\n", encoding="utf-8")
    (prompts / "trace.md").write_text("TRACE {{story_id}}\n", encoding="utf-8")
    (parse / "atdd.json").write_text(json.dumps({"requiredKeys": ["status", "failing_tests_created", "summary", "next_action"], "schema": {"status": "SUCCESS|FAILURE|AMBIGUOUS", "failing_tests_created": "true|false", "summary": "brief description", "next_action": "proceed|retry|escalate"}}), encoding="utf-8")
    (parse / "test_automate.json").write_text(json.dumps({"requiredKeys": ["status", "tests_added", "summary", "next_action"], "schema": {"status": "SUCCESS|FAILURE|AMBIGUOUS", "tests_added": "integer", "summary": "brief description", "next_action": "proceed|retry|escalate"}}), encoding="utf-8")
    (parse / "test_review.json").write_text(json.dumps({"requiredKeys": ["status", "issues_found", "summary", "next_action"], "schema": {"status": "SUCCESS|FAILURE|AMBIGUOUS", "issues_found": "integer", "summary": "brief description", "next_action": "proceed|retry|escalate"}}), encoding="utf-8")
    (parse / "nfr.json").write_text(json.dumps({"requiredKeys": ["status", "nfr_report_created", "summary", "next_action"], "schema": {"status": "SUCCESS|FAILURE|AMBIGUOUS", "nfr_report_created": "true|false", "summary": "brief description", "next_action": "proceed|retry|escalate"}}), encoding="utf-8")
    (parse / "trace.json").write_text(json.dumps({"requiredKeys": ["status", "trace_updated", "summary", "next_action"], "schema": {"status": "SUCCESS|FAILURE|AMBIGUOUS", "trace_updated": "true|false", "summary": "brief description", "next_action": "proceed|retry|escalate"}}), encoding="utf-8")


def _tea_steps_override(
    project_root: Path,
    *,
    include_nfr: bool = False,
    canonical: bool = False,
    assets_root: str = "_bmad/tea/story-automator",
) -> dict[str, object]:
    prefix = "bmad-testarch" if canonical else "bmad-tea-testarch"
    steps: dict[str, object] = {
        "atdd": {
            "label": "atdd",
            "assets": {
                "skillName": f"{prefix}-atdd",
                "workflowCandidates": ["workflow.md", "workflow.yaml"],
                "instructionsCandidates": [],
                "checklistCandidates": ["checklist.md"],
                "templateCandidates": [],
                "required": ["skill"],
            },
            "prompt": {"templateFile": f"{assets_root}/prompts/atdd.md", "interactionMode": "autonomous"},
            "parse": {"schemaFile": f"{assets_root}/parse/atdd.json"},
            "success": {"verifier": "session_exit"},
        },
        "test_automate": {
            "label": "test-automate",
            "assets": {
                "skillName": f"{prefix}-automate",
                "workflowCandidates": ["workflow.md", "workflow.yaml"],
                "instructionsCandidates": [],
                "checklistCandidates": ["checklist.md"],
                "templateCandidates": [],
                "required": ["skill"],
            },
            "prompt": {"templateFile": f"{assets_root}/prompts/test_automate.md", "interactionMode": "autonomous"},
            "parse": {"schemaFile": f"{assets_root}/parse/test_automate.json"},
            "success": {"verifier": "session_exit"},
        },
        "test_review": {
            "label": "test-review",
            "assets": {
                "skillName": f"{prefix}-test-review",
                "workflowCandidates": ["workflow.md", "workflow.yaml"],
                "instructionsCandidates": [],
                "checklistCandidates": ["checklist.md"],
                "templateCandidates": [],
                "required": ["skill"],
            },
            "prompt": {"templateFile": f"{assets_root}/prompts/test_review.md", "interactionMode": "autonomous"},
            "parse": {"schemaFile": f"{assets_root}/parse/test_review.json"},
            "success": {"verifier": "session_exit"},
        },
        "trace": {
            "label": "trace",
            "assets": {
                "skillName": f"{prefix}-trace",
                "workflowCandidates": ["workflow.md", "workflow.yaml"],
                "instructionsCandidates": [],
                "checklistCandidates": ["checklist.md"],
                "templateCandidates": [],
                "required": ["skill"],
            },
            "prompt": {"templateFile": f"{assets_root}/prompts/trace.md", "interactionMode": "autonomous"},
            "parse": {"schemaFile": f"{assets_root}/parse/trace.json"},
            "success": {"verifier": "session_exit"},
        },
    }
    if include_nfr:
        steps["nfr"] = {
            "label": "nfr",
            "assets": {
                "skillName": f"{prefix}-nfr",
                "workflowCandidates": ["workflow.md", "workflow.yaml"],
                "instructionsCandidates": [],
                "checklistCandidates": ["checklist.md"],
                "templateCandidates": [],
                "required": ["skill"],
            },
            "prompt": {"templateFile": f"{assets_root}/prompts/nfr.md", "interactionMode": "autonomous"},
            "parse": {"schemaFile": f"{assets_root}/parse/nfr.json"},
            "success": {"verifier": "session_exit"},
        }
    return steps


if __name__ == "__main__":
    unittest.main()
