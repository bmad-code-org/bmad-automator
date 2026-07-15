from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .utils import read_text


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


def explicit_policy_sequence(payload: dict[str, Any]) -> tuple[list[str], str]:
    if not payload:
        return [], ""
    workflow = payload.get("workflow")
    if workflow is None:
        return [], ""
    if not isinstance(workflow, dict):
        return [], "explicit story-automator policy workflow must be an object"
    sequence = workflow.get("sequence") or []
    if not isinstance(sequence, list) or any(not isinstance(item, str) for item in sequence):
        return [], "explicit story-automator policy workflow.sequence must be a string array"
    return list(sequence), ""


def normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if item is not None and str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def normalize_option_list(value: Any) -> list[str]:
    return [item.lower() for item in normalize_string_list(value)]


def as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return default


def policy_copy(payload: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(payload)
