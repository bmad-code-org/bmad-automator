from __future__ import annotations

from pathlib import Path
from typing import Any

from .runtime_layout import bundled_story_skill_root, resolve_skill_dir
from .utils import file_exists
from .workflow_steps import WORKFLOW_STEPS, tea_required_steps, tea_skill_aliases


def tea_assets_root(project_root: Path, config: dict[str, Any]) -> str:
    configured = str(config.get("teaAssetsRoot") or "").strip()
    if configured:
        return configured.rstrip("/")
    return tea_detected_assets_root(project_root)


def tea_asset_root_candidates(project_root: Path) -> list[str]:
    candidates = [
        "_bmad/tea/story-automator",
        "docs/plans/tea-story-automator/assets",
        "data/tea-story-automator",
    ]
    unique: list[str] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def tea_assets_base_path(project_root: Path, assets_root: str) -> Path | None:
    raw = Path(assets_root)
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw.resolve())
    else:
        candidates.append((project_root / raw).resolve())
        try:
            bundle_root = bundled_story_skill_root(project_root)
            candidates.append((bundle_root / raw).resolve())
        except FileNotFoundError:
            pass
    first_existing: Path | None = None
    for candidate in candidates:
        if not candidate.exists():
            continue
        if first_existing is None:
            first_existing = candidate
        if tea_assets_complete_for_base(candidate):
            return candidate
    if first_existing is not None:
        return first_existing
    return candidates[0] if candidates else None


def tea_assets_complete_for_base(base: Path | None) -> bool:
    if base is None or not base.exists():
        return False
    if (base / "prompts" / "tea_step.md").is_file() and (base / "parse" / "tea_step.json").is_file():
        return True
    required = [
        base / "prompts" / "atdd.md",
        base / "prompts" / "test_automate.md",
        base / "prompts" / "test_review.md",
        base / "prompts" / "trace.md",
        base / "parse" / "atdd.json",
        base / "parse" / "test_automate.json",
        base / "parse" / "test_review.json",
        base / "parse" / "trace.json",
    ]
    return all(path.is_file() for path in required)


def tea_detected_assets_root(project_root: Path) -> str:
    for assets_root in tea_asset_root_candidates(project_root):
        if tea_assets_complete_for_base(tea_assets_base_path(project_root, assets_root)):
            return assets_root
    return "data/tea-story-automator"


def tea_contract_files(project_root: Path, assets_root: str, step: str) -> tuple[str, str]:
    base = tea_assets_base_path(project_root, assets_root)
    root = assets_root.rstrip("/")
    generic_prompt = f"{root}/prompts/tea_step.md"
    generic_schema = f"{root}/parse/tea_step.json"
    if base is None:
        return generic_prompt, generic_schema
    if (base / "prompts" / f"{step}.md").is_file() and (base / "parse" / f"{step}.json").is_file():
        return f"{root}/prompts/{step}.md", f"{root}/parse/{step}.json"
    return generic_prompt, generic_schema


def resolve_tea_skill_name(project_root: Path, step: str) -> str:
    candidates = tea_skill_aliases(step)
    for skill_name in candidates:
        try:
            skill_dir = resolve_skill_dir(project_root, skill_name)
        except ValueError:
            continue
        if file_exists(str(skill_dir / "SKILL.md")):
            return skill_name
    return candidates[0] if candidates else ""


def tea_skill_installed(project_root: Path, step: str) -> bool:
    for skill_name in tea_skill_aliases(step):
        try:
            skill_dir = resolve_skill_dir(project_root, skill_name)
        except ValueError:
            continue
        if file_exists(str(skill_dir / "SKILL.md")):
            return True
    return False


def tea_step_contracts(project_root: Path, assets_root: str, *, include_nfr: bool) -> dict[str, Any]:
    steps: dict[str, Any] = {}
    for step in tea_required_steps(include_nfr):
        prompt, schema = tea_contract_files(project_root, assets_root, step)
        steps[step] = {
            "label": WORKFLOW_STEPS[step].label,
            "assets": {
                "skillName": resolve_tea_skill_name(project_root, step),
                "workflowCandidates": ["workflow.md", "workflow.yaml"],
                "instructionsCandidates": [],
                "checklistCandidates": ["checklist.md"],
                "templateCandidates": [],
                "required": ["skill"],
            },
            "prompt": {"templateFile": prompt, "interactionMode": "autonomous"},
            "parse": {"schemaFile": schema},
            "success": {"verifier": "session_exit"},
        }
    return steps


def tea_assets_complete(project_root: Path, assets_root: str) -> tuple[bool, list[str]]:
    if not assets_root:
        return False, ["missing TEA story-automator assets root"]
    base = tea_assets_base_path(project_root, assets_root)
    if base is None or not base.exists():
        return False, ["missing TEA story-automator assets root"]
    if tea_assets_complete_for_base(base):
        return True, []
    required = [
        base / "prompts" / "atdd.md",
        base / "prompts" / "test_automate.md",
        base / "prompts" / "test_review.md",
        base / "prompts" / "trace.md",
        base / "parse" / "atdd.json",
        base / "parse" / "test_automate.json",
        base / "parse" / "test_review.json",
        base / "parse" / "trace.json",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    return False, missing


def tea_project_signals(project_root: Path) -> list[str]:
    signals: list[str] = []
    checks = {
        "_bmad/tea/config.yaml": project_root / "_bmad" / "tea" / "config.yaml",
        "_bmad/tea/module-help.csv": project_root / "_bmad" / "tea" / "module-help.csv",
        "_bmad/tea/workflows/testarch": project_root / "_bmad" / "tea" / "workflows" / "testarch",
        "_bmad/tea/story-automator": project_root / "_bmad" / "tea" / "story-automator",
    }
    for label, path in checks.items():
        if path.exists():
            signals.append(label)
    return signals


def tea_skill_availability(project_root: Path, required_steps: list[str] | None = None) -> tuple[list[str], list[str]]:
    available: list[str] = []
    missing: list[str] = []
    for step in (required_steps or tea_required_steps()):
        skill_name = resolve_tea_skill_name(project_root, step)
        aliases = tea_skill_aliases(step)
        missing_name = aliases[0] if aliases else step
        if not skill_name:
            missing.append(missing_name)
            continue
        try:
            skill_dir = resolve_skill_dir(project_root, skill_name)
        except ValueError:
            missing.append(missing_name)
            continue
        if file_exists(str(skill_dir / "SKILL.md")):
            available.append(skill_name)
        else:
            missing.append(missing_name)
    return available, missing


def resolved_explicit_tea_status(policy: dict[str, Any], required_steps: list[str]) -> tuple[list[str], str]:
    available: list[str] = []
    asset_roots: list[str] = []
    steps = policy.get("steps") or {}
    for step in required_steps:
        if not isinstance(steps.get(step), dict):
            continue
        contract = steps[step]
        assets = contract.get("assets") or {}
        skill_name = str(assets.get("skillName") or "").strip()
        if skill_name:
            available.append(skill_name)
        prompt = contract.get("prompt") or {}
        template_file = str(prompt.get("templateFile") or "").strip()
        if template_file:
            root = str(Path(template_file).parent.parent).replace("\\", "/")
            if root and root not in asset_roots:
                asset_roots.append(root)
    return available, ", ".join(asset_roots)


def explicit_tea_assets_status(project_root: Path, payload: dict[str, Any], required_steps: list[str]) -> tuple[str, list[str]]:
    steps = payload.get("steps") if isinstance(payload.get("steps"), dict) else {}
    asset_roots: list[str] = []
    missing_assets: list[str] = []
    for step in required_steps:
        contract = steps.get(step)
        if not isinstance(contract, dict):
            continue
        prompt = contract.get("prompt") or {}
        template_file = str(prompt.get("templateFile") or "").strip()
        if not template_file:
            continue
        root = str(Path(template_file).parent.parent).replace("\\", "/")
        if not root or root in asset_roots:
            continue
        asset_roots.append(root)
        _, missing = tea_assets_complete(project_root, root)
        missing_assets.extend(missing)
    if not asset_roots:
        return "", ["missing TEA story-automator assets root"]
    dedup_missing = list(dict.fromkeys(missing_assets))
    return ", ".join(asset_roots), dedup_missing
