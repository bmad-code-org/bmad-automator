from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


class SmokeError(RuntimeError):
    pass


MARKER_OVERRIDE_ENV = (
    "BMAD_STORY_AUTOMATOR_ACTIVE_MARKER",
    "STORY_AUTOMATOR_ACTIVE_MARKER",
)
HOST_OVERRIDE_ENV = (
    "BMAD_SKILLS_ROOT",
    "BMAD_RUNTIME_PROVIDER",
    "STORY_AUTOMATOR_RUNTIME_PROVIDER",
)


def scrub_host_overrides(env: dict[str, str]) -> dict[str, str]:
    for name in (*MARKER_OVERRIDE_ENV, *HOST_OVERRIDE_ENV):
        env.pop(name, None)
    return env


def deterministic_smoke_env(project: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = scrub_host_overrides(os.environ.copy())
    env["PROJECT_ROOT"] = str(project)
    env.update(extra or {})
    return env


def step(name: str) -> None:
    print(f"\n==> {name}", flush=True)


def run(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    capture: bool = False,
    check: bool = True,
    timeout_seconds: float | None = 900,
) -> subprocess.CompletedProcess[str]:
    print(f"+ ({cwd}) {' '.join(args)}", flush=True)
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            env=env,
            text=True,
            check=check,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.STDOUT if capture else None,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise SmokeError(f"command timed out after {timeout_seconds}s: {' '.join(args)}") from exc


def ensure_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise SmokeError(f"missing required tool: {name}")
