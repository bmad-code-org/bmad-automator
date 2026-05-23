from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..core.frontmatter import extract_frontmatter, parse_simple_frontmatter
from ..core.runtime_layout import bundled_story_skill_root, resolve_skill_dir
from ..core.runtime_policy import PolicyError, load_policy_for_state, snapshot_effective_policy
from ..core.utils import count_matches, ensure_dir, file_exists, get_project_root, now_utc, now_utc_z, read_text, write_json


STANDARD_SEQUENCE = ["create", "dev", "auto", "review", "retro"]
TEA_SKILL_ALIASES = {
    "atdd": ("bmad-testarch-atdd", "bmad-tea-testarch-atdd"),
    "test_automate": ("bmad-testarch-automate", "bmad-tea-testarch-automate"),
    "test_review": ("bmad-testarch-test-review", "bmad-tea-testarch-test-review"),
    "trace": ("bmad-testarch-trace", "bmad-tea-testarch-trace"),
    "nfr": ("bmad-testarch-nfr", "bmad-tea-testarch-nfr"),
}

STEP_DISPLAY_NAMES = {
    "create": "create-story",
    "dev": "dev-story",
    "auto": "automate",
    "review": "code-review",
    "atdd": "atdd",
    "test_automate": "test-automate",
    "test_review": "test-review",
    "nfr": "nfr",
    "trace": "trace",
}


def _story_progress_steps(policy: dict[str, Any]) -> list[str]:
    sequence = ((policy.get("workflow") or {}).get("sequence")) or []
    return [str(step) for step in sequence if isinstance(step, str) and step and step != "retro"]


def _progress_headers(steps: list[str]) -> list[str]:
    headers = ["Story"]
    headers.extend(STEP_DISPLAY_NAMES.get(step, step.replace("_", "-")) for step in steps)
    headers.extend(["git-commit", "Status"])
    return headers


def _markdown_divider(width: int) -> list[str]:
    return ["-------" if idx == 0 else "----------" for idx in range(width)]


def _progress_table_lines(policy: dict[str, Any], story_range: list[str]) -> tuple[str, str, str]:
    steps = _story_progress_steps(policy)
    headers = _progress_headers(steps)
    divider = _markdown_divider(len(headers))
    pending_cells = ["⏳"] * len(steps) + ["⏳", "pending"]
    rows = "\n".join("| " + " | ".join([story_id, *pending_cells]) + " |" for story_id in story_range)
    return (
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(divider) + " |",
        rows,
    )


def cmd_build_state_doc(args: list[str]) -> int:
    template = ""
    output_folder = ""
    config_file = ""
    config_json = ""
    for idx, arg in enumerate(args):
        if arg == "--template" and idx + 1 < len(args):
            template = args[idx + 1]
        elif arg == "--output-folder" and idx + 1 < len(args):
            output_folder = args[idx + 1]
        elif arg == "--config-file" and idx + 1 < len(args):
            config_file = args[idx + 1]
        elif arg == "--config-json" and idx + 1 < len(args):
            config_json = args[idx + 1]
    if not template or not file_exists(template) or not output_folder:
        write_json({"ok": False, "error": "missing_template_or_output"})
        return 1
    if config_file and file_exists(config_file):
        config_json = read_text(config_file)
    if not config_json.strip():
        write_json({"ok": False, "error": "missing_config"})
        return 1
    try:
        config = json.loads(config_json)
    except json.JSONDecodeError:
        write_json({"ok": False, "error": "missing_config"})
        return 1
    ensure_dir(output_folder)
    now = now_utc_z()
    stamp = now_utc().strftime("%Y%m%d-%H%M%S")
    epic = str(config.get("epic") or "epic")
    safe_epic = re.sub(r"[^a-zA-Z0-9]+", "-", epic).strip("-") or "epic"
    output_path = Path(output_folder) / f"orchestration-{safe_epic}-{stamp}.md"
    policy_selection = _build_run_policy(Path(get_project_root()), config)
    try:
        snapshot = snapshot_effective_policy(get_project_root(), inline_override=policy_selection["policyOverride"])
    except (FileNotFoundError, PolicyError, ValueError) as exc:
        write_json({"ok": False, "error": "policy_snapshot_failed", "reason": str(exc)})
        return 1
    progress_header, progress_divider, progress_rows = _progress_table_lines(snapshot["policy"], [item for item in config.get("storyRange", []) if isinstance(item, str)])
    text = read_text(template)
    replacements: dict[str, Any] = {
        "epic": config.get("epic", ""),
        "epicName": config.get("epicName", ""),
        "storyRange": config.get("storyRange", []),
        "status": config.get("status", "READY"),
        "currentStory": config.get("currentStory"),
        "currentStep": config.get("currentStep"),
        "stepsCompleted": config.get("stepsCompleted", []),
        "lastUpdated": now,
        "createdAt": now,
        "aiCommand": config.get("aiCommand", ""),
        "agentsFile": config.get("agentsFile", ""),
        "complexityFile": config.get("complexityFile", ""),
        "policyVersion": snapshot["policyVersion"],
        "policySnapshotFile": snapshot["policySnapshotFile"],
        "policySnapshotHash": snapshot["policySnapshotHash"],
        "legacyPolicy": False,
    }
    overrides = config.get("overrides", {}) if isinstance(config.get("overrides"), dict) else {}
    text = re.sub(
        r"(?m)^overrides:\n(?:(?:\s{2}.*\n)*)",
        "overrides:\n"
        f"  skipAutomate: {str(bool(overrides.get('skipAutomate', False))).lower()}\n"
        f"  maxParallel: {int(overrides.get('maxParallel', 1) or 1)}\n",
        text,
    )
    custom_instructions = json.dumps(config.get("customInstructions", ""))
    text = re.sub(r"(?m)^customInstructions:.*$", lambda m: f"customInstructions: {custom_instructions}", text)
    if policy_selection["workflowTrack"] == "tea":
        tea_frontmatter = (
            f'workflowTrack: {json.dumps(policy_selection["workflowTrack"])}\n'
            f"selectedOptionalSteps: {json.dumps(policy_selection['selectedOptionalSteps'])}\n"
            f"manualCheckpoints: {json.dumps(policy_selection['manualCheckpoints'])}\n"
            f"policyNotes: {json.dumps(policy_selection['notes'])}\n"
        )
        text = text.replace("customInstructions: " + custom_instructions + "\n", "customInstructions: " + custom_instructions + "\n" + tea_frontmatter)
    agent_config = config.get("agentConfig")
    if isinstance(agent_config, dict):
        per_task = agent_config.get("perTask", {})
        if not isinstance(per_task, dict):
            per_task = {}
        legacy_retro = agent_config.get("retro")
        if isinstance(legacy_retro, dict) and "retro" not in per_task:
            per_task = {**per_task, "retro": legacy_retro}
        default_fallback = agent_config.get("defaultFallback")
        if "defaultFallback" not in agent_config:
            default_fallback = agent_config.get("fallback", False)
        if default_fallback is None:
            default_fallback = False
        default_primary = agent_config.get("defaultPrimary")
        if default_primary is None:
            default_primary = agent_config.get("primary") or "auto"

        lines = [
            "agentConfig:",
            f"  defaultPrimary: {json.dumps(default_primary)}",
            f"  defaultFallback: {json.dumps(default_fallback)}",
        ]
        if isinstance(per_task, dict) and per_task:
            lines.append("  perTask:")
            for task in sorted(per_task):
                entry = per_task[task]
                if not isinstance(entry, dict):
                    continue
                lines.append(f"    {task}:")
                if "primary" in entry:
                    lines.append(f"      primary: {json.dumps(entry['primary'])}")
                if "fallback" in entry:
                    value = entry["fallback"]
                    lines.append(f"      fallback: {'false' if value is False else json.dumps(value)}")
        complexity_overrides = agent_config.get("complexityOverrides", {})
        if isinstance(complexity_overrides, dict) and complexity_overrides:
            lines.append("  complexityOverrides:")
            for level in sorted(complexity_overrides):
                task_map = complexity_overrides[level]
                if not isinstance(task_map, dict) or not task_map:
                    continue
                lines.append(f"    {level}:")
                for task in sorted(task_map):
                    entry = task_map[task]
                    if not isinstance(entry, dict):
                        continue
                    lines.append(f"      {task}:")
                    if "primary" in entry:
                        lines.append(f"        primary: {json.dumps(entry['primary'])}")
                    if "fallback" in entry:
                        value = entry["fallback"]
                        lines.append(f"        fallback: {'false' if value is False else json.dumps(value)}")
        block = "\n".join(lines) + "\n"
        text = re.sub(r"(?m)^agentConfig:\n(?:(?:\s{2}.*\n)*)", block, text)
    for key, value in replacements.items():
        text = re.sub(rf"(?m)^{re.escape(key)}:.*$", lambda m, k=key, v=value: f"{k}: {json.dumps(v)}", text)
    story_range = [item for item in config.get("storyRange", []) if isinstance(item, str)]
    body = {
        "{{epicName}}": str(config.get("epicName", "")),
        "{{epic}}": str(config.get("epic", "")),
        "{{storyRange}}": ", ".join(story_range),
        "{{createdAt}}": now,
        "{{overrides.skipAutomate}}": str(bool(overrides.get("skipAutomate", False))).lower(),
        "{{overrides.maxParallel}}": str(int(overrides.get("maxParallel", 1) or 1)),
        "{{customInstructions}}": str(config.get("customInstructions", "")),
    }
    tea_block = ""
    if policy_selection["workflowTrack"] == "tea":
        tea_block_lines = [
            "**TEA Configuration:**",
            "- Mandatory TEA Core: atdd, test_automate, test_review, trace",
            f"- Optional Automated Steps: {', '.join(policy_selection['selectedOptionalSteps']) or 'none'}",
            f"- Policy Notes: {'; '.join(policy_selection['notes']) or 'none'}",
            "",
        ]
        tea_block = "\n".join(tea_block_lines)
    body["{{teaConfigurationBlock}}"] = tea_block
    for key, value in body.items():
        text = text.replace(key, value)
    text = text.replace("| Story | create-story | dev-story | automate | code-review | git-commit | Status |", progress_header)
    text = text.replace("|-------|--------------|-----------|----------|-------------|------------|--------|", progress_divider)
    text = text.replace("<!-- Progress rows will be appended here -->", progress_rows)
    output_path.write_text(text)
    write_json({"ok": True, "path": str(output_path), "createdAt": now})
    return 0


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _tea_assets_root(project_root: Path, config: dict[str, Any]) -> str:
    configured = str(config.get("teaAssetsRoot") or "").strip()
    if configured:
        return configured.rstrip("/")
    project_assets = project_root / "_bmad" / "tea" / "story-automator"
    if project_assets.is_dir():
        return "_bmad/tea/story-automator"
    wrapper_assets = project_root / "docs" / "plans" / "tea-story-automator" / "assets"
    if wrapper_assets.is_dir():
        return "docs/plans/tea-story-automator/assets"
    return "data/tea-story-automator"


def _tea_assets_base_path(project_root: Path, assets_root: str) -> Path | None:
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
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else None


def _tea_contract_files(project_root: Path, assets_root: str, step: str) -> tuple[str, str]:
    base = _tea_assets_base_path(project_root, assets_root)
    root = assets_root.rstrip("/")
    generic_prompt = f"{root}/prompts/tea_step.md"
    generic_schema = f"{root}/parse/tea_step.json"
    if base is None:
        return generic_prompt, generic_schema
    if (base / "prompts" / f"{step}.md").is_file() and (base / "parse" / f"{step}.json").is_file():
        return f"{root}/prompts/{step}.md", f"{root}/parse/{step}.json"
    return generic_prompt, generic_schema


def _resolve_tea_skill_name(project_root: Path, step: str) -> str:
    candidates = TEA_SKILL_ALIASES.get(step, ())
    for skill_name in candidates:
        try:
            skill_dir = resolve_skill_dir(project_root, skill_name)
        except ValueError:
            continue
        if file_exists(str(skill_dir / "SKILL.md")):
            return skill_name
    return candidates[0] if candidates else ""


def _tea_step_contracts(project_root: Path, assets_root: str, *, include_nfr: bool) -> dict[str, Any]:
    root = assets_root.rstrip("/")
    atdd_prompt, atdd_schema = _tea_contract_files(project_root, assets_root, "atdd")
    automate_prompt, automate_schema = _tea_contract_files(project_root, assets_root, "test_automate")
    review_prompt, review_schema = _tea_contract_files(project_root, assets_root, "test_review")
    trace_prompt, trace_schema = _tea_contract_files(project_root, assets_root, "trace")
    steps: dict[str, Any] = {
        "atdd": {
            "label": "atdd",
            "assets": {
                "skillName": _resolve_tea_skill_name(project_root, "atdd"),
                "workflowCandidates": ["workflow.md", "workflow.yaml"],
                "instructionsCandidates": [],
                "checklistCandidates": ["checklist.md"],
                "templateCandidates": [],
                "required": ["skill"],
            },
            "prompt": {"templateFile": atdd_prompt, "interactionMode": "autonomous"},
            "parse": {"schemaFile": atdd_schema},
            "success": {"verifier": "session_exit"},
        },
        "test_automate": {
            "label": "test-automate",
            "assets": {
                "skillName": _resolve_tea_skill_name(project_root, "test_automate"),
                "workflowCandidates": ["workflow.md", "workflow.yaml"],
                "instructionsCandidates": [],
                "checklistCandidates": ["checklist.md"],
                "templateCandidates": [],
                "required": ["skill"],
            },
            "prompt": {"templateFile": automate_prompt, "interactionMode": "autonomous"},
            "parse": {"schemaFile": automate_schema},
            "success": {"verifier": "session_exit"},
        },
        "test_review": {
            "label": "test-review",
            "assets": {
                "skillName": _resolve_tea_skill_name(project_root, "test_review"),
                "workflowCandidates": ["workflow.md", "workflow.yaml"],
                "instructionsCandidates": [],
                "checklistCandidates": ["checklist.md"],
                "templateCandidates": [],
                "required": ["skill"],
            },
            "prompt": {"templateFile": review_prompt, "interactionMode": "autonomous"},
            "parse": {"schemaFile": review_schema},
            "success": {"verifier": "session_exit"},
        },
        "trace": {
            "label": "trace",
            "assets": {
                "skillName": _resolve_tea_skill_name(project_root, "trace"),
                "workflowCandidates": ["workflow.md", "workflow.yaml"],
                "instructionsCandidates": [],
                "checklistCandidates": ["checklist.md"],
                "templateCandidates": [],
                "required": ["skill"],
            },
            "prompt": {"templateFile": trace_prompt, "interactionMode": "autonomous"},
            "parse": {"schemaFile": trace_schema},
            "success": {"verifier": "session_exit"},
        },
    }
    if include_nfr:
        nfr_prompt, nfr_schema = _tea_contract_files(project_root, assets_root, "nfr")
        steps["nfr"] = {
            "label": "nfr",
            "assets": {
                "skillName": _resolve_tea_skill_name(project_root, "nfr"),
                "workflowCandidates": ["workflow.md", "workflow.yaml"],
                "instructionsCandidates": [],
                "checklistCandidates": ["checklist.md"],
                "templateCandidates": [],
                "required": ["skill"],
            },
            "prompt": {"templateFile": nfr_prompt, "interactionMode": "autonomous"},
            "parse": {"schemaFile": nfr_schema},
            "success": {"verifier": "session_exit"},
        }
    return steps


def _build_run_policy(project_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    explicit_override = config.get("policyOverride")
    if isinstance(explicit_override, dict):
        return {
            "policyOverride": explicit_override,
            "workflowTrack": str(config.get("workflowTrack") or "standard"),
            "selectedOptionalSteps": _normalize_string_list(config.get("selectedOptionalSteps")),
            "manualCheckpoints": _normalize_string_list(config.get("manualCheckpoints")),
            "notes": _normalize_string_list(config.get("policyNotes")),
        }

    has_run_selection = any(
        key in config for key in ("workflowTrack", "selectedOptionalSteps", "manualCheckpoints", "teaAssetsRoot", "includeRetro")
    )
    if not has_run_selection:
        return {
            "policyOverride": {},
            "workflowTrack": "standard",
            "selectedOptionalSteps": [],
            "manualCheckpoints": [],
            "notes": [],
        }

    track = str(config.get("workflowTrack") or "standard").strip().lower()
    if track not in {"standard", "tea"}:
        track = "standard"
    selected = set(_normalize_string_list(config.get("selectedOptionalSteps")))
    manual = set(_normalize_string_list(config.get("manualCheckpoints")))
    notes: list[str] = []
    policy_override: dict[str, Any] = {}

    if track == "tea":
        assets_root = _tea_assets_root(project_root, config)
        include_nfr = "nfr" in selected
        include_retro = "retro" in selected
        if "validate-create-story" in selected:
            notes.append("validate-create-story remains an advisory pre-dev quality check and is not yet automated by story-automator.")
        if "qa-generate-e2e-tests" in selected:
            notes.append("qa-generate-e2e-tests is superseded by TEA test_automate on the TEA track and was ignored.")
        sequence = ["create", "atdd", "dev", "test_automate", "test_review"]
        if include_nfr:
            sequence.append("nfr")
        sequence.extend(["trace", "review"])
        if include_retro:
            sequence.append("retro")
        policy_override = {
            "workflow": {"sequence": sequence},
            "steps": _tea_step_contracts(project_root, assets_root, include_nfr=include_nfr),
        }
        selected = {"nfr" if include_nfr else "", "retro" if include_retro else ""}
        selected.discard("")
    else:
        include_retro = "retro" in selected if "retro" in selected else _as_bool(config.get("includeRetro"), True)
        sequence = ["create", "dev", "auto", "review"]
        if include_retro:
            sequence.append("retro")
            selected.add("retro")
        else:
            selected.discard("retro")
        for unsupported in sorted(selected & {"nfr"}):
            notes.append("nfr is only available on the TEA track and was ignored for the standard workflow.")
            selected.discard(unsupported)
        if "validate-create-story" in selected:
            notes.append("validate-create-story is not yet an automated story-automator step and was recorded as advisory only.")
            selected.discard("validate-create-story")
        if "qa-generate-e2e-tests" in selected:
            notes.append("qa-generate-e2e-tests is already represented by the standard auto step; use skipAutomate to disable it.")
            selected.discard("qa-generate-e2e-tests")
        policy_override = {"workflow": {"sequence": sequence}}

    if manual:
        notes.append("checkpoint-preview is out of scope for story-automator and was ignored.")
    return {
        "policyOverride": policy_override,
        "workflowTrack": track,
        "selectedOptionalSteps": sorted(selected),
        "manualCheckpoints": [],
        "notes": notes,
    }


def cmd_build_run_policy(args: list[str]) -> int:
    config_file = ""
    config_json = ""
    for idx, arg in enumerate(args):
        if arg == "--config-file" and idx + 1 < len(args):
            config_file = args[idx + 1]
        elif arg == "--config-json" and idx + 1 < len(args):
            config_json = args[idx + 1]
    if config_file and file_exists(config_file):
        config_json = read_text(config_file)
    if not config_json.strip():
        write_json({"ok": False, "error": "missing_config"})
        return 1
    try:
        config = json.loads(config_json)
    except json.JSONDecodeError:
        write_json({"ok": False, "error": "missing_config"})
        return 1
    selection = _build_run_policy(Path(get_project_root()), config)
    write_json({"ok": True, **selection})
    return 0


def _has_explicit_tea_policy(project_root: Path) -> bool:
    override_path = project_root / "_bmad" / "bmm" / "story-automator.policy.json"
    if not override_path.is_file():
        return False
    try:
        payload = json.loads(read_text(override_path))
    except (OSError, json.JSONDecodeError):
        return False
    sequence = ((payload.get("workflow") or {}).get("sequence")) or []
    return any(step in {"atdd", "test_automate", "test_review", "trace", "nfr"} for step in sequence if isinstance(step, str))


def _tea_detection_assets_root(project_root: Path) -> str:
    project_assets = project_root / "_bmad" / "tea" / "story-automator"
    if project_assets.is_dir():
        return "_bmad/tea/story-automator"
    wrapper_assets = project_root / "docs" / "plans" / "tea-story-automator" / "assets"
    if wrapper_assets.is_dir():
        return "docs/plans/tea-story-automator/assets"
    return "data/tea-story-automator"


def _tea_assets_complete(project_root: Path, assets_root: str) -> tuple[bool, list[str]]:
    if not assets_root:
        return False, ["missing TEA story-automator assets root"]
    base = _tea_assets_base_path(project_root, assets_root)
    if base is None or not base.exists():
        return False, ["missing TEA story-automator assets root"]
    if (base / "prompts" / "tea_step.md").is_file() and (base / "parse" / "tea_step.json").is_file():
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
    return not missing, missing


def _tea_project_signals(project_root: Path) -> list[str]:
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


def _tea_skill_availability(project_root: Path) -> tuple[list[str], list[str]]:
    available: list[str] = []
    missing: list[str] = []
    for step in ("atdd", "test_automate", "test_review", "trace"):
        skill_name = _resolve_tea_skill_name(project_root, step)
        if not skill_name:
            continue
        try:
            skill_dir = resolve_skill_dir(project_root, skill_name)
        except ValueError:
            missing.append(TEA_SKILL_ALIASES[step][0])
            continue
        if file_exists(str(skill_dir / "SKILL.md")):
            available.append(skill_name)
        else:
            missing.append(TEA_SKILL_ALIASES[step][0])
    return available, missing


def _detect_workflow_track(project_root: Path) -> dict[str, Any]:
    signals = _tea_project_signals(project_root)
    explicit_policy = _has_explicit_tea_policy(project_root)
    assets_root = _tea_detection_assets_root(project_root)
    assets_ok, missing_assets = _tea_assets_complete(project_root, assets_root)
    available_skills, missing_skills = _tea_skill_availability(project_root)
    reasons: list[str] = []
    prompt = ""
    recommended_track = "standard"
    requires_confirmation = False
    tea_capable = bool(signals) and assets_ok and not missing_skills

    if explicit_policy and assets_ok and not missing_skills:
        recommended_track = "tea"
        reasons.append("Project already defines an explicit TEA story-automator policy override.")
    elif explicit_policy:
        reasons.append("Project defines an explicit TEA story-automator policy override, but required TEA skills or assets are missing.")
    elif tea_capable:
        recommended_track = "tea"
        requires_confirmation = True
        reasons.append("Detected TEA module files in the project.")
        reasons.append("Required TEA skills are installed.")
        reasons.append("TEA story-automator assets are available.")
        prompt = "Detected TEA support for this project. Enable TEA automation for this run? [y/N]"
    else:
        if signals:
            reasons.append("Detected TEA-related project files.")
        if missing_skills:
            reasons.append("Required TEA skills are missing, so TEA automation is not currently available.")
        if missing_assets:
            reasons.append("TEA story-automator assets are incomplete or missing.")

    return {
        "ok": True,
        "recommendedTrack": recommended_track,
        "requiresConfirmation": requires_confirmation,
        "prompt": prompt,
        "teaDetected": explicit_policy or bool(signals),
        "teaCapable": (assets_ok and not missing_skills) if explicit_policy else tea_capable,
        "explicitTeaPolicy": explicit_policy,
        "signals": signals,
        "availableSkills": available_skills,
        "missingSkills": missing_skills,
        "assetsRoot": assets_root,
        "missingAssets": missing_assets,
        "reasons": reasons,
    }


def cmd_detect_workflow_track(args: list[str]) -> int:
    project_root = Path(get_project_root())
    for idx, arg in enumerate(args):
        if arg == "--project-root" and idx + 1 < len(args):
            project_root = Path(args[idx + 1]).expanduser().resolve()
    write_json(_detect_workflow_track(project_root))
    return 0


def cmd_sprint_compare(args: list[str]) -> int:
    state = ""
    sprint = ""
    for idx, arg in enumerate(args):
        if arg == "--state" and idx + 1 < len(args):
            state = args[idx + 1]
        elif arg == "--sprint" and idx + 1 < len(args):
            sprint = args[idx + 1]
    if not state or not file_exists(state):
        write_json({"ok": False, "error": "state_not_found"})
        return 1
    if not sprint or not file_exists(sprint):
        write_json({"ok": False, "error": "sprint_not_found"})
        return 1
    fields = parse_simple_frontmatter(read_text(state))
    story_range = fields.get("storyRange", []) if isinstance(fields.get("storyRange"), list) else []
    current_story = fields.get("currentStory")
    before = list(story_range)
    if isinstance(current_story, str) and current_story in story_range:
        before = story_range[: story_range.index(current_story)]
    sprint_text = read_text(sprint)
    incomplete = []
    for story_id in before:
        match = re.search(rf"(?m)^\s*{re.escape(story_id)}:\s*(\S+)", sprint_text)
        if not match or match.group(1) != "done":
            incomplete.append(story_id)
    write_json({"ok": True, "incomplete": incomplete, "checked": before})
    return 0


def cmd_state_metrics(args: list[str]) -> int:
    state = ""
    for idx, arg in enumerate(args):
        if arg == "--state" and idx + 1 < len(args):
            state = args[idx + 1]
    if not state or not file_exists(state):
        write_json({"ok": False, "error": "state_not_found"})
        return 1
    total = 0
    completed = 0
    in_table = False
    for line in read_text(state).splitlines():
        if line.startswith("| Story "):
            in_table = True
            continue
        if in_table and re.match(r"^\|[- ]*\|", line):
            continue
        if in_table and line.startswith("|"):
            parts = [part.strip() for part in line.split("|")]
            values = [part for part in parts[1:-1] if part]
            if len(values) >= 2:
                total += 1
                if any(token in values[-1].lower() for token in ("done", "complete", "completed")):
                    completed += 1
            continue
        if in_table and not line.startswith("|"):
            in_table = False
    print(
        json.dumps(
            {
                "ok": True,
                "storiesCompleted": completed,
                "total": total,
                "reviewCycles": count_matches(read_text(state), r"review cycle|code review cycle"),
                "escalations": count_matches(read_text(state), r"escalation|escalated"),
            },
            separators=(",", ":"),
        )
    )
    return 0


def cmd_validate_state(args: list[str]) -> int:
    if args and args[0] in {"--help", "-h"}:
        print("Usage: validate-state --state PATH")
        return 0
    state = ""
    for idx, arg in enumerate(args):
        if arg == "--state" and idx + 1 < len(args):
            state = args[idx + 1]
    if not state or not file_exists(state):
        write_json({"ok": False, "error": "state_not_found"})
        return 1
    text = read_text(state)
    frontmatter = extract_frontmatter(text)
    fields = parse_simple_frontmatter(text)
    issues: list[str] = []

    def required(key: str, validator: Any = None) -> None:
        value = fields.get(key)
        if value in ("", [], None):
            issues.append(f"Missing or empty {key}")
            return
        if validator and not validator(value):
            issues.append(f"Invalid {key}")

    allowed = {"INITIALIZING", "READY", "IN_PROGRESS", "PAUSED", "EXECUTION_COMPLETE", "COMPLETE", "ABORTED"}
    required("epic")
    required("epicName")
    required("storyRange")
    required("status", lambda value: isinstance(value, str) and value in allowed)
    required("lastUpdated", lambda value: isinstance(value, str) and re.search(r"\d{4}-\d{2}-\d{2}T", value))
    if not _has_runtime_command_config(fields, frontmatter):
        issues.append("Missing or empty aiCommand")
    try:
        load_policy_for_state(state)
    except PolicyError as exc:
        issues.append(str(exc))
    write_json({"ok": True, "structure": "issues" if issues else "ok", "issues": issues})
    return 0


def _has_runtime_command_config(fields: dict[str, Any], frontmatter: str) -> bool:
    ai_command = fields.get("aiCommand")
    if ai_command not in ("", [], None):
        return True
    return _has_agent_config_block(frontmatter)


def _has_agent_config_block(frontmatter: str) -> bool:
    in_agent_config = False
    for raw_line in frontmatter.splitlines():
        stripped = raw_line.strip()
        if not in_agent_config:
            if re.match(r"^agentConfig:\s*(?:#.*)?$", stripped):
                in_agent_config = True
            continue
        if raw_line and not raw_line.startswith(" "):
            break
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, raw = stripped.split(":", 1)
        if key.strip() in {"defaultPrimary", "defaultFallback", "perTask", "complexityOverrides", "retro"}:
            if key.strip() in {"perTask", "complexityOverrides", "retro"} or raw.strip():
                return True
    return False
