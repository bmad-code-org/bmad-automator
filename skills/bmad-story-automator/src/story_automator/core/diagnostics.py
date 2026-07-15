from __future__ import annotations

import ast
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DIAGNOSTIC_EVENTS_FILE_ENV = "STORY_AUTOMATOR_DIAGNOSTICS_FILE"
MAX_STRING_LENGTH = 160
MAX_COLLECTION_ITEMS = 6
SECRET_KEY_PATTERN = r"(?:[A-Za-z0-9]+[_.-])*(?:authorization|credential|password|secret|token|api[_-]?key|access[_-]?key)(?:[_.-](?:hash|id|key|secret|value))?"
SENSITIVE_KEY_RE = re.compile(rf"^{SECRET_KEY_PATTERN}$", re.IGNORECASE)
SECRET_ASSIGNMENT_PREFIX_RE = re.compile(
    rf"(?i)(?<![A-Za-z0-9_.{{,-])(['\"]?)({SECRET_KEY_PATTERN})\1(?![A-Za-z0-9_.-])\s*[:=]\s*"
)
SECRET_QUOTED_ASSIGNMENT_RE = re.compile(
    rf"(?i)(?<![A-Za-z0-9_.{{,-])(['\"]?)({SECRET_KEY_PATTERN})\1(?![A-Za-z0-9_.-])\s*[:=]\s*(['\"])(?!<redacted>\3)(?:(?!\3).)*\3"
)
SECRET_ASSIGNMENT_RE = re.compile(
    rf"(?i)(?<![A-Za-z0-9_.{{,-])(['\"]?)({SECRET_KEY_PATTERN})\1(?![A-Za-z0-9_.-])\s*[:=]\s*(?!['\"]?<redacted>['\"]?)(?:(?:bearer|basic|token)\s+)?[^\s,;}}]+"
)
COMMA_SECRET_ASSIGNMENT_RE = re.compile(
    rf"(?i)(?<=,)({SECRET_KEY_PATTERN})(?![A-Za-z0-9_.-])\s*[:=]\s*(?!['\"]?<redacted>['\"]?)(?:(?:bearer|basic|token)\s+)?[^\s,;}}]+"
)
COMMA_SECRET_QUOTED_ASSIGNMENT_RE = re.compile(
    rf"(?i)(?<=,)({SECRET_KEY_PATTERN})(?![A-Za-z0-9_.-])\s*[:=]\s*(['\"])(?!<redacted>\2)(?:(?!\2).)*\2"
)
COMMA_SECRET_COLLECTION_ASSIGNMENT_RE = re.compile(
    rf"(?i)(?<=,)({SECRET_KEY_PATTERN})(?![A-Za-z0-9_.-])\s*[:=]\s*[\[{{].*$"
)
JSON_LIKE_SECRET_FIELD_RE = re.compile(
    rf"(?i)([{{,]\s*)(['\"])({SECRET_KEY_PATTERN})\2\s*:\s*(['\"])(?:(?!\4).)*\4"
)
JSON_LIKE_SECRET_UNQUOTED_FIELD_RE = re.compile(
    rf"(?i)([{{,]\s*)(['\"])({SECRET_KEY_PATTERN})\2\s*:\s*(?!['\"]?<redacted>['\"]?)(?:\[[^\]}}]*(?:\]|$)|\{{[^\]}}]*(?:\}}|$)|[^,}}\s]+)"
)
JSON_LIKE_SECRET_BARE_FIELD_RE = re.compile(
    rf"(?i)([{{,]\s*)({SECRET_KEY_PATTERN})(?![A-Za-z0-9_.-])\s*:\s*(?!<redacted>)(?:\[[^\]}}]*(?:\]|$)|\{{[^\]}}]*(?:\}}|$)|[^,}}\s]+)"
)
ESCAPED_JSON_SECRET_FIELD_RE = re.compile(
    rf"(?i)((?:\\)?['\"])({SECRET_KEY_PATTERN})\1\s*:\s*((?:\\)?['\"])(?:(?!\3).)*(?:\3|(?=,|$))"
)
SECRET_PATH_VALUE_ASSIGNMENT_RE = re.compile(
    rf"(?i)(?<![A-Za-z0-9_.-])({SECRET_KEY_PATTERN})(?![A-Za-z0-9_.-])\s*[:=]\s*(?:(?:bearer|basic|token)\s+)?<path:[^>]+>"
)
SECRET_PATH_PLACEHOLDER_ASSIGNMENT_RE = re.compile(
    rf"(?i)(<path:({SECRET_KEY_PATTERN})>)\s*[:=]\s*(?:(?:bearer|basic|token)\s+)?[^\s,;]+"
)
ABSOLUTE_PATH_WITH_EXT_RE = re.compile(
    r"(?<![\w.-])(?:/(?:[^/,\n;:]+/)+[^,\n;:]*?|[A-Za-z]:[\\/](?:[^\\/,\n;:]+[\\/])+[^,\n;:]*?)\.[A-Za-z0-9][A-Za-z0-9._-]*(?=$|[\s,;:)\]}\"'])"
)
ABSOLUTE_PATH_BEFORE_SECRET_RE = re.compile(
    rf"(?<![\w.-])(?:/(?:[^/,\n;:=]+/)+(?:(?!\s+(?:and\s+)?(?:/|[A-Za-z]:[\\/]))(?!\s+{SECRET_KEY_PATTERN}\s*[:=])[^,\n;:=])+|"
    rf"[A-Za-z]:[\\/](?:[^\\/,\n;:=]+[\\/])+(?:(?!\s+(?:and\s+)?(?:/|[A-Za-z]:[\\/]))(?!\s+{SECRET_KEY_PATTERN}\s*[:=])[^,\n;:=])+)(?=\s+{SECRET_KEY_PATTERN}\s*[:=])"
)
ABSOLUTE_PATH_RE = re.compile(
    r"(?<![\w.-])(?:/(?:[^/\s,\n;:=]+/)+[^/\s,\n;:=]+|[A-Za-z]:[\\/](?:[^\\/\s,\n;:=]+[\\/])+[^\\/\s,\n;:=]+)"
)


class RedactedText(str):
    """String already passed through redact_actual; keep serialization idempotent."""


@dataclass(frozen=True)
class DiagnosticIssue:
    type: str
    field: str = ""
    expected: Any = ""
    actual: Any = ""
    message: str = ""
    recovery: str = ""
    code: str = ""
    severity: str = "error"
    source: str = ""


@dataclass(frozen=True)
class DiagnosticEvent:
    name: str
    source: str
    message: str = ""
    severity: str = "info"
    issues: list[DiagnosticIssue] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)


def serialize_issue(issue: DiagnosticIssue) -> dict[str, Any]:
    return {
        "type": issue.type,
        "field": issue.field,
        "expected": redact_actual(_json_safe(issue.expected)),
        "actual": redact_actual(issue.actual),
        "message": redact_actual(issue.message),
        "recovery": redact_actual(issue.recovery),
        "code": redact_actual(issue.code),
        "severity": issue.severity,
        "source": redact_actual(issue.source),
    }


def serialize_issues(issues: list[DiagnosticIssue] | tuple[DiagnosticIssue, ...]) -> list[dict[str, Any]]:
    return [serialize_issue(issue) for issue in issues]


def serialize_event(event: DiagnosticEvent) -> dict[str, Any]:
    return {
        "name": event.name,
        "source": event.source,
        "message": redact_actual(event.message),
        "severity": event.severity,
        "issues": serialize_issues(event.issues),
        "context": redact_actual(event.context),
    }


def emit_diagnostic_event(event: DiagnosticEvent, path: str | Path | None = None) -> bool:
    target = str(path or os.environ.get(DIAGNOSTIC_EVENTS_FILE_ENV, "")).strip()
    if not target:
        return False
    try:
        output = Path(target).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(serialize_event(event), separators=(",", ":")) + "\n")
    except OSError:
        return False
    return True


def legacy_issue_message(issue: DiagnosticIssue) -> str:
    if issue.message:
        return str(redact_actual(issue.message))
    if issue.field and issue.expected:
        return f"{issue.field}: expected {issue.expected}"
    if issue.field:
        return issue.field
    return issue.type


def issues_from_exception(exc: Exception, source: str, field: str = "") -> list[DiagnosticIssue]:
    raw_message = str(exc)
    message = RedactedText(str(redact_actual(raw_message if raw_message else exc.__class__.__name__)))
    return [
        DiagnosticIssue(
            type=exc.__class__.__name__,
            field=field,
            actual=message,
            message=message,
            severity="error",
            source=source,
        )
    ]


def redact_actual(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, RedactedText):
        return value
    if isinstance(value, Path):
        return _redact_string(str(value))
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for idx, (key, item) in enumerate(value.items()):
            if idx >= MAX_COLLECTION_ITEMS:
                redacted["..."] = f"{len(value) - MAX_COLLECTION_ITEMS} more"
                break
            key_text = str(key)
            safe_key = _redact_string(key_text)
            redacted[safe_key] = "<redacted>" if SENSITIVE_KEY_RE.search(key_text) else redact_actual(item)
        return redacted
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        redacted_items = [redact_actual(item) for item in items[:MAX_COLLECTION_ITEMS]]
        if len(items) > MAX_COLLECTION_ITEMS:
            redacted_items.append(f"... {len(items) - MAX_COLLECTION_ITEMS} more")
        return redacted_items
    return _redact_string(str(value))


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _redact_string(value: str) -> str:
    structured = _redact_json_string(value)
    if structured is not None:
        return structured
    value = JSON_LIKE_SECRET_FIELD_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}{match.group(3)}{match.group(2)}:{match.group(4)}<redacted>{match.group(4)}", value)
    value = _redact_sensitive_json_assignments(value)
    value = _redact_quoted_json_strings(value)
    value = _redact_embedded_json(value)
    value = JSON_LIKE_SECRET_UNQUOTED_FIELD_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}{match.group(3)}{match.group(2)}:<redacted>", value)
    value = JSON_LIKE_SECRET_BARE_FIELD_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}:<redacted>", value)
    value = ESCAPED_JSON_SECRET_FIELD_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}{match.group(1)}:{match.group(3)}<redacted>{match.group(3)}", value)
    value = ABSOLUTE_PATH_WITH_EXT_RE.sub(_path_placeholder, value)
    value = ABSOLUTE_PATH_BEFORE_SECRET_RE.sub(_path_before_secret_placeholder, value)
    value = ABSOLUTE_PATH_RE.sub(_path_placeholder, value)
    value = SECRET_PATH_VALUE_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=<redacted>", value)
    value = SECRET_PATH_PLACEHOLDER_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=<redacted>", value)
    value = SECRET_QUOTED_ASSIGNMENT_RE.sub(lambda match: f"{match.group(2)}=<redacted>", value)
    value = SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(2)}=<redacted>", value)
    value = COMMA_SECRET_COLLECTION_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=<redacted>", value)
    value = COMMA_SECRET_QUOTED_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=<redacted>", value)
    value = COMMA_SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=<redacted>", value)
    if len(value) > MAX_STRING_LENGTH:
        return f"{value[:MAX_STRING_LENGTH]}...<truncated {len(value) - MAX_STRING_LENGTH} chars>"
    return value


def _redact_json_string(value: str) -> str | None:
    stripped = value.strip()
    if not (stripped.startswith("{") or stripped.startswith("[")):
        return None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        try:
            parsed = ast.literal_eval(stripped)
        except (SyntaxError, ValueError):
            return None
    if isinstance(parsed, str) and parsed.strip().startswith(("{", "[")):
        redacted = redact_actual(parsed)
        encoded = json.dumps(redacted, separators=(",", ":"))
        return encoded if len(encoded) <= MAX_STRING_LENGTH else f"{encoded[:MAX_STRING_LENGTH]}...<truncated {len(encoded) - MAX_STRING_LENGTH} chars>"
    redacted = redact_actual(parsed)
    encoded = json.dumps(redacted, separators=(",", ":"))
    return encoded if len(encoded) <= MAX_STRING_LENGTH else f"{encoded[:MAX_STRING_LENGTH]}...<truncated {len(encoded) - MAX_STRING_LENGTH} chars>"


def _redact_sensitive_json_assignments(value: str) -> str:
    output: list[str] = []
    index = 0
    changed = False
    while index < len(value):
        match = SECRET_ASSIGNMENT_PREFIX_RE.match(value, index)
        if not match:
            output.append(value[index])
            index += 1
            continue
        value_start = match.end()
        if value_start >= len(value) or value[value_start] not in "{[":
            output.append(value[index])
            index += 1
            continue
        decoded = _decode_collection_prefix(value[value_start:])
        if decoded is None:
            output.append(f"{match.group(2)}=<redacted>")
            index = len(value)
            changed = True
            continue
        _parsed, end = decoded
        output.append(f"{match.group(2)}=<redacted>")
        index = value_start + end
        changed = True
    return "".join(output) if changed else value


def _redact_quoted_json_strings(value: str) -> str:
    decoder = json.JSONDecoder()
    output: list[str] = []
    index = 0
    changed = False
    while index < len(value):
        if value[index] not in "\"'":
            output.append(value[index])
            index += 1
            continue
        try:
            parsed, end = decoder.raw_decode(value[index:])
        except json.JSONDecodeError:
            literal = _decode_quoted_literal_prefix(value[index:])
            if literal is None:
                output.append(value[index])
                index += 1
                continue
            parsed, end = literal
        if not (isinstance(parsed, str) and parsed.strip().startswith(("{", "["))):
            output.append(value[index])
            index += 1
            continue
        output.append(json.dumps(redact_actual(parsed), separators=(",", ":")))
        index += end
        changed = True
    return "".join(output) if changed else value


def _redact_embedded_json(value: str) -> str:
    output: list[str] = []
    index = 0
    changed = False
    while index < len(value):
        if value[index] not in "{[":
            output.append(value[index])
            index += 1
            continue
        decoded = _decode_collection_prefix(value[index:])
        if decoded is None:
            output.append(value[index])
            index += 1
            continue
        parsed, end = decoded
        redacted = redact_actual(parsed)
        output.append(json.dumps(redacted, separators=(",", ":")))
        index += end
        changed = True
    return "".join(output) if changed else value


def _decode_collection_prefix(value: str) -> tuple[Any, int] | None:
    decoder = json.JSONDecoder()
    try:
        return decoder.raw_decode(value)
    except json.JSONDecodeError:
        pass
    end = _balanced_collection_end(value)
    if end <= 0:
        return None
    try:
        return ast.literal_eval(value[:end]), end
    except (SyntaxError, ValueError):
        return None


def _decode_quoted_literal_prefix(value: str) -> tuple[Any, int] | None:
    end = _quoted_literal_end(value)
    if end <= 0:
        return None
    try:
        return ast.literal_eval(value[:end]), end
    except (SyntaxError, ValueError):
        return None


def _balanced_collection_end(value: str) -> int:
    if not value or value[0] not in "{[":
        return -1
    opening = {"{": "}", "[": "]"}
    stack = [opening[value[0]]]
    quote = ""
    escaped = False
    for index, char in enumerate(value[1:], start=1):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in {"'", '"'}:
            quote = char
            continue
        if char in opening:
            stack.append(opening[char])
            continue
        if stack and char == stack[-1]:
            stack.pop()
            if not stack:
                return index + 1
    return -1


def _quoted_literal_end(value: str) -> int:
    if not value or value[0] not in {"'", '"'}:
        return -1
    quote = value[0]
    escaped = False
    for index, char in enumerate(value[1:], start=1):
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == quote:
            return index + 1
    return -1


def _path_placeholder(match: re.Match[str]) -> str:
    path = match.group(0)
    name = path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return f"<path:{name}>" if name else "<path>"


def _path_before_secret_placeholder(match: re.Match[str]) -> str:
    value = match.group(0)
    if len(list(ABSOLUTE_PATH_RE.finditer(value))) > 1:
        return ABSOLUTE_PATH_RE.sub(_path_placeholder, value)
    return _path_placeholder(match)
