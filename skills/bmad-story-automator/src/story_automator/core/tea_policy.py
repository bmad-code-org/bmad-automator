from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .runtime_layout import bundled_story_skill_root, resolve_skill_dir
from .runtime_policy import PolicyError, load_effective_policy
from .utils import file_exists, read_text


STANDARD_SEQUENCE = ["create", "dev", "auto", "review", "retro"]
TEA_SKILL_ALIASES = {
    "atdd": ("bmad-testarch-atdd", "bmad-tea-testarch-atdd"),
    "test_automate": ("bmad-testarch-automate", "bmad-tea-testarch-automate"),
    "test_review": ("bmad-testarch-test-review", "bmad-tea-testarch-test-review"),
    "trace": ("bmad-testarch-trace", "bmad-tea-testarch-trace"),
    "nfr": ("bmad-testarch-nfr", "bmad-tea-testarch-nfr"),
}
TEA_TRACK_DEFINITION = {
    "coreSequence": ["create", "atdd", "dev", "test_automate", "test_review", "trace", "review"],
    "optionalSteps": {"nfr", "retro"},
}


def build_run_policy(project_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    explicit_override = config.get("policyOverride")
    if isinstance(explicit_override, dict):
        resolved = load_effective_policy(str(project_root), inline_override=explicit_override)
        sequence = [step for step in ((resolved.get("workflow") or {}).get("sequence") or []) if isinstance(step, str)]
        track = workflow_track_for_sequence(sequence)
        notes = _normalize_string_list(config.get("policyNotes"))
        if _normalize_option_list(config.get("manualCheckpoints")):
            notes.append("checkpoint-preview is out of scope for story-automator and was ignored.")
        return {
            "policyOverride": explicit_override,
            "workflowTrack": track,
            "selectedOptionalSteps": selected_optional_steps_from_sequence(sequence),
            "manualCheckpoints": [],
            "notes": notes,
        }

    explicit_override_payload, explicit_override_error = explicit_policy_payload(project_root)
    explicit_override_sequence = [
        step for step in (((explicit_override_payload.get("workflow") or {}).get("sequence")) or []) if isinstance(step, str)
    ]
    explicit_override_track = workflow_track_for_sequence(explicit_override_sequence) if explicit_override_payload else "standard"
    explicit_override_resolved, explicit_override_validation_error = explicit_project_policy_details(
        project_root, explicit_override_payload
    )

    has_run_selection = any(
        key in config for key in ("workflowTrack", "selectedOptionalSteps", "manualCheckpoints", "teaAssetsRoot", "includeRetro")
    )
    if not has_run_selection:
        if explicit_override_error:
            raise PolicyError(explicit_override_error)
        if explicit_override_payload and explicit_override_resolved is None:
            raise PolicyError(explicit_override_validation_error or "explicit story-automator policy is invalid")
        sequence = [
            step
            for step in (((explicit_override_resolved or {}).get("workflow") or {}).get("sequence") or [])
            if isinstance(step, str)
        ]
        return {
            "policyOverride": {},
            "workflowTrack": workflow_track_for_sequence(sequence) if sequence else "standard",
            "selectedOptionalSteps": selected_optional_steps_from_sequence(sequence),
            "manualCheckpoints": [],
            "notes": [],
        }

    track = str(config.get("workflowTrack") or "standard").strip().lower()
    if track not in {"standard", "tea"}:
        track = "standard"
    selected = set(_normalize_option_list(config.get("selectedOptionalSteps")))
    manual = set(_normalize_option_list(config.get("manualCheckpoints")))
    notes: list[str] = []
    policy_override: dict[str, Any] = {}

    if track == "tea":
        if explicit_override_payload and explicit_override_track == "tea":
            if explicit_override_resolved is None:
                raise PolicyError(explicit_override_validation_error or "explicit TEA story-automator policy is invalid")
            explicit_sequence = ((explicit_override_resolved.get("workflow") or {}).get("sequence")) or []
            selected = set(selected_optional_steps_from_sequence([step for step in explicit_sequence if isinstance(step, str)]))
            if _normalize_option_list(config.get("selectedOptionalSteps")):
                notes.append("Per-run TEA optional-step selection was ignored because the project defines an explicit TEA story-automator policy.")
            if _normalize_option_list(config.get("manualCheckpoints")):
                notes.append("checkpoint-preview is out of scope for story-automator and was ignored.")
            return {
                "policyOverride": {},
                "workflowTrack": track,
                "selectedOptionalSteps": sorted(selected),
                "manualCheckpoints": [],
                "notes": notes,
            }

        assets_root = tea_assets_root(project_root, config)
        include_nfr = "nfr" in selected
        if include_nfr and not tea_skill_installed(project_root, "nfr"):
            notes.append("nfr was requested on the TEA track, but the TEA NFR skill is not installed, so it was ignored.")
            include_nfr = False
            selected.discard("nfr")
        include_retro = "retro" in selected
        if "validate-create-story" in selected:
            notes.append("validate-create-story remains an advisory pre-dev quality check and is not yet automated by story-automator.")
        if "qa-generate-e2e-tests" in selected:
            notes.append("qa-generate-e2e-tests is superseded by TEA test_automate on the TEA track and was ignored.")

        sequence = list(TEA_TRACK_DEFINITION["coreSequence"][:-2])
        if include_nfr:
            sequence.append("nfr")
        sequence.extend(TEA_TRACK_DEFINITION["coreSequence"][-2:])
        if include_retro:
            sequence.append("retro")
        policy_override = {
            "workflow": {"sequence": sequence},
            "steps": tea_step_contracts(project_root, assets_root, include_nfr=include_nfr),
        }
        selected = {"nfr" if include_nfr else "", "retro" if include_retro else ""}
        selected.discard("")
    else:
        if explicit_override_payload and explicit_override_track == "standard":
            if explicit_override_resolved is None:
                raise PolicyError(explicit_override_validation_error or "explicit standard story-automator policy is invalid")
            explicit_sequence = ((explicit_override_resolved.get("workflow") or {}).get("sequence")) or []
            selected = set(selected_optional_steps_from_sequence([step for step in explicit_sequence if isinstance(step, str)]))
            if _normalize_option_list(config.get("selectedOptionalSteps")) or "includeRetro" in config:
                notes.append("Per-run standard optional-step selection was ignored because the project defines an explicit standard story-automator policy.")
            if _normalize_option_list(config.get("manualCheckpoints")):
                notes.append("checkpoint-preview is out of scope for story-automator and was ignored.")
            return {
                "policyOverride": {},
                "workflowTrack": track,
                "selectedOptionalSteps": sorted(selected),
                "manualCheckpoints": [],
                "notes": notes,
            }
        include_retro = "retro" in selected if "retro" in selected else _as_bool(config.get("includeRetro"), True)
        sequence = list(STANDARD_SEQUENCE[:-1])
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
    selection = {
        "policyOverride": policy_override,
        "workflowTrack": track,
        "selectedOptionalSteps": sorted(selected),
        "manualCheckpoints": [],
        "notes": notes,
    }
    load_effective_policy(str(project_root), inline_override=selection["policyOverride"])
    return selection


def detect_workflow_track(project_root: Path) -> dict[str, Any]:
    signals = tea_project_signals(project_root)
    explicit_override_present, explicit_override_stat_error = path_is_file(explicit_policy_path(project_root))
    explicit_override_payload, explicit_override_error = explicit_policy_payload(project_root)
    explicit_override_sequence = [
        step for step in (((explicit_override_payload.get("workflow") or {}).get("sequence")) or []) if isinstance(step, str)
    ]
    explicit_override_track = workflow_track_for_sequence(explicit_override_sequence) if explicit_override_payload else "standard"
    explicit_override_resolved, explicit_override_validation_error = explicit_project_policy_details(
        project_root, explicit_override_payload
    )
    explicit_steps = explicit_tea_steps(project_root)
    explicit_policy = bool(explicit_steps)
    explicit_policy_valid = explicit_policy and explicit_override_resolved is not None
    if explicit_policy and explicit_policy_valid:
        available_skills, assets_root = resolved_explicit_tea_status(explicit_override_resolved, explicit_steps)
        missing_skills = []
        missing_assets = []
        assets_ok = True
    elif explicit_policy:
        available_skills, missing_skills = tea_skill_availability(project_root, explicit_steps or None)
        assets_root, missing_assets = explicit_tea_assets_status(project_root, explicit_override_payload, explicit_steps)
        assets_ok = not missing_assets
    else:
        assets_root = tea_detected_assets_root(project_root)
        assets_ok, missing_assets = tea_assets_complete(project_root, assets_root)
        available_skills, missing_skills = tea_skill_availability(project_root, explicit_steps or None)
    reasons: list[str] = []
    prompt = ""
    recommended_track = "standard"
    requires_confirmation = False
    tea_capable = bool(signals) and assets_ok and not missing_skills

    if explicit_policy and explicit_policy_valid:
        recommended_track = "tea"
        reasons.append("Project already defines an explicit TEA story-automator policy override.")
    elif explicit_policy:
        reasons.append("Project defines an explicit TEA story-automator policy override, but required TEA skills or assets are missing.")
        if explicit_override_validation_error:
            reasons.append(explicit_override_validation_error)
    elif explicit_override_payload and explicit_override_track == "standard" and explicit_override_resolved is not None:
        reasons.append("Project already defines an explicit standard story-automator policy override.")
    elif explicit_override_payload and explicit_override_track == "standard":
        reasons.append("Project defines an explicit standard story-automator policy override, but it is invalid.")
        if explicit_override_validation_error:
            reasons.append(explicit_override_validation_error)
    elif explicit_override_stat_error:
        reasons.append("Project defines a story-automator policy override, but it is unreadable.")
        reasons.append(explicit_override_stat_error)
    elif explicit_override_present and explicit_override_error:
        reasons.append("Project defines a story-automator policy override, but it is invalid.")
        reasons.append(explicit_override_error)
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
        "teaCapable": explicit_policy_valid if explicit_policy else tea_capable,
        "explicitTeaPolicy": explicit_policy,
        "signals": signals,
        "availableSkills": available_skills,
        "missingSkills": missing_skills,
        "assetsRoot": assets_root,
        "missingAssets": missing_assets,
        "reasons": reasons,
    }


def selected_optional_steps_from_sequence(sequence: list[str]) -> list[str]:
    selected: list[str] = []
    if "nfr" in sequence:
        selected.append("nfr")
    if "retro" in sequence:
        selected.append("retro")
    return selected


def workflow_track_for_sequence(sequence: list[str]) -> str:
    unique_tea_steps = {"atdd", "test_automate", "test_review", "trace", "nfr"}
    return "tea" if any(step in unique_tea_steps for step in sequence) else "standard"


def explicit_policy_path(project_root: Path) -> Path:
    return project_root / "_bmad" / "bmm" / "story-automator.policy.json"


def path_is_file(path: Path) -> tuple[bool, str]:
    try:
        return path.is_file(), ""
    except OSError as exc:
        return False, str(exc)


def explicit_policy_payload(project_root: Path) -> tuple[dict[str, Any], str]:
    override_path = explicit_policy_path(project_root)
    override_exists, override_error = path_is_file(override_path)
    if override_error:
        return {}, f"explicit story-automator policy unreadable: {override_error}"
    if not override_exists:
        return {}, ""
    try:
        payload = json.loads(read_text(override_path))
    except OSError as exc:
        return {}, f"explicit story-automator policy unreadable: {exc}"
    except json.JSONDecodeError as exc:
        return {}, f"explicit story-automator policy invalid JSON: {exc}"
    if not isinstance(payload, dict):
        return {}, "explicit story-automator policy must be a JSON object"
    return payload, ""


def explicit_tea_steps(project_root: Path) -> list[str]:
    payload, _ = explicit_policy_payload(project_root)
    sequence = ((payload.get("workflow") or {}).get("sequence")) or []
    tea_steps = {"atdd", "test_automate", "test_review", "trace", "nfr"}
    return [step for step in sequence if isinstance(step, str) and step in tea_steps]


def has_explicit_tea_policy(project_root: Path) -> bool:
    return bool(explicit_tea_steps(project_root))


def explicit_tea_policy_details(project_root: Path) -> tuple[dict[str, Any] | None, str]:
    if not has_explicit_tea_policy(project_root):
        return None, ""
    try:
        return load_effective_policy(str(project_root), resolve_assets=True), ""
    except (FileNotFoundError, PolicyError, ValueError) as exc:
        return None, str(exc)


def explicit_project_policy_details(project_root: Path, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    if not payload:
        return None, ""
    try:
        return load_effective_policy(str(project_root), resolve_assets=True), ""
    except (FileNotFoundError, PolicyError, ValueError) as exc:
        return None, str(exc)


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
    for candidate in candidates:
        if candidate.exists():
            return candidate
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
    candidates = TEA_SKILL_ALIASES.get(step, ())
    for skill_name in candidates:
        try:
            skill_dir = resolve_skill_dir(project_root, skill_name)
        except ValueError:
            continue
        if file_exists(str(skill_dir / "SKILL.md")):
            return skill_name
    return candidates[0] if candidates else ""


def tea_skill_installed(project_root: Path, step: str) -> bool:
    candidates = TEA_SKILL_ALIASES.get(step, ())
    for skill_name in candidates:
        try:
            skill_dir = resolve_skill_dir(project_root, skill_name)
        except ValueError:
            continue
        if file_exists(str(skill_dir / "SKILL.md")):
            return True
    return False


def tea_step_contracts(project_root: Path, assets_root: str, *, include_nfr: bool) -> dict[str, Any]:
    steps: dict[str, Any] = {}
    for step, label in (
        ("atdd", "atdd"),
        ("test_automate", "test-automate"),
        ("test_review", "test-review"),
        ("trace", "trace"),
    ):
        prompt, schema = tea_contract_files(project_root, assets_root, step)
        steps[step] = {
            "label": label,
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
    if include_nfr:
        prompt, schema = tea_contract_files(project_root, assets_root, "nfr")
        steps["nfr"] = {
            "label": "nfr",
            "assets": {
                "skillName": resolve_tea_skill_name(project_root, "nfr"),
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
    for step in (required_steps or ["atdd", "test_automate", "test_review", "trace"]):
        skill_name = resolve_tea_skill_name(project_root, step)
        if not skill_name:
            missing.append(TEA_SKILL_ALIASES[step][0])
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
    steps = payload.get("steps") or {}
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


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if item is not None and str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _normalize_option_list(value: Any) -> list[str]:
    return [item.lower() for item in _normalize_string_list(value)]


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
