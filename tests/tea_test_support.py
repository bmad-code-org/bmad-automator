from __future__ import annotations

import json
import shutil
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class patch_env:
    def __init__(self, project_root: Path, extra: dict[str, str] | None = None) -> None:
        self.project_root = str(project_root)
        self.extra = extra or {}
        self.previous: dict[str, str | None] = {}

    def __enter__(self) -> None:
        import os

        self.previous["PROJECT_ROOT"] = os.environ.get("PROJECT_ROOT")
        os.environ["PROJECT_ROOT"] = self.project_root
        for key, value in self.extra.items():
            self.previous[key] = os.environ.get(key)
            os.environ[key] = value

    def __exit__(self, exc_type, exc, tb) -> None:
        import os

        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def install_bundle(project_root: Path) -> None:
    source_skill = REPO_ROOT / "skills" / "bmad-story-automator"
    source_review = REPO_ROOT / "skills" / "bmad-story-automator-review"
    target_root = project_root / ".claude" / "skills"
    target_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_skill, target_root / "bmad-story-automator")
    shutil.copytree(source_review, target_root / "bmad-story-automator-review")


def install_required_skills(project_root: Path) -> None:
    for name in ("bmad-create-story", "bmad-dev-story", "bmad-retrospective", "bmad-qa-generate-e2e-tests"):
        skill_dir = project_root / ".claude" / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
        (skill_dir / "workflow.md").write_text(f"# {name}\n", encoding="utf-8")
    (project_root / ".claude" / "skills" / "bmad-create-story" / "discover-inputs.md").write_text(
        "# discover\n", encoding="utf-8"
    )
    (project_root / ".claude" / "skills" / "bmad-create-story" / "checklist.md").write_text(
        "# checklist\n", encoding="utf-8"
    )
    (project_root / ".claude" / "skills" / "bmad-create-story" / "template.md").write_text(
        "# template\n", encoding="utf-8"
    )
    (project_root / ".claude" / "skills" / "bmad-dev-story" / "checklist.md").write_text(
        "# checklist\n", encoding="utf-8"
    )
    (project_root / ".claude" / "skills" / "bmad-qa-generate-e2e-tests" / "checklist.md").write_text(
        "# checklist\n", encoding="utf-8"
    )


def install_tea_skills(
    project_root: Path,
    *,
    include_nfr: bool = False,
    canonical: bool = False,
    write_assets: bool = True,
) -> None:
    if write_assets:
        write_tea_assets(project_root)
    else:
        (project_root / "_bmad" / "tea" / "workflows" / "testarch").mkdir(parents=True, exist_ok=True)
    prefix = "bmad-testarch" if canonical else "bmad-tea-testarch"
    names = [
        f"{prefix}-atdd",
        f"{prefix}-automate",
        f"{prefix}-test-review",
        f"{prefix}-trace",
    ]
    if include_nfr:
        names.append(f"{prefix}-nfr")
    for name in names:
        skill_dir = project_root / ".claude" / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
        (skill_dir / "workflow.md").write_text(f"# {name}\n", encoding="utf-8")


def write_tea_assets(project_root: Path, *, root: Path | None = None) -> None:
    base = root or (project_root / "_bmad" / "tea" / "story-automator")
    prompts = base / "prompts"
    parse = base / "parse"
    prompts.mkdir(parents=True, exist_ok=True)
    parse.mkdir(parents=True, exist_ok=True)
    (prompts / "atdd.md").write_text("ATDD {{story_id}}\n", encoding="utf-8")
    (prompts / "test_automate.md").write_text("TEST AUTOMATE {{story_id}}\n", encoding="utf-8")
    (prompts / "test_review.md").write_text("TEST REVIEW {{story_id}}\n", encoding="utf-8")
    (prompts / "nfr.md").write_text("NFR {{story_id}}\n", encoding="utf-8")
    (prompts / "trace.md").write_text("TRACE {{story_id}}\n", encoding="utf-8")
    (parse / "atdd.json").write_text(
        json.dumps(
            {
                "requiredKeys": ["status", "failing_tests_created", "summary", "next_action"],
                "schema": {
                    "status": "SUCCESS|FAILURE|AMBIGUOUS",
                    "failing_tests_created": "true|false",
                    "summary": "brief description",
                    "next_action": "proceed|retry|escalate",
                },
            }
        ),
        encoding="utf-8",
    )
    (parse / "test_automate.json").write_text(
        json.dumps(
            {
                "requiredKeys": ["status", "tests_added", "summary", "next_action"],
                "schema": {
                    "status": "SUCCESS|FAILURE|AMBIGUOUS",
                    "tests_added": "integer",
                    "summary": "brief description",
                    "next_action": "proceed|retry|escalate",
                },
            }
        ),
        encoding="utf-8",
    )
    (parse / "test_review.json").write_text(
        json.dumps(
            {
                "requiredKeys": ["status", "issues_found", "summary", "next_action"],
                "schema": {
                    "status": "SUCCESS|FAILURE|AMBIGUOUS",
                    "issues_found": "integer",
                    "summary": "brief description",
                    "next_action": "proceed|retry|escalate",
                },
            }
        ),
        encoding="utf-8",
    )
    (parse / "nfr.json").write_text(
        json.dumps(
            {
                "requiredKeys": ["status", "nfr_report_created", "summary", "next_action"],
                "schema": {
                    "status": "SUCCESS|FAILURE|AMBIGUOUS",
                    "nfr_report_created": "true|false",
                    "summary": "brief description",
                    "next_action": "proceed|retry|escalate",
                },
            }
        ),
        encoding="utf-8",
    )
    (parse / "trace.json").write_text(
        json.dumps(
            {
                "requiredKeys": ["status", "trace_updated", "summary", "next_action"],
                "schema": {
                    "status": "SUCCESS|FAILURE|AMBIGUOUS",
                    "trace_updated": "true|false",
                    "summary": "brief description",
                    "next_action": "proceed|retry|escalate",
                },
            }
        ),
        encoding="utf-8",
    )


def tea_steps_override(
    *,
    include_nfr: bool = False,
    canonical: bool = False,
    assets_root: str = "_bmad/tea/story-automator",
) -> dict[str, object]:
    prefix = "bmad-testarch" if canonical else "bmad-tea-testarch"
    steps: dict[str, object] = {
        "atdd": {
            "label": "atdd",
            "assets": {
                "skillName": f"{prefix}-atdd",
                "workflowCandidates": ["workflow.md", "workflow.yaml"],
                "instructionsCandidates": [],
                "checklistCandidates": ["checklist.md"],
                "templateCandidates": [],
                "required": ["skill"],
            },
            "prompt": {"templateFile": f"{assets_root}/prompts/atdd.md", "interactionMode": "autonomous"},
            "parse": {"schemaFile": f"{assets_root}/parse/atdd.json"},
            "success": {"verifier": "session_exit"},
        },
        "test_automate": {
            "label": "test-automate",
            "assets": {
                "skillName": f"{prefix}-automate",
                "workflowCandidates": ["workflow.md", "workflow.yaml"],
                "instructionsCandidates": [],
                "checklistCandidates": ["checklist.md"],
                "templateCandidates": [],
                "required": ["skill"],
            },
            "prompt": {"templateFile": f"{assets_root}/prompts/test_automate.md", "interactionMode": "autonomous"},
            "parse": {"schemaFile": f"{assets_root}/parse/test_automate.json"},
            "success": {"verifier": "session_exit"},
        },
        "test_review": {
            "label": "test-review",
            "assets": {
                "skillName": f"{prefix}-test-review",
                "workflowCandidates": ["workflow.md", "workflow.yaml"],
                "instructionsCandidates": [],
                "checklistCandidates": ["checklist.md"],
                "templateCandidates": [],
                "required": ["skill"],
            },
            "prompt": {"templateFile": f"{assets_root}/prompts/test_review.md", "interactionMode": "autonomous"},
            "parse": {"schemaFile": f"{assets_root}/parse/test_review.json"},
            "success": {"verifier": "session_exit"},
        },
        "trace": {
            "label": "trace",
            "assets": {
                "skillName": f"{prefix}-trace",
                "workflowCandidates": ["workflow.md", "workflow.yaml"],
                "instructionsCandidates": [],
                "checklistCandidates": ["checklist.md"],
                "templateCandidates": [],
                "required": ["skill"],
            },
            "prompt": {"templateFile": f"{assets_root}/prompts/trace.md", "interactionMode": "autonomous"},
            "parse": {"schemaFile": f"{assets_root}/parse/trace.json"},
            "success": {"verifier": "session_exit"},
        },
    }
    if include_nfr:
        steps["nfr"] = {
            "label": "nfr",
            "assets": {
                "skillName": f"{prefix}-nfr",
                "workflowCandidates": ["workflow.md", "workflow.yaml"],
                "instructionsCandidates": [],
                "checklistCandidates": ["checklist.md"],
                "templateCandidates": [],
                "required": ["skill"],
            },
            "prompt": {"templateFile": f"{assets_root}/prompts/nfr.md", "interactionMode": "autonomous"},
            "parse": {"schemaFile": f"{assets_root}/parse/nfr.json"},
            "success": {"verifier": "session_exit"},
        }
    return steps
