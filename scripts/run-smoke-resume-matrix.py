#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


MODULES = [
    "tests.test_resume_matrix",
]


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    pythonpath = str(repo_root / "skills" / "bmad-story-automator" / "src")
    existing = env.get("PYTHONPATH", "").strip()
    env["PYTHONPATH"] = pythonpath if not existing else f"{pythonpath}{os.pathsep}{existing}"
    cmd = [sys.executable, "-m", "unittest", *MODULES]
    completed = subprocess.run(cmd, text=True, capture_output=True, cwd=repo_root, env=env)
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
