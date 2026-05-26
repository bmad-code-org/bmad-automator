from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from story_automator.core.runtime_policy import (
    PolicyError,
    load_effective_policy,
    load_policy_shape_for_state,
    load_policy_snapshot,
    load_runtime_policy,
    snapshot_effective_policy,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


class RuntimePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)
        self._install_bundle()
        self._install_required_skills()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_bundled_default_loads(self) -> None:
        policy = load_effective_policy(str(self.project_root))
        self.assertEqual(policy["version"], 1)
        self.assertEqual(policy["steps"]["review"]["success"]["verifier"], "review_completion")

    def test_project_override_deep_merges_and_arrays_replace(self) -> None:
        self._write_override(
            {
                "workflow": {"sequence": ["create", "review"]},
                "steps": {"review": {"prompt": {"defaultExtraInstruction": "fix critical issues only"}}},
            }
        )
        policy = load_effective_policy(str(self.project_root))
        self.assertEqual(policy["workflow"]["sequence"], ["create", "review"])
        self.assertEqual(policy["steps"]["review"]["prompt"]["defaultExtraInstruction"], "fix critical issues only")

    def test_inline_override_deep_merges_after_project_override(self) -> None:
        self._write_override({"workflow": {"sequence": ["create", "dev", "review"]}})
        policy = load_effective_policy(
            str(self.project_root),
            inline_override={"workflow": {"repeat": {"review": {"maxCycles": 3}}}},
        )
        self.assertEqual(policy["workflow"]["sequence"], ["create", "dev", "review"])
        self.assertEqual(policy["workflow"]["repeat"]["review"]["maxCycles"], 3)

    def test_invalid_step_name_rejected(self) -> None:
        self._write_override({"steps": {"ship": {"success": {"verifier": "session_exit"}}}})
        with self.assertRaises(PolicyError):
            load_effective_policy(str(self.project_root))

    def test_tea_steps_allowed_when_explicitly_configured_and_installed(self) -> None:
        self._install_tea_skills()
        steps = _tea_steps_override(self.project_root)
        self._write_override(
            {
                "workflow": {"sequence": ["create", "atdd", "dev", "test_automate", "test_review", "trace", "review"]},
                "steps": steps,
            }
        )
        policy = load_effective_policy(str(self.project_root))
        self.assertEqual(
            policy["workflow"]["sequence"],
            ["create", "atdd", "dev", "test_automate", "test_review", "trace", "review"],
        )
        self.assertEqual(policy["steps"]["trace"]["assets"]["skillName"], "bmad-tea-testarch-trace")

    def test_invalid_verifier_name_rejected(self) -> None:
        self._write_override({"steps": {"review": {"success": {"verifier": "nope"}}}})
        with self.assertRaises(PolicyError):
            load_effective_policy(str(self.project_root))

    def test_required_asset_missing_fails(self) -> None:
        shutil.rmtree(self.project_root / ".claude" / "skills" / "bmad-create-story")
        with self.assertRaises(PolicyError):
            load_effective_policy(str(self.project_root))

    def test_tea_policy_fails_when_required_tea_skill_missing(self) -> None:
        steps = _tea_steps_override(self.project_root)
        self._write_override(
            {
                "workflow": {"sequence": ["create", "atdd", "dev", "review"]},
                "steps": {
                    "atdd": steps["atdd"],
                },
            }
        )
        with self.assertRaises(PolicyError):
            load_effective_policy(str(self.project_root))

    def test_dependency_workflow_file_optional(self) -> None:
        (self.project_root / ".claude" / "skills" / "bmad-create-story" / "workflow.md").unlink()
        policy = load_effective_policy(str(self.project_root))
        files = policy["steps"]["create"]["assets"]["files"]
        self.assertEqual(files["skill"], ".claude/skills/bmad-create-story/SKILL.md")
        self.assertEqual(files["workflow"], "")

    def test_optional_workflow_without_skill_ignored(self) -> None:
        (self.project_root / ".claude" / "skills" / "bmad-qa-generate-e2e-tests" / "SKILL.md").unlink()
        policy = load_effective_policy(str(self.project_root))
        files = policy["steps"]["auto"]["assets"]["files"]
        self.assertEqual(files["skill"], "")
        self.assertEqual(files["workflow"], "")

    def test_snapshot_hash_stable(self) -> None:
        first = snapshot_effective_policy(str(self.project_root))
        second = snapshot_effective_policy(str(self.project_root))
        self.assertEqual(first["policySnapshotHash"], second["policySnapshotHash"])

    def test_snapshot_bakes_legacy_env_values_for_resume(self) -> None:
        with patch.dict("os.environ", {"MAX_REVIEW_CYCLES": "2", "MAX_CRASH_RETRIES": "4"}, clear=False):
            snapshot = snapshot_effective_policy(str(self.project_root))
        with patch.dict("os.environ", {"MAX_REVIEW_CYCLES": "9", "MAX_CRASH_RETRIES": "9"}, clear=False):
            policy = load_policy_snapshot(
                snapshot["policySnapshotFile"],
                project_root=str(self.project_root),
                expected_hash=snapshot["policySnapshotHash"],
            )
        self.assertEqual(policy["workflow"]["repeat"]["review"]["maxCycles"], 2)
        self.assertEqual(policy["workflow"]["crash"]["maxRetries"], 4)

    def test_invalid_legacy_env_value_raises_policy_error(self) -> None:
        with patch.dict("os.environ", {"MAX_REVIEW_CYCLES": "nope"}, clear=False):
            with self.assertRaisesRegex(PolicyError, "MAX_REVIEW_CYCLES must be an integer"):
                load_effective_policy(str(self.project_root))

    def test_malformed_override_json_raises_policy_error(self) -> None:
        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "story-automator.policy.json").write_text("{bad json", encoding="utf-8")
        with self.assertRaises(PolicyError):
            load_effective_policy(str(self.project_root))

    def test_unreadable_override_file_is_wrapped_as_policy_error(self) -> None:
        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        override_path = (override_dir / "story-automator.policy.json").resolve()
        override_path.write_text("{}", encoding="utf-8")

        original_read_json = __import__("story_automator.core.runtime_policy", fromlist=["_read_json"])._read_json

        def raising_read_json(path):
            if Path(path).resolve() == override_path:
                raise OSError("permission denied")
            return original_read_json(path)

        with patch("story_automator.core.runtime_policy._read_json", side_effect=raising_read_json):
            with self.assertRaisesRegex(PolicyError, r"project override unreadable: .*story-automator\.policy\.json"):
                load_effective_policy(str(self.project_root))

    def test_bundled_policy_read_failure_is_wrapped_as_policy_error(self) -> None:
        policy_path = self.project_root / ".claude" / "skills" / "bmad-story-automator" / "data" / "orchestration-policy.json"
        policy_path.unlink()
        policy_path.mkdir()
        with patch(
            "story_automator.core.runtime_policy.bundled_skill_root",
            return_value=self.project_root / ".claude" / "skills" / "bmad-story-automator",
        ):
            with self.assertRaisesRegex(PolicyError, r"policy unreadable: .*orchestration-policy\.json"):
                load_effective_policy(str(self.project_root))

    def test_invalid_assets_type_rejected(self) -> None:
        self._write_override({"steps": {"review": {"assets": []}}})
        with self.assertRaises(PolicyError):
            load_effective_policy(str(self.project_root))

    def test_invalid_workflow_and_snapshot_types_rejected(self) -> None:
        self._write_override({"workflow": [], "snapshot": []})
        with self.assertRaises(PolicyError):
            load_effective_policy(str(self.project_root))

    def test_invalid_nested_workflow_types_rejected(self) -> None:
        self._write_override({"workflow": {"repeat": [1], "crash": [2]}})
        with self.assertRaises(PolicyError):
            load_effective_policy(str(self.project_root))

    def test_invalid_parser_runtime_rejected(self) -> None:
        self._write_override({"runtime": {"parser": {"provider": "bad", "model": "haiku", "timeoutSeconds": 120}}})
        with self.assertRaisesRegex(PolicyError, "runtime.parser.provider"):
            load_effective_policy(str(self.project_root))

    def test_snapshot_reload_re_resolves_paths_for_new_root(self) -> None:
        snapshot = snapshot_effective_policy(str(self.project_root))
        copied_root = Path(self.tmp.name) / "copied"
        shutil.copytree(self.project_root, copied_root)
        policy = load_runtime_policy(str(copied_root), state_file=str(copied_root / snapshot["policySnapshotFile"]))
        template_path = policy["steps"]["create"]["prompt"]["templatePath"]
        self.assertTrue(str(copied_root) in template_path)

    def test_snapshot_relative_dir_cannot_escape_project_root(self) -> None:
        self._write_override({"snapshot": {"relativeDir": "../outside"}})
        with self.assertRaisesRegex(PolicyError, "snapshot.relativeDir escapes allowed root"):
            snapshot_effective_policy(str(self.project_root))

    def test_data_path_cannot_escape_allowed_roots(self) -> None:
        self._write_override({"steps": {"create": {"prompt": {"templateFile": "../outside.md"}}}})
        with self.assertRaisesRegex(PolicyError, "policy data path escapes allowed roots"):
            load_effective_policy(str(self.project_root))

    def test_snapshot_file_cannot_escape_project_root(self) -> None:
        snapshot = snapshot_effective_policy(str(self.project_root))
        source_path = self.project_root / snapshot["policySnapshotFile"]
        external = self.project_root.parent / "external-snapshot.json"
        external.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
        with self.assertRaisesRegex(PolicyError, "policy snapshot escapes allowed root"):
            load_policy_snapshot(str(external), project_root=str(self.project_root), expected_hash=snapshot["policySnapshotHash"])

    def test_snapshot_detects_prompt_template_drift(self) -> None:
        snapshot = snapshot_effective_policy(str(self.project_root))
        prompt = self.project_root / ".claude" / "skills" / "bmad-story-automator" / "data" / "prompts" / "create.md"
        prompt.write_text("# changed\n", encoding="utf-8")
        with self.assertRaisesRegex(PolicyError, "policy template hash mismatch"):
            load_policy_snapshot(
                snapshot["policySnapshotFile"],
                project_root=str(self.project_root),
                expected_hash=snapshot["policySnapshotHash"],
            )

    def test_snapshot_detects_parse_schema_drift(self) -> None:
        snapshot = snapshot_effective_policy(str(self.project_root))
        schema = self.project_root / ".claude" / "skills" / "bmad-story-automator" / "data" / "parse" / "create.json"
        schema.write_text('{"requiredKeys":["status"],"schema":{"status":"SUCCESS|FAILURE|AMBIGUOUS"}}\n', encoding="utf-8")
        with self.assertRaisesRegex(PolicyError, "policy parse schema hash mismatch"):
            load_policy_snapshot(
                snapshot["policySnapshotFile"],
                project_root=str(self.project_root),
                expected_hash=snapshot["policySnapshotHash"],
            )

    def test_snapshot_detects_success_contract_drift(self) -> None:
        snapshot = snapshot_effective_policy(str(self.project_root))
        contract = self.project_root / ".claude" / "skills" / "bmad-story-automator-review" / "contract.json"
        contract.write_text('{"doneValues":["approved"],"sourceOrder":["story-file"],"syncSprintStatus":false}\n', encoding="utf-8")
        with self.assertRaisesRegex(PolicyError, "policy success contract hash mismatch"):
            load_policy_snapshot(
                snapshot["policySnapshotFile"],
                project_root=str(self.project_root),
                expected_hash=snapshot["policySnapshotHash"],
            )

    def test_missing_marker_state_raises_policy_error(self) -> None:
        marker = self.project_root / ".claude" / ".story-automator-active"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"stateFile": "missing.md"}), encoding="utf-8")
        with self.assertRaisesRegex(PolicyError, "marker state file missing"):
            load_runtime_policy(str(self.project_root))

    def test_marker_state_cannot_escape_project_root(self) -> None:
        marker = self.project_root / ".claude" / ".story-automator-active"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"stateFile": "../outside.md"}), encoding="utf-8")
        with self.assertRaisesRegex(PolicyError, "marker state file escapes allowed root"):
            load_runtime_policy(str(self.project_root))

    def test_malformed_marker_raises_policy_error(self) -> None:
        marker = self.project_root / ".claude" / ".story-automator-active"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("{bad json", encoding="utf-8")
        with self.assertRaisesRegex(PolicyError, "active-run marker invalid"):
            load_runtime_policy(str(self.project_root))

    def test_env_state_cannot_escape_project_root(self) -> None:
        with patch.dict("os.environ", {"STORY_AUTOMATOR_STATE_FILE": "../outside.md"}, clear=False):
            with self.assertRaisesRegex(PolicyError, "env state file escapes allowed root"):
                load_runtime_policy(str(self.project_root))

    def test_legacy_state_uses_bundled_defaults_without_override_or_env(self) -> None:
        self._write_override({"workflow": {"repeat": {"review": {"maxCycles": 1}}}})
        legacy_state = self.project_root / "legacy.md"
        legacy_state.write_text(
            "---\nepic: \"1\"\nepicName: \"Epic 1\"\nstoryRange: [\"1.1\"]\nstatus: \"READY\"\nlastUpdated: \"2026-04-13T00:00:00Z\"\naiCommand: \"claude\"\n---\n",
            encoding="utf-8",
        )
        with patch.dict("os.environ", {"MAX_REVIEW_CYCLES": "2"}, clear=False):
            policy = load_runtime_policy(str(self.project_root), state_file=str(legacy_state))
        self.assertEqual(policy["workflow"]["repeat"]["review"]["maxCycles"], 5)

    def test_marker_resume_with_missing_snapshot_raises_policy_error(self) -> None:
        state_file = self.project_root / "orchestration.md"
        state_file.write_text(
            "---\npolicySnapshotFile: \"_bmad-output/story-automator/snapshots/missing.json\"\npolicySnapshotHash: \"deadbeef\"\n---\n",
            encoding="utf-8",
        )
        marker = self.project_root / ".claude" / ".story-automator-active"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"stateFile": str(state_file.relative_to(self.project_root))}), encoding="utf-8")
        with self.assertRaises(PolicyError):
            load_runtime_policy(str(self.project_root))

    def test_new_state_without_snapshot_metadata_is_rejected(self) -> None:
        state_file = self.project_root / "orchestration.md"
        state_file.write_text(
            "---\nepic: \"1\"\nepicName: \"Epic 1\"\nstoryRange: [\"1.1\"]\nstatus: \"READY\"\nlastUpdated: \"2026-04-13T00:00:00Z\"\naiCommand: \"claude\"\npolicyVersion: 1\nlegacyPolicy: false\n---\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(PolicyError, "state policy snapshot missing"):
            load_runtime_policy(str(self.project_root), state_file=str(state_file))

    def test_contradictory_legacy_flag_with_policy_version_is_rejected(self) -> None:
        state_file = self.project_root / "orchestration.md"
        state_file.write_text(
            "---\nepic: \"1\"\nepicName: \"Epic 1\"\nstoryRange: [\"1.1\"]\nstatus: \"READY\"\nlastUpdated: \"2026-04-13T00:00:00Z\"\naiCommand: \"claude\"\npolicyVersion: 1\nlegacyPolicy: true\n---\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(PolicyError, "state policy snapshot missing"):
            load_runtime_policy(str(self.project_root), state_file=str(state_file))

    def test_snapshot_metadata_with_legacy_flag_is_rejected(self) -> None:
        snapshot = snapshot_effective_policy(str(self.project_root))
        state_file = self.project_root / "orchestration.md"
        state_file.write_text(
            f"---\npolicySnapshotFile: \"{snapshot['policySnapshotFile']}\"\npolicySnapshotHash: \"{snapshot['policySnapshotHash']}\"\nlegacyPolicy: true\n---\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(PolicyError, "state policy metadata contradictory"):
            load_runtime_policy(str(self.project_root), state_file=str(state_file))

    def test_explicit_directory_state_file_raises_policy_error(self) -> None:
        with self.assertRaisesRegex(PolicyError, "state file unreadable"):
            load_runtime_policy(str(self.project_root), state_file=str(self.project_root))

    def test_load_policy_shape_for_state_reports_missing_snapshot_precisely(self) -> None:
        state_file = self.project_root / "orchestration-missing-snapshot.md"
        state_file.write_text(
            "---\npolicySnapshotFile: \"missing.json\"\npolicySnapshotHash: \"deadbeef\"\n---\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(PolicyError, r"policy snapshot missing: .*missing\.json"):
            load_policy_shape_for_state(str(state_file), project_root=str(self.project_root))

    def test_load_policy_shape_for_state_wraps_snapshot_stat_errors(self) -> None:
        state_file = self.project_root / "orchestration-unreadable-snapshot.md"
        state_file.write_text(
            "---\npolicySnapshotFile: \"blocked.json\"\npolicySnapshotHash: \"deadbeef\"\n---\n",
            encoding="utf-8",
        )
        blocked_path = (self.project_root / "blocked.json").resolve()
        original_is_file = Path.is_file

        def raising_is_file(path: Path) -> bool:
            if path.resolve() == blocked_path:
                raise PermissionError("permission denied")
            return original_is_file(path)

        with patch("pathlib.Path.is_file", autospec=True, side_effect=raising_is_file):
            with self.assertRaisesRegex(PolicyError, r"policy snapshot unreadable: .*blocked\.json"):
                load_policy_shape_for_state(str(state_file), project_root=str(self.project_root))

    def test_load_policy_snapshot_wraps_snapshot_stat_errors(self) -> None:
        blocked_path = (self.project_root / "blocked.json").resolve()
        original_is_file = Path.is_file

        def raising_is_file(path: Path) -> bool:
            if path.resolve() == blocked_path:
                raise PermissionError("permission denied")
            return original_is_file(path)

        with patch("pathlib.Path.is_file", autospec=True, side_effect=raising_is_file):
            with self.assertRaisesRegex(PolicyError, r"policy snapshot unreadable: .*blocked\.json"):
                load_policy_snapshot("blocked.json", project_root=str(self.project_root), expected_hash="deadbeef")

    def _install_bundle(self) -> None:
        source_skill = REPO_ROOT / "skills" / "bmad-story-automator"
        source_review = REPO_ROOT / "skills" / "bmad-story-automator-review"
        target_root = self.project_root / ".claude" / "skills"
        target_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_skill, target_root / "bmad-story-automator")
        shutil.copytree(source_review, target_root / "bmad-story-automator-review")

    def _install_required_skills(self) -> None:
        self._make_skill(
            "bmad-create-story",
            extras={"discover-inputs.md": "# discover\n", "checklist.md": "# checklist\n", "template.md": "# template\n"},
        )
        self._make_skill("bmad-dev-story", extras={"checklist.md": "# checklist\n"})
        self._make_skill("bmad-retrospective")
        self._make_skill("bmad-qa-generate-e2e-tests", extras={"checklist.md": "# checklist\n"})

    def _make_skill(self, name: str, *, extras: dict[str, str] | None = None) -> None:
        skill_dir = self.project_root / ".claude" / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
        (skill_dir / "workflow.md").write_text(f"# {name}\n", encoding="utf-8")
        for rel, content in (extras or {}).items():
            (skill_dir / rel).write_text(content, encoding="utf-8")

    def _write_override(self, payload: dict[str, object]) -> None:
        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "story-automator.policy.json").write_text(json.dumps(payload), encoding="utf-8")

    def _install_tea_skills(self) -> None:
        _write_tea_assets(self.project_root)
        for name in (
            "bmad-tea-testarch-atdd",
            "bmad-tea-testarch-automate",
            "bmad-tea-testarch-test-review",
            "bmad-tea-testarch-trace",
        ):
            skill_dir = self.project_root / ".claude" / "skills" / name
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
            (skill_dir / "workflow.md").write_text(f"# {name}\n", encoding="utf-8")


def _write_tea_assets(project_root: Path) -> None:
    prompts = project_root / "_bmad" / "tea" / "story-automator" / "prompts"
    parse = project_root / "_bmad" / "tea" / "story-automator" / "parse"
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


def _tea_steps_override(project_root: Path, *, include_nfr: bool = False) -> dict[str, object]:
    steps: dict[str, object] = {
        "atdd": {
            "label": "atdd",
            "assets": {
                "skillName": "bmad-tea-testarch-atdd",
                "workflowCandidates": ["workflow.md", "workflow.yaml"],
                "instructionsCandidates": [],
                "checklistCandidates": ["checklist.md"],
                "templateCandidates": [],
                "required": ["skill"],
            },
            "prompt": {"templateFile": "_bmad/tea/story-automator/prompts/atdd.md", "interactionMode": "autonomous"},
            "parse": {"schemaFile": "_bmad/tea/story-automator/parse/atdd.json"},
            "success": {"verifier": "session_exit"},
        },
        "test_automate": {
            "label": "test-automate",
            "assets": {
                "skillName": "bmad-tea-testarch-automate",
                "workflowCandidates": ["workflow.md", "workflow.yaml"],
                "instructionsCandidates": [],
                "checklistCandidates": ["checklist.md"],
                "templateCandidates": [],
                "required": ["skill"],
            },
            "prompt": {"templateFile": "_bmad/tea/story-automator/prompts/test_automate.md", "interactionMode": "autonomous"},
            "parse": {"schemaFile": "_bmad/tea/story-automator/parse/test_automate.json"},
            "success": {"verifier": "session_exit"},
        },
        "test_review": {
            "label": "test-review",
            "assets": {
                "skillName": "bmad-tea-testarch-test-review",
                "workflowCandidates": ["workflow.md", "workflow.yaml"],
                "instructionsCandidates": [],
                "checklistCandidates": ["checklist.md"],
                "templateCandidates": [],
                "required": ["skill"],
            },
            "prompt": {"templateFile": "_bmad/tea/story-automator/prompts/test_review.md", "interactionMode": "autonomous"},
            "parse": {"schemaFile": "_bmad/tea/story-automator/parse/test_review.json"},
            "success": {"verifier": "session_exit"},
        },
        "trace": {
            "label": "trace",
            "assets": {
                "skillName": "bmad-tea-testarch-trace",
                "workflowCandidates": ["workflow.md", "workflow.yaml"],
                "instructionsCandidates": [],
                "checklistCandidates": ["checklist.md"],
                "templateCandidates": [],
                "required": ["skill"],
            },
            "prompt": {"templateFile": "_bmad/tea/story-automator/prompts/trace.md", "interactionMode": "autonomous"},
            "parse": {"schemaFile": "_bmad/tea/story-automator/parse/trace.json"},
            "success": {"verifier": "session_exit"},
        },
    }
    if include_nfr:
        steps["nfr"] = {
            "label": "nfr",
            "assets": {
                "skillName": "bmad-tea-testarch-nfr",
                "workflowCandidates": ["workflow.md", "workflow.yaml"],
                "instructionsCandidates": [],
                "checklistCandidates": ["checklist.md"],
                "templateCandidates": [],
                "required": ["skill"],
            },
            "prompt": {"templateFile": "_bmad/tea/story-automator/prompts/nfr.md", "interactionMode": "autonomous"},
            "parse": {"schemaFile": "_bmad/tea/story-automator/parse/nfr.json"},
            "success": {"verifier": "session_exit"},
        }
    return steps


if __name__ == "__main__":
    unittest.main()
