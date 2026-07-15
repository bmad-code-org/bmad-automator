from __future__ import annotations

import json

from .workflow_steps import summary_steps_for_track


def policy_frontmatter_block(
    track: str,
    optional_steps: list[str],
    manual_checkpoints: list[str],
    notes: list[str],
) -> str:
    if track == "standard":
        return ""
    return (
        f"workflowTrack: {json.dumps(track)}\n"
        f"selectedOptionalSteps: {json.dumps(optional_steps)}\n"
        f"manualCheckpoints: {json.dumps(manual_checkpoints)}\n"
        f"policyNotes: {json.dumps(notes)}\n"
    )


def policy_summary_block(track: str, sequence: list[str], optional_steps: list[str], notes: list[str]) -> str:
    if track == "standard":
        return ""
    display_track = track.upper()
    selected_steps = summary_steps_for_track(sequence, track)
    lines = [
        f"**{display_track} Configuration:**",
        f"- Pinned {display_track} Steps: {', '.join(selected_steps) or 'none'}",
        f"- Optional Automated Steps: {', '.join(optional_steps) or 'none'}",
        f"- Policy Notes: {'; '.join(notes) or 'none'}",
        "",
    ]
    return "\n".join(lines)
