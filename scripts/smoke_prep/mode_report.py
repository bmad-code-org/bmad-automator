from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def write_mode_report(repo_root: Path, summary: dict[str, object]) -> tuple[Path, dict[str, object]]:
    report = repo_root / ".smoke" / "MODE_SMOKE_REPORT.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    payload = _report_payload(repo_root, summary)
    report.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return report, payload


def _report_payload(repo_root: Path, summary: dict[str, object]) -> dict[str, object]:
    payload = dict(summary)
    payload["project"] = {
        "kind": "ephemeral",
        "name": "mode smoke fixture",
        "retained": False,
    }
    payload["createdAt"] = datetime.now(timezone.utc).isoformat()
    diagnostics = _persist_diagnostics(repo_root, payload)
    if diagnostics:
        payload["diagnostics"] = diagnostics
        resume = payload.get("resume")
        if isinstance(resume, dict) and isinstance(resume.get("latestIncomplete"), str):
            if "latestIncomplete" not in diagnostics:
                raise ValueError(f"failed to persist latest incomplete state: {resume['latestIncomplete']}")
            payload["resume"] = {**resume, "latestIncomplete": diagnostics["latestIncomplete"]}
    return payload


def _persist_diagnostics(repo_root: Path, payload: dict[str, object]) -> dict[str, str]:
    dest = repo_root / ".smoke" / "mode-diagnostics"
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    diagnostics: dict[str, str] = {"folder": str(dest)}
    resume = payload.get("resume")
    latest = resume.get("latestIncomplete") if isinstance(resume, dict) else None
    if isinstance(latest, str):
        latest_path = Path(latest)
        if latest_path.exists():
            latest_dest = dest / latest_path.name
            latest_dest.write_text(latest_path.read_text(encoding="utf-8"), encoding="utf-8")
            diagnostics["latestIncomplete"] = str(latest_dest)
    return diagnostics
