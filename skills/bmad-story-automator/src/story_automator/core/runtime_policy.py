from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .frontmatter import parse_simple_frontmatter
from .runtime_layout import active_marker_path, resolve_portable_path
from .utils import ensure_dir, get_project_root, iso_now, md5_hex8, read_text, write_atomic
from .runtime_policy_support import (
    PolicyError,
    _apply_legacy_env,
    _clear_resolved_fields,
    _deep_merge,
    _display_path,
    _ensure_within,
    _load_bundled_policy_shape,
    _load_policy_snapshot_shape,
    _path_is_file,
    _prune_unreferenced_steps,
    _read_json,
    _resolve_policy_paths,
    _resolve_snapshot_dir,
    _resolve_state_path,
    _resolve_success_paths,
    _stable_policy_json,
    _state_policy_mode,
    _validate_policy_shape,
    bundled_skill_root,
    parser_runtime_config,
)

def load_bundled_policy(project_root: str | None = None, *, resolve_assets: bool = True) -> dict[str, Any]:
    root = Path(project_root or get_project_root()).resolve()
    bundle_root = bundled_skill_root(root)
    policy = _load_bundled_policy_shape(root, bundle_root=bundle_root)
    if resolve_assets:
        _resolve_policy_paths(policy, project_root=root, bundle_root=bundle_root)
    else:
        _resolve_success_paths(policy, project_root=root, bundle_root=bundle_root)
    return policy



def load_effective_policy(
    project_root: str | None = None,
    *,
    resolve_assets: bool = True,
    inline_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(project_root or get_project_root()).resolve()
    bundled = load_bundled_policy(str(root), resolve_assets=False)
    override_path = root / "_bmad" / "bmm" / "story-automator.policy.json"
    try:
        override = _read_json(override_path) if _path_is_file(override_path) else {}
    except PolicyError as exc:
        if str(exc).startswith("path unreadable:"):
            raise PolicyError(f"project override unreadable: {override_path}") from exc
        raise
    except OSError as exc:
        raise PolicyError(f"project override unreadable: {override_path}") from exc
    policy = _deep_merge(_deep_merge(bundled, override), inline_override or {})
    _apply_legacy_env(policy)
    _validate_policy_shape(policy)
    _prune_unreferenced_steps(policy)
    _validate_policy_shape(policy)
    _clear_resolved_fields(policy)
    if resolve_assets:
        _resolve_policy_paths(policy, project_root=root, bundle_root=bundled_skill_root(root))
    else:
        _resolve_success_paths(policy, project_root=root, bundle_root=bundled_skill_root(root))
    return policy


def load_runtime_policy(
    project_root: str | None = None,
    state_file: str | Path | None = None,
    *,
    resolve_assets: bool = True,
) -> dict[str, Any]:
    root = Path(project_root or get_project_root()).resolve()
    resolved_state, source = resolve_policy_state_file(root, state_file)
    if resolved_state:
        state_path = Path(resolved_state)
        if source in {"env", "marker"} and not state_path.is_file():
            raise PolicyError(f"{source} state file missing: {state_path}")
        if source != "explicit" and not state_path.is_file():
            return load_effective_policy(str(root), resolve_assets=resolve_assets)
        return load_policy_for_state(str(state_path), project_root=str(root), resolve_assets=resolve_assets)
    return load_effective_policy(str(root), resolve_assets=resolve_assets)


def snapshot_effective_policy(project_root: str | None = None, *, inline_override: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(project_root or get_project_root()).resolve()
    policy = load_effective_policy(str(root), inline_override=inline_override)
    snapshot_dir = _resolve_snapshot_dir(policy, root)
    ensure_dir(snapshot_dir)
    stable_json = _stable_policy_json(policy)
    snapshot_hash = md5_hex8(stable_json)
    stamp = iso_now().replace("-", "").replace(":", "").replace("T", "-").replace("Z", "")
    snapshot_path = snapshot_dir / f"{stamp}-{snapshot_hash}.json"
    write_atomic(snapshot_path, stable_json)
    return {
        "policy": policy,
        "policyVersion": policy.get("version", 1),
        "policySnapshotHash": snapshot_hash,
        "policySnapshotFile": _display_path(snapshot_path, root),
    }


def load_policy_snapshot(
    snapshot_file: str,
    *,
    project_root: str | None = None,
    expected_hash: str = "",
    resolve_assets: bool = True,
) -> dict[str, Any]:
    root = Path(project_root or get_project_root()).resolve()
    path = Path(snapshot_file)
    if not path.is_absolute():
        path = root / path
    path = _ensure_within(path, root, "policy snapshot")
    try:
        snapshot_exists = path.is_file()
    except OSError as exc:
        raise PolicyError(f"policy snapshot unreadable: {path}") from exc
    if not snapshot_exists:
        raise PolicyError(f"policy snapshot missing: {path}")
    policy = _load_policy_snapshot_shape(path, expected_hash=expected_hash)
    if resolve_assets:
        _resolve_policy_paths(policy, project_root=root, bundle_root=bundled_skill_root(root))
    else:
        _resolve_success_paths(policy, project_root=root, bundle_root=bundled_skill_root(root))
    return policy


def load_policy_for_state(
    state_file: str | Path,
    project_root: str | None = None,
    *,
    resolve_assets: bool = True,
) -> dict[str, Any]:
    root = Path(project_root or get_project_root()).resolve()
    try:
        fields = parse_simple_frontmatter(read_text(state_file))
    except OSError as exc:
        raise PolicyError(f"state file unreadable: {state_file}") from exc
    snapshot_file, snapshot_hash, legacy_mode = _state_policy_mode(fields)
    if not legacy_mode:
        return load_policy_snapshot(
            snapshot_file,
            project_root=str(root),
            expected_hash=snapshot_hash,
            resolve_assets=resolve_assets,
        )
    return load_bundled_policy(str(root), resolve_assets=resolve_assets)


def load_policy_shape_for_state(state_file: str | Path, project_root: str | None = None) -> dict[str, Any]:
    root = Path(project_root or get_project_root()).resolve()
    try:
        fields = parse_simple_frontmatter(read_text(state_file))
    except OSError as exc:
        raise PolicyError(f"state file unreadable: {state_file}") from exc
    snapshot_file, snapshot_hash, legacy_mode = _state_policy_mode(fields)
    if not legacy_mode:
        path = Path(snapshot_file)
        if not path.is_absolute():
            path = root / path
        path = _ensure_within(path, root, "policy snapshot")
        try:
            snapshot_exists = path.is_file()
        except OSError as exc:
            raise PolicyError(f"policy snapshot unreadable: {path}") from exc
        if not snapshot_exists:
            raise PolicyError(f"policy snapshot missing: {path}")
        return _load_policy_snapshot_shape(path, expected_hash=snapshot_hash)
    return _load_bundled_policy_shape(root)


def summarize_state_policy_fields(fields: dict[str, Any], *, project_root: str | Path | None = None) -> tuple[str, str, str, str, str]:
    policy_version = str(fields.get("policyVersion") or "").strip()
    try:
        snapshot_file, snapshot_hash, legacy_mode = _state_policy_mode(fields)
        if snapshot_file and snapshot_hash:
            load_policy_snapshot(
                snapshot_file,
                project_root=str(Path(project_root or get_project_root()).resolve()),
                expected_hash=snapshot_hash,
                resolve_assets=False,
            )
    except PolicyError as exc:
        return "", "", policy_version, "false", str(exc)
    return snapshot_file, snapshot_hash, policy_version, "true" if legacy_mode else "false", ""


def resolve_policy_state_file(project_root: str | Path | None = None, state_file: str | Path | None = None) -> tuple[str, str]:
    root = Path(project_root or get_project_root()).resolve()
    explicit = Path(state_file).expanduser() if state_file else None
    if explicit:
        return str(_resolve_state_path(root, explicit)), "explicit"
    env_state = os.environ.get("STORY_AUTOMATOR_STATE_FILE", "").strip()
    if env_state:
        return str(_resolve_state_path(root, Path(env_state).expanduser(), allow_outside=False, label="env state file")), "env"
    marker = active_marker_path(root)
    if marker.is_file():
        try:
            payload = _read_json(marker)
        except PolicyError as exc:
            raise PolicyError(f"active-run marker invalid: {exc}") from exc
        marker_state = str(payload.get("stateFile") or "").strip()
        if not marker_state:
            raise PolicyError("active-run marker missing stateFile")
        return str(_resolve_state_path(root, Path(marker_state).expanduser(), allow_outside=False, label="marker state file")), "marker"
    return "", ""


def step_contract(policy: dict[str, Any], step: str) -> dict[str, Any]:
    contract = (policy.get("steps") or {}).get(step)
    if not isinstance(contract, dict):
        raise PolicyError(f"unknown step: {step}")
    return contract


def review_max_cycles(policy: dict[str, Any]) -> int:
    repeat = ((policy.get("workflow") or {}).get("repeat") or {}).get("review") or {}
    return int(repeat.get("maxCycles", 5))


def workflow_sequence(policy: dict[str, Any]) -> list[str]:
    sequence = ((policy.get("workflow") or {}).get("sequence")) or []
    return [str(step) for step in sequence if isinstance(step, str) and step]


def story_task_sequence(policy: dict[str, Any]) -> list[str]:
    return [step for step in workflow_sequence(policy) if step != "retro"]


def crash_max_retries(policy: dict[str, Any]) -> int:
    crash = ((policy.get("workflow") or {}).get("crash")) or {}
    return int(crash.get("maxRetries", 2))
