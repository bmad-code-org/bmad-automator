#!/usr/bin/env python3
from __future__ import annotations

import sys
from subprocess import CalledProcessError

from smoke_prep.inputs import smoke_inputs
from smoke_prep.process import SmokeError


def main() -> int:
    try:
        inputs = smoke_inputs()
    except (CalledProcessError, OSError, ValueError, SmokeError) as exc:
        print(f"smoke input determinism failed: {exc}", file=sys.stderr)
        return 1

    try:
        gunz = inputs["gunz"]
        bmad = inputs["bmadMethod"]
        repo = gunz["repo"]
        branch = gunz["branch"]
        commit = gunz["commit"]
        spec = bmad["spec"]
        resolved_version = bmad["resolvedVersion"]
        install_spec = bmad["installSpec"]
        integrity = bmad["integrity"]
    except (KeyError, TypeError) as exc:
        print(f"smoke input determinism failed: malformed payload: {exc}", file=sys.stderr)
        return 1

    print("smoke input determinism ok")
    print(f"- repo: {repo}")
    print(f"- branch: {branch}")
    print(f"- commit: {commit}")
    print(f"- bmad method npm spec: {spec}")
    print(f"- bmad method resolved version: {resolved_version}")
    print(f"- bmad method install spec: {install_spec}")
    print(f"- bmad method integrity: {integrity}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
