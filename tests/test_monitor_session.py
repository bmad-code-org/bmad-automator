from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from story_automator.commands import tmux as tmux_cmd
from story_automator.commands.tmux import cmd_monitor_session


def _completed_status(output_file: str = "/tmp/out.txt") -> dict[str, object]:
    return {
        "status": "idle",
        "todos_done": 0,
        "todos_total": 0,
        "active_task": output_file,
        "wait_estimate": 0,
        "session_state": "completed",
    }


def _active_status() -> dict[str, object]:
    return {
        "status": "active",
        "todos_done": 1,
        "todos_total": 3,
        "active_task": "working",
        "wait_estimate": 5,
        "session_state": "in_progress",
    }


class MonitorSessionRepollTests(unittest.TestCase):
    """The false-complete contract: re-confirm in-process instead of bouncing
    an ``incomplete`` the orchestrator would hand-poll (issue #29)."""

    def _run(self, *extra_args: str) -> dict[str, object]:
        stdout = io.StringIO()
        args = ["sess", "--agent", "claude", "--initial-wait", "0", "--json", "--workflow", "create", *extra_args]
        with (
            patch.object(tmux_cmd, "_resolve_agent_selection", return_value="claude"),
            patch.object(tmux_cmd, "runtime_mode", return_value="runner"),
            patch.object(tmux_cmd.time, "sleep", return_value=None),
            redirect_stdout(stdout),
        ):
            code = cmd_monitor_session(args)
        self.assertEqual(code, 0)
        return json.loads(stdout.getvalue().strip().splitlines()[-1])

    def test_verified_completion_returns_immediately(self) -> None:
        verify = patch.object(
            tmux_cmd,
            "_verify_monitor_completion",
            return_value=({"verified": True}, "story_create"),
        )
        with patch.object(tmux_cmd, "session_status", return_value=_completed_status()), verify as verify_mock:
            payload = self._run()
        self.assertEqual(payload["final_state"], "completed")
        self.assertTrue(payload["output_verified"])
        self.assertEqual(verify_mock.call_count, 1)

    def test_false_complete_rechecks_then_incomplete(self) -> None:
        verify = patch.object(
            tmux_cmd,
            "_verify_monitor_completion",
            return_value=({"verified": False, "reason": "story_missing"}, "story_create"),
        )
        with patch.object(tmux_cmd, "session_status", return_value=_completed_status()), verify as verify_mock:
            payload = self._run()  # default completion_rechecks == 3
        self.assertEqual(payload["final_state"], "incomplete")
        self.assertEqual(payload["exit_reason"], "story_missing")
        # Re-confirmed in-process 3 times before giving up — never bounced early.
        self.assertEqual(verify_mock.call_count, 3)

    def test_recheck_recovers_when_verifier_passes(self) -> None:
        verify = patch.object(
            tmux_cmd,
            "_verify_monitor_completion",
            side_effect=[
                ({"verified": False, "reason": "not_yet"}, "story_create"),
                ({"verified": True}, "story_create"),
            ],
        )
        with patch.object(tmux_cmd, "session_status", return_value=_completed_status()), verify as verify_mock:
            payload = self._run()
        self.assertEqual(payload["final_state"], "completed")
        self.assertTrue(payload["output_verified"])
        self.assertEqual(verify_mock.call_count, 2)

    def test_completion_rechecks_one_disables_repoll(self) -> None:
        verify = patch.object(
            tmux_cmd,
            "_verify_monitor_completion",
            return_value=({"verified": False, "reason": "story_missing"}, "story_create"),
        )
        with patch.object(tmux_cmd, "session_status", return_value=_completed_status()), verify as verify_mock:
            payload = self._run("--completion-rechecks", "1")
        self.assertEqual(payload["final_state"], "incomplete")
        self.assertEqual(verify_mock.call_count, 1)

    def test_false_complete_void_when_session_resumes_activity(self) -> None:
        # completed(unverified) -> active again -> completed(verified): the
        # transient idle must not count toward the recheck budget.
        statuses = [_completed_status(), _completed_status(), _active_status(), _completed_status(), _completed_status()]
        verify = patch.object(
            tmux_cmd,
            "_verify_monitor_completion",
            side_effect=[
                ({"verified": False, "reason": "not_yet"}, "story_create"),
                ({"verified": True}, "story_create"),
            ],
        )
        with patch.object(tmux_cmd, "session_status", side_effect=statuses), verify:
            payload = self._run()
        self.assertEqual(payload["final_state"], "completed")
        self.assertTrue(payload["output_verified"])


if __name__ == "__main__":
    unittest.main()
