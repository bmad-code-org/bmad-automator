from __future__ import annotations

from pathlib import Path
from typing import Any

from .runtime_policy import PolicyError, load_effective_policy
from .tea_policy_assets import (
    explicit_tea_assets_status,
    resolved_explicit_tea_status,
    tea_assets_complete,
    tea_assets_root,
    tea_detected_assets_root,
    tea_project_signals,
    tea_skill_availability,
    tea_skill_installed,
    tea_step_contracts,
)
from .tea_policy_config import (
    as_bool,
    explicit_policy_path,
    explicit_policy_payload,
    explicit_policy_sequence,
    normalize_option_list,
    normalize_string_list,
    path_is_file,
    policy_copy,
)
from .workflow_steps import (
    STANDARD_SEQUENCE,
    selected_optional_steps_from_sequence,
    tea_sequence,
    tea_steps_from_sequence,
    workflow_track_for_sequence,
)


def build_run_policy(project_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    explicit_override = config.get("policyOverride")
    if isinstance(explicit_override, dict):
        resolved = load_effective_policy(str(project_root), inline_override=policy_copy(explicit_override))
        sequence = [step for step in ((resolved.get("workflow") or {}).get("sequence") or []) if isinstance(step, str)]
        track = workflow_track_for_sequence(sequence)
        notes = normalize_string_list(config.get("policyNotes"))
        if normalize_option_list(config.get("manualCheckpoints")):
            notes.append("checkpoint-preview is out of scope for story-automator and was ignored.")
        return {
            "policyOverride": explicit_override,
            "workflowTrack": track,
            "selectedOptionalSteps": selected_optional_steps_from_sequence(sequence),
            "manualCheckpoints": [],
            "notes": notes,
        }

    explicit_override_payload, explicit_override_error = explicit_policy_payload(project_root)
    explicit_override_sequence, explicit_override_shape_error = explicit_policy_sequence(explicit_override_payload)
    explicit_override_error = explicit_override_error or explicit_override_shape_error
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
        raise PolicyError(f"unknown workflowTrack: {track}")
    selected = set(normalize_option_list(config.get("selectedOptionalSteps")))
    manual = set(normalize_option_list(config.get("manualCheckpoints")))
    notes: list[str] = []
    policy_override: dict[str, Any] = {}

    if track == "tea":
        if explicit_override_payload and explicit_override_track == "tea":
            if explicit_override_resolved is None:
                raise PolicyError(explicit_override_validation_error or "explicit TEA story-automator policy is invalid")
            explicit_sequence = ((explicit_override_resolved.get("workflow") or {}).get("sequence")) or []
            selected = set(selected_optional_steps_from_sequence([step for step in explicit_sequence if isinstance(step, str)]))
            if normalize_option_list(config.get("selectedOptionalSteps")) or "includeRetro" in config:
                notes.append("Per-run TEA optional-step selection was ignored because the project defines an explicit TEA story-automator policy.")
            if normalize_option_list(config.get("manualCheckpoints")):
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
        include_retro = "retro" in selected if "retro" in selected else as_bool(config.get("includeRetro"), False)
        if "validate-create-story" in selected:
            notes.append("validate-create-story remains an advisory pre-dev quality check and is not yet automated by story-automator.")
        if "qa-generate-e2e-tests" in selected:
            notes.append("qa-generate-e2e-tests is superseded by TEA test_automate on the TEA track and was ignored.")

        sequence = tea_sequence(include_nfr=include_nfr, include_retro=include_retro)
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
            if normalize_option_list(config.get("selectedOptionalSteps")) or "includeRetro" in config:
                notes.append("Per-run standard optional-step selection was ignored because the project defines an explicit standard story-automator policy.")
            if normalize_option_list(config.get("manualCheckpoints")):
                notes.append("checkpoint-preview is out of scope for story-automator and was ignored.")
            return {
                "policyOverride": {},
                "workflowTrack": track,
                "selectedOptionalSteps": sorted(selected),
                "manualCheckpoints": [],
                "notes": notes,
            }
        include_retro = "retro" in selected if "retro" in selected else as_bool(config.get("includeRetro"), True)
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
    load_effective_policy(str(project_root), inline_override=policy_copy(selection["policyOverride"]))
    return selection


def detect_workflow_track(project_root: Path) -> dict[str, Any]:
    signals = tea_project_signals(project_root)
    explicit_override_present, explicit_override_stat_error = path_is_file(explicit_policy_path(project_root))
    explicit_override_payload, explicit_override_error = explicit_policy_payload(project_root)
    explicit_override_sequence, explicit_override_shape_error = explicit_policy_sequence(explicit_override_payload)
    explicit_override_error = explicit_override_error or explicit_override_shape_error
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


def explicit_tea_steps(project_root: Path) -> list[str]:
    payload, _ = explicit_policy_payload(project_root)
    sequence, _ = explicit_policy_sequence(payload)
    return tea_steps_from_sequence(sequence)


def explicit_project_policy_details(project_root: Path, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    if not payload:
        return None, ""
    try:
        return load_effective_policy(str(project_root), resolve_assets=True), ""
    except (FileNotFoundError, PolicyError, ValueError) as exc:
        return None, str(exc)
