from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..core.frontmatter import extract_frontmatter, parse_simple_frontmatter
from ..core.runtime_policy import PolicyError, load_policy_for_state, snapshot_effective_policy
from ..core.agent_config import normalize_model as _model_or_none
from ..core.state_document import progress_metrics, progress_table_lines
from ..core.tea_policy import build_run_policy, detect_workflow_track, selected_optional_steps_from_sequence, workflow_track_for_sequence
from ..core.utils import count_matches, ensure_dir, file_exists, get_project_root, now_utc, now_utc_z, read_text, write_json


def _tea_summary_steps(sequence: list[str]) -> list[str]:
    tea_steps = {"atdd", "test_automate", "test_review", "nfr", "trace"}
    return [step.replace("_", "-") for step in sequence if step in tea_steps]


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
        try:
            config_json = read_text(config_file)
        except OSError:
            write_json({"ok": False, "error": "config_file_unreadable"})
            return 1
    if not config_json.strip():
        write_json({"ok": False, "error": "missing_config"})
        return 1
    try:
        config = json.loads(config_json)
    except json.JSONDecodeError:
        write_json({"ok": False, "error": "invalid_config_json"})
        return 1
    if not isinstance(config, dict):
        write_json({"ok": False, "error": "config_must_be_object"})
        return 1
    raw_story_range = config.get("storyRange", [])
    if raw_story_range is not None and not isinstance(raw_story_range, list):
        write_json({"ok": False, "error": "storyRange_must_be_array"})
        return 1
    if raw_story_range and any(not isinstance(item, str) for item in raw_story_range):
        write_json({"ok": False, "error": "storyRange_must_be_array_of_strings"})
        return 1
    story_range = list(raw_story_range or [])
    ensure_dir(output_folder)
    now = now_utc_z()
    stamp = now_utc().strftime("%Y%m%d-%H%M%S")
    epic = str(config.get("epic") or "epic")
    safe_epic = re.sub(r"[^a-zA-Z0-9]+", "-", epic).strip("-") or "epic"
    output_path = Path(output_folder) / f"orchestration-{safe_epic}-{stamp}.md"
    try:
        policy_selection = build_run_policy(Path(get_project_root()), config)
        snapshot = snapshot_effective_policy(get_project_root(), inline_override=policy_selection["policyOverride"])
    except (FileNotFoundError, PolicyError, ValueError) as exc:
        write_json({"ok": False, "error": "policy_snapshot_failed", "reason": str(exc)})
        return 1
    pinned_sequence = [step for step in ((snapshot["policy"].get("workflow") or {}).get("sequence") or []) if isinstance(step, str)]
    pinned_track = workflow_track_for_sequence(pinned_sequence)
    pinned_optional_steps = selected_optional_steps_from_sequence(pinned_sequence)
    progress_header, progress_divider, progress_rows = progress_table_lines(snapshot["policy"], story_range)
    text = read_text(template)
    replacements: dict[str, Any] = {
        "epic": config.get("epic", ""),
        "epicName": config.get("epicName", ""),
        "storyRange": story_range,
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
    if pinned_track == "tea":
        tea_frontmatter = (
            f'workflowTrack: {json.dumps(pinned_track)}\n'
            f"selectedOptionalSteps: {json.dumps(pinned_optional_steps)}\n"
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
        # Model serialization preserves three states so round-trips through
        # `_load_agent_config_from_state` + `resolve_agent` keep the same
        # semantics as the in-memory config:
        #   - key ABSENT  → no `model` line (task inherits defaultModel)
        #   - key PRESENT, sentinel  → `model: ""`  (explicit opt-out — clears
        #     any inherited defaultModel; later parsed back as empty string,
        #     `"model" in entry` is True, resolver assigns "" overriding the
        #     default)
        #   - key PRESENT, real ID  → `model: "<id>"`
        # See bma-d's review of 5ada2c2 for the round-trip regression that
        # motivated this — without preserving the explicit clear, retro/dev
        # tasks silently re-inherited `defaultModel` after persistence.
        if "defaultModel" in agent_config:
            lines.append(f"  defaultModel: {json.dumps(_model_or_none(agent_config.get('defaultModel')))}")
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
                if "model" in entry:
                    lines.append(f"      model: {json.dumps(_model_or_none(entry.get('model')))}")
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
                    if "model" in entry:
                        lines.append(f"        model: {json.dumps(_model_or_none(entry.get('model')))}")
        block = "\n".join(lines) + "\n"
        text = re.sub(r"(?m)^agentConfig:\n(?:(?:\s{2}.*\n)*)", block, text)
    for key, value in replacements.items():
        text = re.sub(rf"(?m)^{re.escape(key)}:.*$", lambda m, k=key, v=value: f"{k}: {json.dumps(v)}", text)
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
    if pinned_track == "tea":
        pinned_tea_steps = _tea_summary_steps(pinned_sequence)
        tea_block_lines = [
            "**TEA Configuration:**",
            f"- Pinned TEA Steps: {', '.join(pinned_tea_steps) or 'none'}",
            f"- Optional Automated Steps: {', '.join(pinned_optional_steps) or 'none'}",
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


def cmd_build_run_policy(args: list[str]) -> int:
    config_file = ""
    config_json = ""
    for idx, arg in enumerate(args):
        if arg == "--config-file" and idx + 1 < len(args):
            config_file = args[idx + 1]
        elif arg == "--config-json" and idx + 1 < len(args):
            config_json = args[idx + 1]
    if config_file and file_exists(config_file):
        try:
            config_json = read_text(config_file)
        except OSError:
            write_json({"ok": False, "error": "config_file_unreadable"})
            return 1
    if not config_json.strip():
        write_json({"ok": False, "error": "missing_config"})
        return 1
    try:
        config = json.loads(config_json)
    except json.JSONDecodeError:
        write_json({"ok": False, "error": "invalid_config_json"})
        return 1
    if not isinstance(config, dict):
        write_json({"ok": False, "error": "config_must_be_object"})
        return 1
    try:
        selection = build_run_policy(Path(get_project_root()), config)
    except (FileNotFoundError, PolicyError, ValueError) as exc:
        write_json({"ok": False, "error": "policy_invalid", "reason": str(exc)})
        return 1
    write_json({"ok": True, **selection})
    return 0
def cmd_detect_workflow_track(args: list[str]) -> int:
    project_root = Path(get_project_root())
    for idx, arg in enumerate(args):
        if arg == "--project-root" and idx + 1 < len(args):
            project_root = Path(args[idx + 1]).expanduser().resolve()
    write_json(detect_workflow_track(project_root))
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
    metrics = progress_metrics(read_text(state))
    print(
        json.dumps(
            {
                "ok": True,
                "storiesCompleted": metrics["storiesCompleted"],
                "total": metrics["total"],
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
