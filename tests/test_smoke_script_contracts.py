from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"


def load_script_module(name: str, path: Path):
    with patch.object(sys, "path", [str(SCRIPTS), *sys.path]):
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load script module: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


def import_script_package(name: str):
    with patch.object(sys, "path", [str(SCRIPTS), *sys.path]):
        return __import__(name, fromlist=["*"])


class VersionAlignmentScriptTests(unittest.TestCase):
    def test_python_version_missing_raises_targeted_error(self) -> None:
        module = load_script_module("check_version_alignment", SCRIPTS / "check-version-alignment.py")

        with self.assertRaisesRegex(ValueError, "missing Python __version__ assignment"):
            module.python_version("# no version here\n", "pkg/__init__.py")

    def test_marketplace_plugin_version_uses_stable_plugin_name(self) -> None:
        module = load_script_module("check_version_alignment", SCRIPTS / "check-version-alignment.py")

        version = module.marketplace_plugin_version(
            {
                "plugins": [
                    {"name": "other-plugin", "version": "9.9.9"},
                    {"name": "bmad-automator", "version": "1.15.0"},
                ]
            },
            {"name": "bmad-automator"},
        )

        self.assertEqual(version, "1.15.0")

    def test_marketplace_plugin_version_requires_match(self) -> None:
        module = load_script_module("check_version_alignment", SCRIPTS / "check-version-alignment.py")

        with self.assertRaisesRegex(ValueError, "missing plugin: bmad-automator"):
            module.marketplace_plugin_version({"plugins": []}, {"name": "bmad-automator"})


class SmokeContractsScriptTests(unittest.TestCase):
    def test_allowed_environment_skips_do_not_fail_default_contract_gate(self) -> None:
        module = load_script_module("run_smoke_contracts", SCRIPTS / "run-smoke-contracts.py")
        stderr = io.StringIO()

        class Result:
            skipped = [("tmux test", "tmux not available")]

            def wasSuccessful(self) -> bool:
                return True

        class Runner:
            def __init__(self, *, verbosity: int) -> None:
                self.verbosity = verbosity

            def run(self, suite):
                return Result()

        with (
            patch.object(module.unittest.defaultTestLoader, "loadTestsFromNames", return_value=object()) as load_tests,
            patch.object(module.unittest, "TextTestRunner", Runner),
            redirect_stderr(stderr),
        ):
            code = module.main()

        self.assertEqual(code, 0)
        self.assertIn("smoke:contracts skipped 1 allowed environment-dependent tests", stderr.getvalue())
        load_tests.assert_called_once_with(module.TEST_MODULES)

    def test_unexpected_skips_fail_default_contract_gate(self) -> None:
        module = load_script_module("run_smoke_contracts", SCRIPTS / "run-smoke-contracts.py")
        stderr = io.StringIO()

        class Result:
            skipped = [("feature test", "temporarily disabled")]

            def wasSuccessful(self) -> bool:
                return True

        class Runner:
            def __init__(self, *, verbosity: int) -> None:
                self.verbosity = verbosity

            def run(self, suite):
                return Result()

        with (
            patch.object(module.unittest.defaultTestLoader, "loadTestsFromNames", return_value=object()),
            patch.object(module.unittest, "TextTestRunner", Runner),
            redirect_stderr(stderr),
        ):
            code = module.main()

        self.assertEqual(code, 1)
        self.assertIn("smoke:contracts got 1 unexpected skipped tests", stderr.getvalue())


class DeterministicSmokeEnvTests(unittest.TestCase):
    def test_subprocess_runners_clear_marker_override_env(self) -> None:
        automator = load_script_module("run_smoke_automator", SCRIPTS / "run-smoke-automator.py")
        dev_loop = load_script_module("run_smoke_dev_loop", SCRIPTS / "run-smoke-dev-loop.py")

        with patch.dict(
            os.environ,
            {
                "BMAD_STORY_AUTOMATOR_ACTIVE_MARKER": "/tmp/outside-a",
                "STORY_AUTOMATOR_ACTIVE_MARKER": "/tmp/outside-b",
                "BMAD_SKILLS_ROOT": "/tmp/outside-skills",
                "BMAD_RUNTIME_PROVIDER": "codex",
                "STORY_AUTOMATOR_RUNTIME_PROVIDER": "codex",
            },
            clear=False,
        ):
            runner = automator.SmokeRunner(
                root=REPO_ROOT,
                workspace=REPO_ROOT / ".smoke",
                project=REPO_ROOT / ".smoke" / "gunz",
                story_id="1.1",
            )
            dev = dev_loop.DevLoopSmokeRunner(
                root=REPO_ROOT,
                workspace=REPO_ROOT / ".smoke",
                project=REPO_ROOT / ".smoke" / "gunz",
                story_ids=["1.1"],
            )

        for env in (runner.env, dev.env):
            self.assertNotIn("BMAD_STORY_AUTOMATOR_ACTIVE_MARKER", env)
            self.assertNotIn("STORY_AUTOMATOR_ACTIVE_MARKER", env)
            self.assertNotIn("BMAD_SKILLS_ROOT", env)
            self.assertNotIn("BMAD_RUNTIME_PROVIDER", env)
            self.assertNotIn("STORY_AUTOMATOR_RUNTIME_PROVIDER", env)

    def test_smoke_prep_env_clears_host_overrides(self) -> None:
        automator = import_script_package("smoke_prep.automator")

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {
                    "BMAD_STORY_AUTOMATOR_ACTIVE_MARKER": "/tmp/outside-a",
                    "STORY_AUTOMATOR_ACTIVE_MARKER": "/tmp/outside-b",
                    "BMAD_SKILLS_ROOT": "/tmp/outside-skills",
                    "BMAD_RUNTIME_PROVIDER": "codex",
                    "STORY_AUTOMATOR_RUNTIME_PROVIDER": "codex",
                },
                clear=False,
            ):
                env = automator.smoke_env(Path(tmp))

        self.assertNotIn("BMAD_STORY_AUTOMATOR_ACTIVE_MARKER", env)
        self.assertNotIn("STORY_AUTOMATOR_ACTIVE_MARKER", env)
        self.assertNotIn("BMAD_SKILLS_ROOT", env)
        self.assertNotIn("BMAD_RUNTIME_PROVIDER", env)
        self.assertNotIn("STORY_AUTOMATOR_RUNTIME_PROVIDER", env)
        self.assertTrue(env["HOME"].startswith(tmp))
        self.assertTrue(env["NPM_CONFIG_CACHE"].startswith(tmp))

    def test_in_process_runners_clear_host_override_env_during_calls(self) -> None:
        modes = load_script_module("run_smoke_modes", SCRIPTS / "run-smoke-modes.py")
        finish = load_script_module("run_smoke_finish_loop", SCRIPTS / "run-smoke-finish-loop.py")

        def assert_clean_env(args):
            self.assertNotIn("BMAD_STORY_AUTOMATOR_ACTIVE_MARKER", os.environ)
            self.assertNotIn("STORY_AUTOMATOR_ACTIVE_MARKER", os.environ)
            self.assertNotIn("BMAD_SKILLS_ROOT", os.environ)
            self.assertNotIn("STORY_AUTOMATOR_RUNTIME_PROVIDER", os.environ)
            return 0

        def assert_mode_env(args):
            self.assertNotIn("BMAD_RUNTIME_PROVIDER", os.environ)
            return assert_clean_env(args)

        with patch.dict(
            os.environ,
            {
                "BMAD_STORY_AUTOMATOR_ACTIVE_MARKER": "/tmp/outside-a",
                "STORY_AUTOMATOR_ACTIVE_MARKER": "/tmp/outside-b",
                "BMAD_SKILLS_ROOT": "/tmp/outside-skills",
                "BMAD_RUNTIME_PROVIDER": "codex",
                "STORY_AUTOMATOR_RUNTIME_PROVIDER": "codex",
            },
            clear=False,
        ):
            mode_runner = modes.ModeSmokeRunner()
            finish_runner = finish.FinishLoopSmokeRunner()
            try:
                self.assertEqual(mode_runner._call(assert_mode_env, [])[0], 0)
                self.assertEqual(finish_runner._call(assert_clean_env, [])[0], 0)
            finally:
                mode_runner.close()
                finish_runner.close()

            self.assertEqual(os.environ["BMAD_STORY_AUTOMATOR_ACTIVE_MARKER"], "/tmp/outside-a")
            self.assertEqual(os.environ["STORY_AUTOMATOR_ACTIVE_MARKER"], "/tmp/outside-b")
            self.assertEqual(os.environ["BMAD_SKILLS_ROOT"], "/tmp/outside-skills")
            self.assertEqual(os.environ["BMAD_RUNTIME_PROVIDER"], "codex")
            self.assertEqual(os.environ["STORY_AUTOMATOR_RUNTIME_PROVIDER"], "codex")


class SmokePrepCliTests(unittest.TestCase):
    def test_smoke_input_check_malformed_payload_returns_clean_failure(self) -> None:
        module = load_script_module("check_smoke_inputs", SCRIPTS / "check-smoke-inputs.py")
        stderr = io.StringIO()

        with patch.object(module, "smoke_inputs", return_value={"gunz": {}}), redirect_stderr(stderr):
            code = module.main()

        self.assertEqual(code, 1)
        self.assertIn("smoke input determinism failed: malformed payload:", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_value_error_returns_clean_failure(self) -> None:
        cli = import_script_package("smoke_prep.cli")

        with tempfile.TemporaryDirectory() as tmp:
            stderr = io.StringIO()
            with (
                patch.object(cli, "repo_root", return_value=REPO_ROOT),
                patch.object(cli, "ensure_tool"),
                patch.object(cli, "resolve_workspace", return_value=Path(tmp)),
                patch.object(cli, "prepare_gunz"),
                patch.object(cli, "smoke_env", return_value={}),
                patch.object(cli, "smoke_inputs", side_effect=ValueError("bad smoke input")),
                redirect_stderr(stderr),
            ):
                code = cli.main([])

        self.assertEqual(code, 1)
        self.assertIn("smoke prep failed: bad smoke input", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_skip_automator_install_report_marks_artifacts_skipped(self) -> None:
        report = import_script_package("smoke_prep.report")

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            gunz = workspace / "gunz"
            gunz.mkdir()
            next_steps = report.write_next_steps(workspace, gunz, automator_installed=False)

            text = next_steps.read_text(encoding="utf-8")
            self.assertIn("package identity: skipped", text)
            self.assertIn("installed manifest: skipped", text)
            self.assertIn("project-local automator install skipped", text)
            self.assertNotIn("PACKAGE_IDENTITY.json`", text)
            self.assertNotIn("INSTALLED_AUTOMATOR_MANIFEST.json`", text)
            self.assertNotIn("bmad-story-automator/scripts/story-automator", text)

    def test_shared_process_run_times_out_cleanly(self) -> None:
        process = import_script_package("smoke_prep.process")

        with patch.object(
            process.subprocess,
            "run",
            side_effect=process.subprocess.TimeoutExpired(["git", "fetch"], 900),
        ):
            with self.assertRaisesRegex(process.SmokeError, "command timed out after 900s: git fetch"):
                process.run(["git", "fetch"], cwd=REPO_ROOT)

    def test_npm_view_timeout_becomes_smoke_error(self) -> None:
        inputs = import_script_package("smoke_prep.inputs")

        with patch.object(
            inputs.subprocess,
            "run",
            side_effect=inputs.subprocess.TimeoutExpired(["npm", "view"], 60),
        ):
            with self.assertRaisesRegex(inputs.SmokeError, "npm view timed out"):
                inputs._resolve_bmad_method({})

    def test_npm_view_non_object_metadata_becomes_smoke_error(self) -> None:
        inputs = import_script_package("smoke_prep.inputs")

        class Result:
            stdout = "[]"

        with patch.object(inputs.subprocess, "run", return_value=Result()):
            with self.assertRaisesRegex(inputs.SmokeError, "unexpected npm identity"):
                inputs._resolve_bmad_method({})

    def test_npm_view_malformed_metadata_becomes_smoke_error(self) -> None:
        inputs = import_script_package("smoke_prep.inputs")

        class BadJson:
            stdout = "{bad json"

        class BadDist:
            stdout = '{"version":"1.2.3","dist":[]}'

        class BadVersion:
            stdout = '{"version":["1.2.3"],"dist":{"integrity":"sha512-good"}}'

        class BadIntegrity:
            stdout = '{"version":"1.2.3","dist":{"integrity":["sha512-bad"]}}'

        with patch.object(inputs.subprocess, "run", return_value=BadJson()):
            with self.assertRaisesRegex(inputs.SmokeError, "unexpected npm identity"):
                inputs._resolve_bmad_method({})
        with patch.object(inputs.subprocess, "run", return_value=BadDist()):
            with self.assertRaisesRegex(inputs.SmokeError, "unexpected npm identity"):
                inputs._resolve_bmad_method({})
        for result in (BadVersion(), BadIntegrity()):
            with patch.object(inputs.subprocess, "run", return_value=result):
                with self.assertRaisesRegex(inputs.SmokeError, "missing npm identity"):
                    inputs._resolve_bmad_method({})

    def test_npm_pack_timeout_becomes_smoke_error(self) -> None:
        package_contracts = import_script_package("smoke_prep.package_contracts")

        with patch.object(
            package_contracts.subprocess,
            "run",
            side_effect=package_contracts.subprocess.TimeoutExpired(["npm", "pack"], 900),
        ):
            with self.assertRaisesRegex(package_contracts.SmokeError, "npm pack timed out after 900s"):
                package_contracts._npm_pack_json(REPO_ROOT, ["--json"], {})

    def test_npm_pack_malformed_metadata_becomes_smoke_error(self) -> None:
        package_contracts = import_script_package("smoke_prep.package_contracts")

        with self.assertRaisesRegex(package_contracts.SmokeError, "missing files list"):
            package_contracts._assert_content({})
        with self.assertRaisesRegex(package_contracts.SmokeError, "missing package fields"):
            package_contracts._assert_pack_metadata({}, {})
        with self.assertRaisesRegex(package_contracts.SmokeError, "malformed file entry"):
            package_contracts._assert_content({"files": [{}]})

    def test_package_json_decode_failure_becomes_smoke_error(self) -> None:
        package_contracts = import_script_package("smoke_prep.package_contracts")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text("{bad json", encoding="utf-8")
            with self.assertRaisesRegex(package_contracts.SmokeError, "invalid package.json"):
                package_contracts.assert_package_contract(root, {})
            with self.assertRaisesRegex(package_contracts.SmokeError, "invalid package.json"):
                package_contracts.pack_project(root, root / "dist", {})

    def test_workspace_check_ignore_uses_path_delimiter(self) -> None:
        workspace = import_script_package("smoke_prep.workspace")

        with patch.object(workspace.subprocess, "run") as run:
            run.return_value.returncode = 0
            resolved = workspace.resolve_workspace(REPO_ROOT, ".smoke")

        self.assertEqual(resolved, (REPO_ROOT / ".smoke").resolve())
        self.assertEqual(run.call_args.args[0], ["git", "check-ignore", "-q", "--", ".smoke"])


class SmokeModesScriptTests(unittest.TestCase):
    def test_help_exits_without_running_smoke(self) -> None:
        module = load_script_module("run_smoke_modes", SCRIPTS / "run-smoke-modes.py")

        with patch.object(module.ModeSmokeRunner, "run", side_effect=AssertionError("should not run")):
            with self.assertRaises(SystemExit) as caught:
                module.main(["--help"])

        self.assertEqual(caught.exception.code, 0)

    def test_runner_local_subprocesses_have_timeouts(self) -> None:
        automator = load_script_module("run_smoke_automator", SCRIPTS / "run-smoke-automator.py")
        dev_loop = load_script_module("run_smoke_dev_loop", SCRIPTS / "run-smoke-dev-loop.py")
        finish = load_script_module("run_smoke_finish_loop", SCRIPTS / "run-smoke-finish-loop.py")
        calls: list[dict[str, object]] = []

        def capture_run(*args, **kwargs):
            calls.append(kwargs)
            return subprocess.CompletedProcess(args[0], 0, stdout="{}", stderr="")

        with patch.object(automator.subprocess, "run", side_effect=capture_run):
            runner = automator.SmokeRunner(root=REPO_ROOT, workspace=REPO_ROOT / ".smoke", project=REPO_ROOT, story_id="1.1")
            runner._run("echo", "ok")
        with patch.object(dev_loop.subprocess, "run", side_effect=capture_run):
            runner = dev_loop.DevLoopSmokeRunner(root=REPO_ROOT, workspace=REPO_ROOT / ".smoke", project=REPO_ROOT, story_ids=["1.1"])
            runner._run("echo", "ok")
        with patch.object(finish.subprocess, "run", side_effect=capture_run):
            runner = finish.FinishLoopSmokeRunner()
            try:
                runner._run(["git", "status"], cwd=REPO_ROOT)
            finally:
                runner.close()

        self.assertEqual([call.get("timeout") for call in calls], [900, 900, 900])

    def test_json_objects_parses_concatenated_marker_output(self) -> None:
        module = load_script_module("run_smoke_modes", SCRIPTS / "run-smoke-modes.py")
        runner = module.ModeSmokeRunner()
        try:
            payloads = runner._json_objects(0, '{"exists":true}\n{"storiesRemaining":2}\n')
        finally:
            runner.close()

        self.assertEqual(payloads[0]["exists"], True)
        self.assertEqual(payloads[1]["storiesRemaining"], 2)

    def test_report_payload_persists_latest_incomplete_state(self) -> None:
        module = load_script_module("run_smoke_modes", SCRIPTS / "run-smoke-modes.py")
        runner = module.ModeSmokeRunner()
        state_file = runner.output / "orchestration-smoke.md"
        try:
            state_file.parent.mkdir(parents=True)
            state_file.write_text('status: "IN_PROGRESS"\n', encoding="utf-8")

            report, payload = runner.write_report(
                {
                    "project": str(runner.project),
                    "resume": {"latestIncomplete": str(state_file)},
                }
            )
            persisted = Path(payload["resume"]["latestIncomplete"])
        finally:
            runner.close()

        self.assertEqual(payload["project"]["kind"], "ephemeral")
        self.assertNotIn("path", payload["project"])
        self.assertTrue(persisted.exists())
        self.assertEqual(persisted.read_text(encoding="utf-8"), 'status: "IN_PROGRESS"\n')
        self.assertEqual(json.loads(report.read_text(encoding="utf-8")), payload)

    def test_report_payload_fails_closed_when_latest_incomplete_cannot_be_persisted(self) -> None:
        module = load_script_module("run_smoke_modes", SCRIPTS / "run-smoke-modes.py")
        runner = module.ModeSmokeRunner()
        try:
            missing = runner.output / "missing-state.md"
            with self.assertRaisesRegex(module.SmokeModesError, "failed to persist latest incomplete state"):
                runner.write_report(
                    {
                        "project": str(runner.project),
                        "resume": {"latestIncomplete": str(missing)},
                    }
                )
        finally:
            runner.close()


class SmokeStorySlugTests(unittest.TestCase):
    def test_automator_story_slug_ignores_unfound_sprint_status_story_echo(self) -> None:
        module = load_script_module("run_smoke_automator", SCRIPTS / "run-smoke-automator.py")
        runner = module.SmokeRunner(
            root=REPO_ROOT,
            workspace=REPO_ROOT / ".smoke",
            project=REPO_ROOT / ".smoke" / "gunz",
            story_id="1.1",
        )
        try:
            with patch.object(
                runner,
                "_helper_json",
                side_effect=[
                    {"found": False, "story": "1.1", "status": "not_found"},
                    {"title": "First Story"},
                ],
            ):
                slug = runner._story_slug()
        finally:
            runner.close()

        self.assertEqual(slug, "1-1-first-story")

    def test_dev_loop_story_slug_ignores_unfound_sprint_status_story_echo(self) -> None:
        module = load_script_module("run_smoke_dev_loop", SCRIPTS / "run-smoke-dev-loop.py")
        runner = module.DevLoopSmokeRunner(
            root=REPO_ROOT,
            workspace=REPO_ROOT / ".smoke",
            project=REPO_ROOT / ".smoke" / "gunz",
            story_ids=["1.1"],
        )
        try:
            with patch.object(
                runner,
                "_helper_json",
                side_effect=[
                    {"found": False, "story": "1.1", "status": "not_found"},
                    {"title": "First Story"},
                ],
            ):
                slug = runner._story_slug("1.1")
        finally:
            runner.close()

        self.assertEqual(slug, "1-1-first-story")


class FinishLoopSmokeScriptTests(unittest.TestCase):
    def test_ephemeral_descriptors_do_not_expose_cleaned_paths(self) -> None:
        module = load_script_module("run_smoke_finish_loop", SCRIPTS / "run-smoke-finish-loop.py")
        runner = module.FinishLoopSmokeRunner()
        try:
            project_descriptor = runner._ephemeral_project_descriptor()
            repo_descriptor = runner._repo_descriptor(runner.project)
        finally:
            runner.close()

        self.assertEqual(project_descriptor["kind"], "ephemeral")
        self.assertFalse(project_descriptor["retained"])
        self.assertNotIn("path", project_descriptor)
        self.assertEqual(repo_descriptor["kind"], "ephemeral")
        self.assertFalse(repo_descriptor["retained"])
        self.assertNotIn("path", repo_descriptor)

    def test_write_report_returns_persisted_payload_without_temp_paths(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git not available")
        module = load_script_module("run_smoke_finish_loop", SCRIPTS / "run-smoke-finish-loop.py")
        runner = module.FinishLoopSmokeRunner()
        try:
            runner.project.mkdir(parents=True)
            runner._init_git()
            state = runner.project / "orchestration-smoke.md"
            state.write_text('status: "COMPLETE"\n', encoding="utf-8")
            learnings = runner.output / "learnings.md"
            learnings.parent.mkdir(parents=True)
            learnings.write_text("## Learnings\n", encoding="utf-8")
            runner.results["wrapup"] = {"learnings": str(learnings.relative_to(runner.project))}
            payload = runner._write_report(state, [{"story": "1.1", "commit": "abc123"}], runner.project)
            report = Path(payload["report"])
            temp_root = runner.tmp.name
        finally:
            runner.close()

        persisted = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(persisted, payload)
        self.assertTrue(Path(payload["diagnostics"]["stateFile"]).exists())
        self.assertTrue(Path(payload["diagnostics"]["gitLog"]).exists())
        self.assertTrue(Path(payload["diagnostics"]["learnings"]).exists())
        self.assertEqual(payload["wrapup"]["learnings"], payload["diagnostics"]["learnings"])
        self.assert_no_temp_path(payload, temp_root)

    def test_json_rejects_non_object_payload(self) -> None:
        module = load_script_module("run_smoke_finish_loop", SCRIPTS / "run-smoke-finish-loop.py")
        runner = module.FinishLoopSmokeRunner()
        try:
            with self.assertRaisesRegex(module.FinishSmokeError, "helper returned non-object JSON"):
                runner._json(0, "[]")
        finally:
            runner.close()

    def assert_no_temp_path(self, value: object, temp_root: str) -> None:
        if isinstance(value, dict):
            for child in value.values():
                self.assert_no_temp_path(child, temp_root)
        elif isinstance(value, list):
            for child in value:
                self.assert_no_temp_path(child, temp_root)
        elif isinstance(value, str):
            self.assertNotIn(temp_root, value)


if __name__ == "__main__":
    unittest.main()
