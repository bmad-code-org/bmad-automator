#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


MODULES = [
    "tests.test_policy_invariants",
    "tests.test_progress_invariants",
]


def _to_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return ""


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    pythonpath = str(repo_root / "skills" / "bmad-story-automator" / "src")
    existing = env.get("PYTHONPATH", "").strip()
    env["PYTHONPATH"] = pythonpath if not existing else f"{pythonpath}{os.pathsep}{existing}"
    cmd = [sys.executable, "-m", "unittest", *MODULES]
    try:
        completed = subprocess.run(cmd, text=True, capture_output=True, cwd=repo_root, env=env, timeout=600)
    except subprocess.TimeoutExpired as exc:
        stdout = _to_text(exc.stdout)
        stderr = _to_text(exc.stderr)
        payload = {
            "ok": False,
            "modules": MODULES,
            "returncode": 124,
            "stdout": stdout,
            "stderr": (stderr + "\nTimed out after 600 seconds").strip(),
        }
        print(json.dumps(payload))
        return 124
    payload = {
        "ok": completed.returncode == 0,
        "modules": MODULES,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    print(json.dumps(payload))
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
