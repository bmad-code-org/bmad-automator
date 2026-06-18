from __future__ import annotations

import shlex
from pathlib import Path

from .config import BMAD_METHOD_NPM_SPEC, BRANCH, PINNED_COMMIT, REPO_URL


def write_next_steps(workspace: Path, gunz_dir: Path, *, automator_installed: bool = True) -> Path:
    next_steps = workspace / "SMOKE_NEXT_STEPS.md"
    helper = (
        gunz_dir
        / ".claude"
        / "skills"
        / "bmad-story-automator"
        / "scripts"
        / "story-automator"
    )
    quoted_gunz_dir = shlex.quote(str(gunz_dir))
    quoted_helper = shlex.quote(str(helper))
    helper_lines = (
        [
            "Helper sanity check:",
            "",
            "```bash",
            f"{quoted_helper} --help",
            "```",
        ]
        if automator_installed
        else [
            "Helper sanity check:",
            "",
            "- skipped by `--skip-automator-install`",
        ]
    )
    next_steps.write_text(
        "\n".join(
            [
                "# Story Automator Smoke",
                "",
                "Prepared project:",
                "",
                f"```text\n{gunz_dir}\n```",
                "",
                "Pinned source:",
                "",
                f"- repo: `{REPO_URL}`",
                f"- branch: `{BRANCH}`",
                f"- commit: `{PINNED_COMMIT}`",
                f"- deterministic input manifest: `{workspace / 'SMOKE_INPUTS.json'}`",
                f"- package identity: `{workspace / 'PACKAGE_IDENTITY.json'}`" if automator_installed else "- package identity: skipped by `--skip-automator-install`",
                f"- installed manifest: `{workspace / 'INSTALLED_AUTOMATOR_MANIFEST.json'}`" if automator_installed else "- installed manifest: skipped by `--skip-automator-install`",
                "",
                "Installed pieces:",
                "",
                f"- BMAD core and BMM via `{BMAD_METHOD_NPM_SPEC}`",
                "- project-local `bmad-story-automator` packed from this checkout" if automator_installed else "- project-local automator install skipped",
                "",
                "Manual smoke start:",
                "",
                "```bash",
                f"cd {quoted_gunz_dir}",
                "claude",
                "```",
                "",
                "Then ask Claude Code:",
                "",
                "```text",
                "Use the bmad-story-automator skill. Run the smoke test in this repo.",
                "```",
                "",
                *helper_lines,
                "",
            ]
        ),
        encoding="utf-8",
    )
    return next_steps
