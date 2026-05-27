from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .runtime_policy import workflow_sequence
from .utils import read_text


def story_progress_steps(policy: dict[str, Any]) -> list[str]:
    return [step for step in workflow_sequence(policy) if step != "retro"]


def progress_headers(policy: dict[str, Any]) -> list[str]:
    headers = ["Story"]
    steps = policy.get("steps") or {}
    for step in story_progress_steps(policy):
        contract = steps.get(step) if isinstance(steps, dict) else None
        label = str((contract or {}).get("label") or step).strip() or step
        headers.append(label.replace("_", "-"))
    headers.extend(["git-commit", "Status"])
    return headers


def progress_table_lines(policy: dict[str, Any], story_range: list[str]) -> tuple[str, str, str]:
    headers = progress_headers(policy)
    divider = markdown_divider(len(headers))
    pending_cells = ["⏳"] * (len(headers) - 3) + ["⏳", "pending"]
    rows = "\n".join("| " + " | ".join([story_id, *pending_cells]) + " |" for story_id in story_range)
    return (
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(divider) + " |",
        rows,
    )


def markdown_divider(width: int) -> list[str]:
    return ["-------" if idx == 0 else "----------" for idx in range(width)]


def parse_markdown_cells(line: str) -> list[str]:
    parts = [part.strip() for part in line.split("|")]
    return [part for part in parts[1:-1]]


def render_markdown_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def normalize_progress_key(value: str, policy: dict[str, Any] | None = None) -> str:
    key = str(value or "").strip().lower().replace("_", "-")
    aliases = {
        "create": "create-story",
        "create-story": "create-story",
        "dev": "dev-story",
        "dev-story": "dev-story",
        "auto": "automate",
        "automate": "automate",
        "review": "code-review",
        "code-review": "code-review",
        "git_commit": "git-commit",
        "git-commit": "git-commit",
        "status": "status",
        "story": "story",
    }
    if policy is not None:
        steps = policy.get("steps") or {}
        for step in story_progress_steps(policy):
            contract = steps.get(step) if isinstance(steps, dict) else None
            label = str((contract or {}).get("label") or step).strip().lower().replace("_", "-")
            aliases[step.replace("_", "-")] = label
            aliases[label] = label
    return aliases.get(key, key)


def sanitize_progress_value(value: str) -> str | None:
    trimmed = value.strip()
    if not trimmed or "|" in trimmed or "\n" in trimmed or "\r" in trimmed:
        return None
    return trimmed


def update_story_progress(state_file: str | Path, story_id: str, updates: dict[str, str], *, policy: dict[str, Any] | None = None) -> tuple[bool, dict[str, Any]]:
    try:
        lines = read_text(state_file).splitlines()
    except OSError:
        return False, {"ok": False, "error": "state_file_unreadable"}
    header_idx = -1
    story_idx = -1
    headers: list[str] = []
    story_cells: list[str] = []
    for i, line in enumerate(lines):
        if line.startswith("| Story "):
            header_idx = i
            headers = [normalize_progress_key(cell, policy) for cell in parse_markdown_cells(line)]
            continue
        if header_idx >= 0 and line.startswith(f"| {story_id} |"):
            story_idx = i
            story_cells = parse_markdown_cells(line)
            break
    if header_idx < 0 or not headers:
        return False, {"ok": False, "error": "progress_table_not_found"}
    if story_idx < 0 or not story_cells:
        return False, {"ok": False, "error": "story_row_not_found"}
    if len(story_cells) != len(headers):
        return False, {"ok": False, "error": "progress_row_misaligned"}

    header_map = {name: pos for pos, name in enumerate(headers)}
    applied: list[str] = []
    for key, value in updates.items():
        normalized_key = normalize_progress_key(key, policy)
        if normalized_key == "story":
            return False, {"ok": False, "error": "story_column_immutable"}
        sanitized = sanitize_progress_value(value)
        if sanitized is None:
            return False, {"ok": False, "error": "invalid_progress_value", "argument": f"{key}={value}"}
        pos = header_map.get(normalized_key)
        if pos is None:
            continue
        story_cells[pos] = sanitized
        applied.append(normalized_key)
    if not applied:
        return False, {"ok": False, "error": "progress_columns_not_found"}
    lines[story_idx] = render_markdown_row(story_cells)
    try:
        Path(state_file).write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        return False, {"ok": False, "error": "state_file_unwritable"}
    return True, {"ok": True, "story": story_id, "updated": applied}


def progress_metrics(text: str) -> dict[str, int]:
    total = 0
    completed = 0
    in_table = False
    for line in text.splitlines():
        if line.startswith("| Story "):
            in_table = True
            continue
        if in_table and re.match(r"^\|[- ]*\|", line):
            continue
        if in_table and line.startswith("|"):
            parts = [part.strip() for part in line.split("|")]
            values = parts[1:-1]
            if len(values) >= 2:
                first_cell = values[0].strip()
                if re.fullmatch(r"-+", first_cell):
                    continue
                total += 1
                if values[-1].strip().lower() in {"done", "complete", "completed"}:
                    completed += 1
            continue
        if in_table and not line.startswith("|"):
            in_table = False
    return {"storiesCompleted": completed, "total": total}
