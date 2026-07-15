from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from story_automator.commands.orchestrator_parse import parse_output_action
from story_automator.commands.state import cmd_build_run_policy, cmd_build_state_doc, cmd_detect_workflow_track
from story_automator.commands.tmux import _build_cmd
from story_automator.core.runtime_policy import load_policy_for_state
from story_automator.core.utils import CommandResult
from tests.tea_test_support import install_bundle, install_required_skills, install_tea_skills, patch_env


class TeaPolicyFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)
        self.output_dir = self.project_root / "_bmad-output" / "story-automator"
        install_bundle(self.project_root)
        install_required_skills(self.project_root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_build_run_policy_rejects_tea_track_when_core_skills_are_missing(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_build_run_policy(["--config-json", json.dumps({"workflowTrack": "tea"})])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["error"], "policy_invalid")
        self.assertIn("bmad-testarch-atdd", payload["reason"])

    def test_build_run_policy_rejects_unknown_workflow_track(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_build_run_policy(["--config-json", json.dumps({"workflowTrack": "teaa"})])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["error"], "policy_invalid")
        self.assertIn("unknown workflowTrack: teaa", payload["reason"])

    def test_generated_policy_override_remains_portable_after_validation(self) -> None:
        install_tea_skills(self.project_root, canonical=True, write_assets=False)
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_build_run_policy(["--config-json", json.dumps({"workflowTrack": "tea"})])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        atdd = payload["policyOverride"]["steps"]["atdd"]
        self.assertNotIn("templatePath", atdd["prompt"])
        self.assertNotIn("schemaPath", atdd["parse"])
        self.assertNotIn("templateHash", atdd["prompt"])
        self.assertNotIn("schemaHash", atdd["parse"])

    def test_detect_workflow_track_keeps_standard_override_out_of_tea_detection(self) -> None:
        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "story-automator.policy.json").write_text(
            json.dumps({"workflow": {"sequence": ["create", "dev", "review"]}}),
            encoding="utf-8",
        )
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_detect_workflow_track([])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["teaDetected"])
        self.assertEqual(payload["recommendedTrack"], "standard")

    def test_build_state_doc_preserves_explicit_standard_override_without_run_selection(self) -> None:
        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "story-automator.policy.json").write_text(
            json.dumps({"workflow": {"sequence": ["create", "dev", "review"]}}),
            encoding="utf-8",
        )
        state_file = self._build_state()
        policy = load_policy_for_state(state_file, project_root=str(self.project_root))
        self.assertEqual(policy["workflow"]["sequence"], ["create", "dev", "review"])

    def test_build_state_doc_preserves_explicit_standard_override_with_standard_track_selection(self) -> None:
        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "story-automator.policy.json").write_text(
            json.dumps({"workflow": {"sequence": ["create", "dev", "review"]}}),
            encoding="utf-8",
        )
        state_file = self._build_state({"workflowTrack": "standard", "selectedOptionalSteps": []})
        policy = load_policy_for_state(state_file, project_root=str(self.project_root))
        self.assertEqual(policy["workflow"]["sequence"], ["create", "dev", "review"])

    def test_build_state_doc_preserves_explicit_project_tea_policy(self) -> None:
        install_tea_skills(self.project_root, canonical=True, write_assets=False)
        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        override = {
            "workflow": {"sequence": ["create", "atdd", "dev", "trace", "review"]},
            "steps": {
                "atdd": {
                    "label": "acceptance-tests",
                    "assets": {
                        "skillName": "bmad-testarch-atdd",
                        "workflowCandidates": ["workflow.md", "workflow.yaml"],
                        "instructionsCandidates": [],
                        "checklistCandidates": ["checklist.md"],
                        "templateCandidates": [],
                        "required": ["skill"],
                    },
                    "prompt": {"templateFile": "data/tea-story-automator/prompts/tea_step.md", "interactionMode": "autonomous"},
                    "parse": {"schemaFile": "data/tea-story-automator/parse/tea_step.json"},
                    "success": {"verifier": "session_exit"},
                },
                "trace": {
                    "label": "trace",
                    "assets": {
                        "skillName": "bmad-testarch-trace",
                        "workflowCandidates": ["workflow.md", "workflow.yaml"],
                        "instructionsCandidates": [],
                        "checklistCandidates": ["checklist.md"],
                        "templateCandidates": [],
                        "required": ["skill"],
                    },
                    "prompt": {"templateFile": "data/tea-story-automator/prompts/tea_step.md", "interactionMode": "autonomous"},
                    "parse": {"schemaFile": "data/tea-story-automator/parse/tea_step.json"},
                    "success": {"verifier": "session_exit"},
                },
            },
        }
        (override_dir / "story-automator.policy.json").write_text(json.dumps(override), encoding="utf-8")

        state_file = self._build_state({"workflowTrack": "tea"})
        policy = load_policy_for_state(state_file, project_root=str(self.project_root))
        self.assertEqual(policy["workflow"]["sequence"], ["create", "atdd", "dev", "trace", "review"])
        self.assertEqual(policy["steps"]["atdd"]["label"], "acceptance-tests")

    def test_build_state_doc_preserves_explicit_project_tea_policy_without_track_selection(self) -> None:
        install_tea_skills(self.project_root, canonical=True, write_assets=False)
        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        override = {
            "workflow": {"sequence": ["create", "atdd", "dev", "trace", "review"]},
            "steps": {
                "atdd": {
                    "label": "acceptance-tests",
                    "assets": {
                        "skillName": "bmad-testarch-atdd",
                        "workflowCandidates": ["workflow.md", "workflow.yaml"],
                        "instructionsCandidates": [],
                        "checklistCandidates": ["checklist.md"],
                        "templateCandidates": [],
                        "required": ["skill"],
                    },
                    "prompt": {"templateFile": "data/tea-story-automator/prompts/tea_step.md", "interactionMode": "autonomous"},
                    "parse": {"schemaFile": "data/tea-story-automator/parse/tea_step.json"},
                    "success": {"verifier": "session_exit"},
                },
                "trace": {
                    "label": "trace",
                    "assets": {
                        "skillName": "bmad-testarch-trace",
                        "workflowCandidates": ["workflow.md", "workflow.yaml"],
                        "instructionsCandidates": [],
                        "checklistCandidates": ["checklist.md"],
                        "templateCandidates": [],
                        "required": ["skill"],
                    },
                    "prompt": {"templateFile": "data/tea-story-automator/prompts/tea_step.md", "interactionMode": "autonomous"},
                    "parse": {"schemaFile": "data/tea-story-automator/parse/tea_step.json"},
                    "success": {"verifier": "session_exit"},
                },
            },
        }
        (override_dir / "story-automator.policy.json").write_text(json.dumps(override), encoding="utf-8")

        state_file = self._build_state()
        policy = load_policy_for_state(state_file, project_root=str(self.project_root))
        self.assertEqual(policy["workflow"]["sequence"], ["create", "atdd", "dev", "trace", "review"])

    def test_build_state_doc_renders_tea_summary_from_pinned_sequence(self) -> None:
        install_tea_skills(self.project_root, canonical=True, write_assets=False)
        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        override = {
            "workflow": {"sequence": ["create", "atdd", "dev", "trace", "review"]},
            "steps": {
                "atdd": {
                    "label": "acceptance-tests",
                    "assets": {
                        "skillName": "bmad-testarch-atdd",
                        "workflowCandidates": ["workflow.md", "workflow.yaml"],
                        "instructionsCandidates": [],
                        "checklistCandidates": ["checklist.md"],
                        "templateCandidates": [],
                        "required": ["skill"],
                    },
                    "prompt": {"templateFile": "data/tea-story-automator/prompts/tea_step.md", "interactionMode": "autonomous"},
                    "parse": {"schemaFile": "data/tea-story-automator/parse/tea_step.json"},
                    "success": {"verifier": "session_exit"},
                },
                "trace": {
                    "label": "trace",
                    "assets": {
                        "skillName": "bmad-testarch-trace",
                        "workflowCandidates": ["workflow.md", "workflow.yaml"],
                        "instructionsCandidates": [],
                        "checklistCandidates": ["checklist.md"],
                        "templateCandidates": [],
                        "required": ["skill"],
                    },
                    "prompt": {"templateFile": "data/tea-story-automator/prompts/tea_step.md", "interactionMode": "autonomous"},
                    "parse": {"schemaFile": "data/tea-story-automator/parse/tea_step.json"},
                    "success": {"verifier": "session_exit"},
                },
            },
        }
        (override_dir / "story-automator.policy.json").write_text(json.dumps(override), encoding="utf-8")

        state_file = self._build_state()
        text = state_file.read_text(encoding="utf-8")
        self.assertIn("- Pinned TEA Steps: atdd, trace", text)
        self.assertNotIn("- Mandatory TEA Core: atdd, test_automate, test_review, trace", text)

    def test_build_state_doc_rejects_duplicate_story_ids(self) -> None:
        stdout = io.StringIO()
        template = self.project_root / ".claude" / "skills" / "bmad-story-automator" / "templates" / "state-document.md"
        config = {
            "epic": "1",
            "epicName": "Epic 1",
            "storyRange": ["1.1", "1.1"],
            "status": "READY",
            "aiCommand": "claude --dangerously-skip-permissions",
        }
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
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["error"], "storyRange_contains_duplicates")
        self.assertEqual(payload["duplicates"], ["1.1"])

    def test_bundled_tea_adapter_contract_supports_build_and_parse_for_all_steps(self) -> None:
        install_tea_skills(self.project_root, canonical=True, include_nfr=True, write_assets=False)
        stdout = io.StringIO()
        config = {"workflowTrack": "tea", "selectedOptionalSteps": ["nfr"]}
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_build_run_policy(["--config-json", json.dumps(config)])
        self.assertEqual(code, 0)
        build_payload = json.loads(stdout.getvalue())
        self.assertTrue(build_payload["ok"])
        self.assertEqual(
            build_payload["policyOverride"]["workflow"]["sequence"],
            ["create", "atdd", "dev", "test_automate", "test_review", "nfr", "trace", "review"],
        )

        state_file = self._build_state(config)
        policy = load_policy_for_state(state_file, project_root=str(self.project_root))
        output_file = self.project_root / "session.txt"
        output_file.write_text("session output\n", encoding="utf-8")

        for step in ("atdd", "test_automate", "test_review", "nfr", "trace"):
            contract = policy["steps"][step]
            self.assertEqual(Path(contract["prompt"]["templatePath"]).name, "tea_step.md")
            self.assertEqual(Path(contract["parse"]["schemaPath"]).name, "tea_step.json")

            build_stdout = io.StringIO()
            with patch_env(self.project_root), redirect_stdout(build_stdout):
                code = _build_cmd([step, "1.1", "--state-file", str(state_file)])
            self.assertEqual(code, 0)
            rendered = build_stdout.getvalue()
            self.assertIn("Run the", rendered)
            self.assertIn("story `1.1`", rendered)

            parse_stdout = io.StringIO()
            with patch_env(self.project_root), patch(
                "story_automator.commands.orchestrator_parse.run_cmd",
                return_value=CommandResult('{"status":"SUCCESS","summary":"ok","next_action":"proceed"}', 0),
            ), redirect_stdout(parse_stdout):
                code = parse_output_action([str(output_file), step, "--state-file", str(state_file)])
            self.assertEqual(code, 0)
            payload = json.loads(parse_stdout.getvalue())
            self.assertEqual(payload["next_action"], "proceed")

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
