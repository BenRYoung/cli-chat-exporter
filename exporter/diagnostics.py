from __future__ import annotations

import pathlib
from collections import Counter
from dataclasses import dataclass
from typing import Any

from .models import SessionExport
from .utils import first_block_text

KNOWN_CODEX_OUTER_TYPES = {"session_meta", "response_item", "event_msg", "turn_context", "compacted"}
KNOWN_CODEX_RESPONSE_TYPES = {
    "message",
    "reasoning",
    "function_call",
    "function_call_output",
    "web_search_call",
    "custom_tool_call",
    "custom_tool_call_output",
    "image_generation_call",
}
KNOWN_CODEX_EVENT_TYPES = {
    "agent_message",
    "agent_reasoning",
    "collab_agent_interaction_end",
    "collab_agent_spawn_end",
    "collab_close_end",
    "collab_waiting_end",
    "exec_command_end",
    "context_compacted",
    "error",
    "image_generation_end",
    "item_completed",
    "mcp_tool_call_end",
    "patch_apply_end",
    "task_complete",
    "task_started",
    "thread_name_updated",
    "thread_rolled_back",
    "token_count",
    "turn_aborted",
    "user_message",
    "view_image_tool_call",
    "web_search_end",
}
KNOWN_MESSAGE_PART_TYPES = {
    "text",
    "input_text",
    "output_text",
    "input_image",
    "thinking",
    "toolCall",
    "tool_use",
}
KNOWN_CURSOR_ROLES = {"user", "assistant"}
KNOWN_OPENCLAW_ROW_TYPES = {"session", "message", "custom", "model_change", "thinking_level_change"}


@dataclass(frozen=True)
class ParseIssue:
    source: str
    path: pathlib.Path
    reason: str
    detail: str

    def short(self) -> str:
        return f"{self.reason}: {self.detail} ({self.path})"


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload")
    return payload if isinstance(payload, dict) else {}


def _content_has_text(parts: Any) -> bool:
    if not isinstance(parts, list):
        return False
    for part in parts:
        if isinstance(part, dict) and str(part.get("text", "")).strip():
            return True
    return False


def _append_unknown(counter: Counter[str], known: set[str], prefix: str, issues: list[ParseIssue], source: str, path: pathlib.Path) -> None:
    unknown = sorted(key for key in counter if key not in known)
    if unknown:
        details = ", ".join(f"{key}={counter[key]}" for key in unknown[:12])
        issues.append(ParseIssue(source, path, f"unknown {prefix}", details))


def diagnose_codex(path: pathlib.Path, rows: list[dict[str, Any]], session: SessionExport) -> list[ParseIssue]:
    issues: list[ParseIssue] = []
    if not rows:
        return [ParseIssue("codex", path, "empty file", "no JSONL rows")]

    header = _payload(rows[0])
    if rows[0].get("type") != "session_meta" or not header:
        issues.append(ParseIssue("codex", path, "invalid header", "first row is not session_meta with object payload"))
    for key in ("id", "timestamp", "cwd"):
        if not header.get(key):
            issues.append(ParseIssue("codex", path, "missing header field", key))

    outer_types: Counter[str] = Counter()
    response_types: Counter[str] = Counter()
    event_types: Counter[str] = Counter()
    part_types: Counter[str] = Counter()
    raw_text_messages = 0
    for row in rows:
        outer_type = str(row.get("type", "unknown"))
        outer_types[outer_type] += 1
        payload = _payload(row)
        if outer_type == "response_item":
            inner_type = str(payload.get("type", "unknown"))
            response_types[inner_type] += 1
            if inner_type == "message":
                if not payload.get("role"):
                    issues.append(ParseIssue("codex", path, "missing message role", str(payload)[:160]))
                content = payload.get("content")
                if not isinstance(content, list):
                    issues.append(ParseIssue("codex", path, "invalid message content", f"role={payload.get('role')}"))
                elif _content_has_text(content):
                    raw_text_messages += 1
                    for part in content:
                        if isinstance(part, dict):
                            part_types[str(part.get("type", "unknown"))] += 1
        elif outer_type == "event_msg":
            event_types[str(payload.get("type", "unknown"))] += 1

    parsed_text_turns = sum(1 for turn in session.turns if first_block_text(turn.blocks))
    if raw_text_messages and parsed_text_turns == 0:
        issues.append(ParseIssue("codex", path, "no parsed message text", f"raw_text_messages={raw_text_messages}"))

    _append_unknown(outer_types, KNOWN_CODEX_OUTER_TYPES, "Codex outer row type", issues, "codex", path)
    _append_unknown(response_types, KNOWN_CODEX_RESPONSE_TYPES, "Codex response_item type", issues, "codex", path)
    _append_unknown(event_types, KNOWN_CODEX_EVENT_TYPES, "Codex event_msg type", issues, "codex", path)
    _append_unknown(part_types, KNOWN_MESSAGE_PART_TYPES, "Codex content part type", issues, "codex", path)
    return issues


def diagnose_cursor(path: pathlib.Path, rows: list[dict[str, Any]], session: SessionExport) -> list[ParseIssue]:
    issues: list[ParseIssue] = []
    raw_text_messages = 0
    roles: Counter[str] = Counter()
    part_types: Counter[str] = Counter()
    for row in rows:
        role = str(row.get("role", "unknown"))
        roles[role] += 1
        message = row.get("message")
        if not isinstance(message, dict):
            issues.append(ParseIssue("cursor", path, "invalid message object", str(row)[:160]))
            continue
        content = message.get("content")
        if not isinstance(content, list):
            issues.append(ParseIssue("cursor", path, "invalid message content", f"role={role}"))
            continue
        if _content_has_text(content):
            raw_text_messages += 1
        for part in content:
            if isinstance(part, dict):
                part_types[str(part.get("type", "unknown"))] += 1

    parsed_text_turns = sum(1 for turn in session.turns if first_block_text(turn.blocks))
    if raw_text_messages and parsed_text_turns == 0:
        issues.append(ParseIssue("cursor", path, "no parsed message text", f"raw_text_messages={raw_text_messages}"))
    _append_unknown(roles, KNOWN_CURSOR_ROLES, "Cursor role", issues, "cursor", path)
    _append_unknown(part_types, KNOWN_MESSAGE_PART_TYPES, "Cursor content part type", issues, "cursor", path)
    return issues


def diagnose_openclaw(path: pathlib.Path, rows: list[dict[str, Any]], session: SessionExport) -> list[ParseIssue]:
    issues: list[ParseIssue] = []
    if not rows:
        return [ParseIssue("openclaw", path, "empty file", "no JSONL rows")]
    header = rows[0]
    if header.get("type") != "session":
        issues.append(ParseIssue("openclaw", path, "invalid header", "first row is not session"))
    row_types = Counter(str(row.get("type", "unknown")) for row in rows)
    raw_text_messages = 0
    part_types: Counter[str] = Counter()
    for row in rows:
        if row.get("type") != "message":
            continue
        message = row.get("message")
        if not isinstance(message, dict):
            issues.append(ParseIssue("openclaw", path, "invalid message object", str(row)[:160]))
            continue
        content = message.get("content")
        if not isinstance(content, list):
            issues.append(ParseIssue("openclaw", path, "invalid message content", f"role={message.get('role')}"))
            continue
        if _content_has_text(content):
            raw_text_messages += 1
        for part in content:
            if isinstance(part, dict):
                part_types[str(part.get("type", "unknown"))] += 1
    parsed_text_turns = sum(1 for turn in session.turns if first_block_text(turn.blocks))
    if raw_text_messages and parsed_text_turns == 0:
        issues.append(ParseIssue("openclaw", path, "no parsed message text", f"raw_text_messages={raw_text_messages}"))
    _append_unknown(row_types, KNOWN_OPENCLAW_ROW_TYPES, "OpenClaw row type", issues, "openclaw", path)
    _append_unknown(part_types, KNOWN_MESSAGE_PART_TYPES, "OpenClaw content part type", issues, "openclaw", path)
    return issues


def diagnose_session(source: str, path: pathlib.Path, rows: list[dict[str, Any]], session: SessionExport) -> list[ParseIssue]:
    if source == "codex":
        return diagnose_codex(path, rows, session)
    if source == "cursor":
        return diagnose_cursor(path, rows, session)
    if source == "openclaw":
        return diagnose_openclaw(path, rows, session)
    return [ParseIssue(source, path, "unsupported source", source)]
