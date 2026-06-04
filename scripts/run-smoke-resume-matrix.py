#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys


MODULES = [
    "tests.test_resume_matrix",
]


def main() -> int:
    cmd = [sys.executable, "-m", "unittest", *MODULES]
    completed = subprocess.run(cmd, text=True, capture_output=True)
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
