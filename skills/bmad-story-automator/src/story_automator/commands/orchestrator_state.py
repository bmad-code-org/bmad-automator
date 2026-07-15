from __future__ import annotations

import re
from pathlib import Path

from story_automator.core.frontmatter import extract_last_action, find_frontmatter_value, parse_simple_frontmatter
from story_automator.core.runtime_policy import PolicyError, load_runtime_policy, summarize_state_policy_fields, workflow_sequence
from story_automator.core.state_document import update_story_progress
from story_automator.core.workflow_steps import TEA_QUALITY_STEPS
from story_automator.core.utils import file_exists, get_project_root, print_json, read_text


def state_list_action(args: list[str]) -> int:
    if not args or not Path(args[0]).is_dir():
        print_json({"ok": False, "error": "folder_not_found", "files": []})
        return 1
    files = []
    for path in sorted(Path(args[0]).glob("orchestration-*.md")):
        files.append({"path": str(path), "status": find_frontmatter_value(path, "status") or "unknown", "lastUpdated": find_frontmatter_value(path, "lastUpdated") or "unknown"})
    print_json({"ok": True, "files": files})
    return 0


def state_latest_action(args: list[str]) -> int:
    if not args or not Path(args[0]).is_dir():
        print_json({"ok": False, "error": "folder_not_found"})
        return 1
    status_filter = args[1] if len(args) > 1 else ""
    matches = []
    for path in Path(args[0]).glob("orchestration-*.md"):
        status = find_frontmatter_value(path, "status")
        if status_filter and status != status_filter:
            continue
        matches.append((find_frontmatter_value(path, "lastUpdated"), str(path)))
    if not matches:
        print_json({"ok": False, "error": "no_match"})
        return 0
    updated, path = max(matches)
    print_json({"ok": True, "path": path, "lastUpdated": updated})
    return 0


def state_latest_incomplete_action(args: list[str]) -> int:
    if not args or not Path(args[0]).is_dir():
        print_json({"ok": False, "error": "folder_not_found"})
        return 1
    matches = []
    for path in Path(args[0]).glob("orchestration-*.md"):
        status = find_frontmatter_value(path, "status")
        if status == "COMPLETE":
            continue
        matches.append((find_frontmatter_value(path, "lastUpdated"), status, str(path)))
    if not matches:
        print_json({"ok": False, "error": "no_incomplete_state"})
        return 0
    updated, status, path = max(matches)
    print_json({"ok": True, "path": path, "lastUpdated": updated, "status": status})
    return 0


def state_summary_action(args: list[str]) -> int:
    if not args or not file_exists(args[0]):
        print_json({"ok": False, "error": "file_not_found"})
        return 1
    fields = parse_simple_frontmatter(read_text(args[0]))
    snapshot_file, snapshot_hash, policy_version, legacy_policy, policy_error = summarize_state_policy_fields(
        fields,
        project_root=get_project_root(),
    )
    payload = {
        "ok": True,
        "epic": str(fields.get("epic") or ""),
        "epicName": str(fields.get("epicName") or ""),
        "currentStory": str(fields.get("currentStory") or ""),
        "currentStep": str(fields.get("currentStep") or ""),
        "status": str(fields.get("status") or ""),
        "lastUpdated": str(fields.get("lastUpdated") or ""),
        "policyVersion": policy_version,
        "policySnapshotFile": snapshot_file,
        "policySnapshotHash": snapshot_hash,
        "legacyPolicy": legacy_policy,
        "lastAction": extract_last_action(args[0]),
    }
    if policy_error:
        payload["policyError"] = policy_error
    print_json(payload)
    return 0


def state_update_action(args: list[str]) -> int:
    if not args or not file_exists(args[0]):
        print_json({"ok": False, "error": "file_not_found"})
        return 1
    text = read_text(args[0])
    updated: list[str] = []
    idx = 1
    while idx < len(args):
        if args[idx] == "--set" and idx + 1 < len(args):
            key, value = args[idx + 1].split("=", 1)
            replaced, count = re.subn(rf"(?m)^{re.escape(key)}:.*$", lambda m, k=key, v=value: f"{k}: {v}", text)
            if count:
                text = replaced
                updated.append(key)
            idx += 2
            continue
        idx += 1
    if not updated:
        print_json({"ok": False, "error": "keys_not_found", "updated": []})
        return 1
    Path(args[0]).write_text(text, encoding="utf-8")
    print_json({"ok": True, "updated": updated})
    return 0



def policy_sequence_action(args: list[str]) -> int:
    state_file = ""
    idx = 0
    try:
        while idx < len(args):
            if args[idx] == "--state-file":
                state_file = _flag_value(args, idx, "--state-file")
                idx += 2
                continue
            idx += 1
    except PolicyError as exc:
        print_json({"ok": False, "error": "policy_invalid", "reason": str(exc)})
        return 1
    try:
        policy = load_runtime_policy(get_project_root(), state_file=state_file, resolve_assets=False)
    except (FileNotFoundError, PolicyError) as exc:
        print_json({"ok": False, "error": "policy_invalid", "reason": str(exc)})
        return 1
    print_json({"ok": True, "sequence": workflow_sequence(policy)})
    return 0


def policy_steps_action(args: list[str]) -> int:
    state_file = ""
    group = ""
    idx = 0
    try:
        while idx < len(args):
            if args[idx] == "--state-file":
                state_file = _flag_value(args, idx, "--state-file")
                idx += 2
                continue
            if args[idx] == "--group":
                group = _flag_value(args, idx, "--group")
                idx += 2
                continue
            idx += 1
    except PolicyError as exc:
        print_json({"ok": False, "error": "policy_invalid", "reason": str(exc)})
        return 1
    if group != "tea-quality":
        print_json({"ok": False, "error": "unknown_step_group", "group": group})
        return 1
    try:
        policy = load_runtime_policy(get_project_root(), state_file=state_file, resolve_assets=False)
    except (FileNotFoundError, PolicyError) as exc:
        print_json({"ok": False, "error": "policy_invalid", "reason": str(exc)})
        return 1
    sequence = workflow_sequence(policy)
    steps = [step for step in sequence if step in TEA_QUALITY_STEPS]
    print_json({"ok": True, "group": group, "steps": steps})
    return 0



def state_progress_action(args: list[str], *, exists_fn=None) -> int:
    if not args:
        print_json({"ok": False, "error": "file_not_found"})
        return 1
    state_file = args[0]
    exists = exists_fn or file_exists
    try:
        if not exists(state_file):
            print_json({"ok": False, "error": "file_not_found"})
            return 1
    except OSError:
        print_json({"ok": False, "error": "state_file_unreadable"})
        return 1
    story_id = ""
    updates: dict[str, str] = {}
    idx = 1
    while idx < len(args):
        if args[idx] == "--story" and idx + 1 < len(args):
            story_id = args[idx + 1]
            idx += 2
            continue
        if args[idx] == "--set" and idx + 1 < len(args):
            raw_update = args[idx + 1]
            if "=" not in raw_update:
                print_json({"ok": False, "error": "invalid_set_argument", "argument": raw_update})
                return 1
            key, value = raw_update.split("=", 1)
            updates[key] = value
            idx += 2
            continue
        idx += 1
    if not story_id or not updates:
        print_json({"ok": False, "error": "missing_story_or_updates"})
        return 1

    try:
        policy = load_runtime_policy(get_project_root(), state_file=state_file, resolve_assets=False)
    except (FileNotFoundError, PolicyError) as exc:
        print_json({"ok": False, "error": "policy_invalid", "reason": str(exc)})
        return 1
    ok, payload = update_story_progress(state_file, story_id, updates, policy=policy)
    if not ok:
        print_json(payload)
        return 1
    print_json(payload)
    return 0



def _flag_value(args: list[str], idx: int, flag: str) -> str:
    if idx + 1 >= len(args) or not args[idx + 1].strip() or args[idx + 1].startswith("--"):
        raise PolicyError(f"{flag} requires a value")
    return args[idx + 1]
