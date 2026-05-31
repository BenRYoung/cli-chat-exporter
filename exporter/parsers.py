from __future__ import annotations

import pathlib
import re
from typing import Any

from .models import SessionExport, Turn
from .utils import (
    SOURCE_TITLES,
    beautify_message_text,
    clean_meta,
    first_block_text,
    format_timestamp,
    json_block,
    parse_json_maybe,
    short_text,
    text_block,
    to_iso_from_epoch,
    tool_block,
)


class PendingAssistant:
    def __init__(self) -> None:
        self.timestamp: str | None = None
        self.blocks: list = []

    def add(self, block, timestamp: str | None) -> None:
        if self.timestamp is None:
            self.timestamp = timestamp
        self.blocks.append(block)

    def take(self) -> tuple[str | None, list]:
        timestamp = self.timestamp
        blocks = self.blocks[:]
        self.timestamp = None
        self.blocks.clear()
        return timestamp, blocks

    def has_items(self) -> bool:
        return bool(self.blocks)


def _message_blocks(source: str, role: str, parts: list[dict[str, Any]]) -> tuple[list, list]:
    text_parts: list[str] = []
    detail_blocks: list = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        part_type = str(part.get("type", "unknown"))
        if part_type in {"text", "input_text", "output_text"}:
            text = str(part.get("text", "")).strip()
            if text:
                text_parts.append(text)
        elif part_type == "thinking":
            thinking = str(part.get("thinking", "")).strip()
            if thinking:
                detail_blocks.append(text_block("Thinking", thinking))
        elif part_type == "toolCall":
            payload = part.get("arguments")
            if payload is None and part.get("partialJson"):
                payload = parse_json_maybe(part.get("partialJson"))
            detail_blocks.append(tool_block(f"Tool Call: {part.get('name', 'tool')}", payload))
        elif part_type == "tool_use":
            detail_blocks.append(tool_block(f"Tool Use: {part.get('name', 'tool')}", part.get("input", part)))
        else:
            detail_blocks.append(json_block(f"Part: {part_type}", part))

    blocks: list = []
    if text_parts:
        main_text, extra_blocks = beautify_message_text(source, role, "\n\n".join(text_parts))
        if main_text:
            blocks.append(text_block("Message", main_text))
        detail_blocks = extra_blocks + detail_blocks
    return blocks, detail_blocks


def _preview_from_turns(turns: list[Turn]) -> str:
    for turn in turns:
        if turn.role == "user":
            text = first_block_text(turn.blocks)
            if text:
                return short_text(text)
    return ""


def _flush_pending(turns: list[Turn], pending: PendingAssistant) -> None:
    if not pending.has_items():
        return
    timestamp, blocks = pending.take()
    turns.append(
        Turn(
            role="assistant",
            title="Assistant",
            timestamp=timestamp,
            blocks=[],
            detail_blocks=blocks,
        )
    )


def _call_suffix(payload: dict[str, Any]) -> str:
    call_id = str(payload.get("call_id") or "").strip()
    return f" ({call_id})" if call_id else ""


def _image_payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key, value in payload.items():
        if key == "result" and isinstance(value, str):
            summary["result_omitted"] = f"{len(value)} characters"
            continue
        summary[key] = value
    return summary


def _limited_list(items: list[Any], limit: int) -> tuple[list[Any], int]:
    return items[:limit], max(0, len(items) - limit)


def _tool_search_tool_summary(tool: Any) -> Any:
    if not isinstance(tool, dict):
        return tool
    summary: dict[str, Any] = {}
    for key in ("type", "name"):
        if tool.get(key) is not None:
            summary[key] = tool.get(key)
    description = str(tool.get("description") or "").strip()
    if description:
        summary["description"] = short_text(description, 240)
    child_tools = tool.get("tools")
    if isinstance(child_tools, list):
        limited_tools, omitted = _limited_list(child_tools, 20)
        summary["tools_count"] = len(child_tools)
        summary["tools"] = [_tool_search_tool_summary(item) for item in limited_tools]
        if omitted:
            summary["tools_omitted"] = omitted
    return summary or tool


def _tool_search_payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key, value in payload.items():
        if key == "tools" and isinstance(value, list):
            limited_tools, omitted = _limited_list(value, 20)
            summary["tools_count"] = len(value)
            summary["tools"] = [_tool_search_tool_summary(tool) for tool in limited_tools]
            if omitted:
                summary["tools_omitted"] = omitted
        else:
            summary[key] = value
    return summary


def _goal_payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    goal = payload.get("goal")
    summary: dict[str, Any] = {
        key: payload.get(key)
        for key in ("type", "threadId", "turnId")
        if payload.get(key) is not None
    }
    if isinstance(goal, dict):
        summary["goal"] = {
            key: goal.get(key)
            for key in (
                "threadId",
                "objective",
                "status",
                "tokenBudget",
                "tokensUsed",
                "timeUsedSeconds",
                "createdAt",
                "updatedAt",
            )
            if goal.get(key) is not None
        }
        extras = {
            key: value
            for key, value in goal.items()
            if key not in summary["goal"]
        }
        if extras:
            summary["goal_extra"] = extras
    else:
        summary["goal"] = goal
    return summary


def _goal_update_turn(payload: dict[str, Any], timestamp: str | None) -> Turn:
    goal = payload.get("goal")
    goal_data = goal if isinstance(goal, dict) else {}
    objective = str(goal_data.get("objective") or "").strip()
    status = str(goal_data.get("status") or "").strip()
    meta = clean_meta(
        [
            f"Status: {status}" if status else None,
            f"Tokens used: {goal_data.get('tokensUsed')}" if goal_data.get("tokensUsed") is not None else None,
            (
                f"Token budget: {goal_data.get('tokenBudget')}"
                if goal_data.get("tokenBudget") is not None
                else None
            ),
            (
                f"Time used: {goal_data.get('timeUsedSeconds')}s"
                if goal_data.get("timeUsedSeconds") is not None
                else None
            ),
            f"Thread ID: {payload.get('threadId')}" if payload.get("threadId") else None,
            f"Turn ID: {payload.get('turnId')}" if payload.get("turnId") else None,
        ]
    )
    blocks = [text_block("Goal Objective", objective)] if objective else [json_block("Goal", goal)]
    return Turn(
        role="event",
        title="Goal Update",
        timestamp=timestamp,
        meta=meta,
        blocks=blocks,
        detail_blocks=[json_block("Goal Metadata", _goal_payload_summary(payload))],
    )


def _goal_update_key(payload: dict[str, Any]) -> tuple[str, str, str]:
    goal = payload.get("goal")
    goal_data = goal if isinstance(goal, dict) else {}
    thread_id = goal_data.get("threadId") or payload.get("threadId") or ""
    objective = goal_data.get("objective") or ""
    status = goal_data.get("status") or ""
    return str(thread_id), str(objective), str(status)


def _replace_turn_content(target: Turn, source: Turn) -> None:
    target.timestamp = source.timestamp
    target.meta = source.meta
    target.blocks = source.blocks
    target.detail_blocks = source.detail_blocks


def _append_assistant_detail(
    current_assistant: Turn | None,
    pending: PendingAssistant,
    block,
    timestamp: str | None,
) -> None:
    if current_assistant is not None:
        current_assistant.detail_blocks.append(block)
    else:
        pending.add(block, timestamp)


def _is_codex_context_turn(turn: Turn) -> bool:
    if turn.role != "user":
        return False
    text = first_block_text(turn.blocks)
    if not text:
        return False
    return text.startswith("# AGENTS.md instructions for ") or "<environment_context>" in text


def _dedupe_adjacent_turns(turns: list[Turn]) -> list[Turn]:
    def norm_blocks(blocks) -> list[str]:
        return [" ".join(block.body.split()) for block in blocks]

    deduped: list[Turn] = []
    for turn in turns:
        if not deduped:
            deduped.append(turn)
            continue
        prev = deduped[-1]
        if (
            prev.role == turn.role
            and format_timestamp(prev.timestamp) == format_timestamp(turn.timestamp)
            and norm_blocks(prev.blocks) == norm_blocks(turn.blocks)
        ):
            if len(turn.detail_blocks) + len(turn.meta) > len(prev.detail_blocks) + len(prev.meta):
                deduped[-1] = turn
            continue
        deduped.append(turn)
    return deduped


def _cursor_project_name(path: pathlib.Path) -> str:
    project_key = path.parents[2].name if len(path.parents) >= 3 else ""
    if not project_key:
        return "root"
    if project_key.isdigit():
        return "root"
    if re.match(r"^[A-Za-z](-[A-Za-z0-9._-]+)+$", project_key):
        drive, rest = project_key.split("-", 1)
        return f"{drive.upper()}:/{rest.replace('-', '/')}"
    if re.match(r"^(mnt|home|Users)(-[A-Za-z0-9._-]+)+$", project_key):
        return project_key.replace("-", "/")
    return "root"


def _openclaw_project_path(cwd: str) -> str:
    if not cwd:
        return "root"
    normalized = cwd.replace("\\", "/")
    normalized = normalized.replace("/.openclaw/workspace", "")
    return normalized or "root"


def _turn_from_message_payload(
    source: str,
    payload: dict[str, Any],
    timestamp: str | None,
    meta: list[str] | None = None,
) -> Turn:
    role = str(payload.get("role", "unknown"))
    blocks, detail_blocks = _message_blocks(source, role, payload.get("content", []))
    return Turn(
        role=role,
        title=role.title(),
        timestamp=timestamp,
        meta=meta or [],
        blocks=blocks,
        detail_blocks=detail_blocks,
    )


def normalize_codex(path: pathlib.Path, rows: list[dict[str, Any]]) -> SessionExport:
    header = rows[0].get("payload", {}) if rows else {}
    session_id = str(header.get("id", path.stem))
    started_at = header.get("timestamp") or (rows[0].get("timestamp") if rows else None)
    cwd = str(header.get("cwd", ""))
    turns: list[Turn] = []
    current_assistant: Turn | None = None
    pending = PendingAssistant()
    goal_update_turns: dict[tuple[str, str, str], Turn] = {}

    for row in rows[1:]:
        outer_type = row.get("type", "unknown")
        timestamp = row.get("timestamp")
        payload = row.get("payload", {})

        if outer_type == "response_item":
            inner_type = payload.get("type", "unknown")
            if inner_type == "message":
                role = str(payload.get("role", "unknown"))
                blocks, detail_blocks = _message_blocks("codex", role, payload.get("content", []))
                if role == "user":
                    probe_turn = Turn(role=role, title="User", timestamp=timestamp, blocks=blocks)
                    if _is_codex_context_turn(probe_turn):
                        role = "context"
                turn = Turn(
                    role=role,
                    title=role.title(),
                    timestamp=timestamp,
                    meta=clean_meta([f"Phase: {payload.get('phase')}" if payload.get("phase") else None]),
                    blocks=blocks,
                    detail_blocks=detail_blocks,
                )
                if role == "assistant":
                    if pending.has_items():
                        _, pending_blocks = pending.take()
                        turn.detail_blocks = pending_blocks + turn.detail_blocks
                    turns.append(turn)
                    current_assistant = turn
                else:
                    _flush_pending(turns, pending)
                    turns.append(turn)
                    current_assistant = None
            elif inner_type == "reasoning":
                summary = payload.get("summary") or []
                summary_text = "\n\n".join(
                    str(item.get("text", "")).strip()
                    for item in summary
                    if isinstance(item, dict) and item.get("type") == "summary_text"
                ).strip()
                if not summary_text:
                    summary_text = str(payload.get("content") or "").strip() or "(Encrypted reasoning omitted)"
                block = text_block("Thinking", summary_text)
                if current_assistant is not None:
                    current_assistant.detail_blocks.append(block)
                else:
                    pending.add(block, timestamp)
            elif inner_type == "function_call":
                arguments = parse_json_maybe(payload.get("arguments"))
                block = tool_block(
                    f"Tool Call: {payload.get('name', 'tool')}{_call_suffix(payload)}",
                    {
                        "name": payload.get("name"),
                        "call_id": payload.get("call_id"),
                        "arguments": arguments,
                    },
                )
                if current_assistant is not None:
                    current_assistant.detail_blocks.append(block)
                else:
                    pending.add(block, timestamp)
            elif inner_type == "function_call_output":
                block = text_block(
                    f"Tool Result{_call_suffix(payload)}",
                    str(payload.get("output", "")).rstrip() or "(empty)",
                )
                if current_assistant is not None:
                    current_assistant.detail_blocks.append(block)
                else:
                    pending.add(block, timestamp)
            elif inner_type == "web_search_call":
                block = tool_block(f"Web Search{_call_suffix(payload)}", payload)
                _append_assistant_detail(current_assistant, pending, block, timestamp)
            elif inner_type == "custom_tool_call":
                block = tool_block(
                    f"Custom Tool Call: {payload.get('name', 'tool')}{_call_suffix(payload)}",
                    payload,
                )
                _append_assistant_detail(current_assistant, pending, block, timestamp)
            elif inner_type == "custom_tool_call_output":
                output = payload.get("output", "")
                parsed_output = parse_json_maybe(output)
                block = tool_block(f"Custom Tool Result{_call_suffix(payload)}", parsed_output)
                _append_assistant_detail(current_assistant, pending, block, timestamp)
            elif inner_type == "image_generation_call":
                block = tool_block("Image Generation", _image_payload_summary(payload))
                _append_assistant_detail(current_assistant, pending, block, timestamp)
            elif inner_type == "tool_search_call":
                arguments = payload.get("arguments")
                if isinstance(arguments, str):
                    arguments = parse_json_maybe(arguments)
                query = ""
                if isinstance(arguments, dict):
                    query = str(arguments.get("query") or "").strip()
                title = f"Tool Search: {short_text(query, 48)}" if query else "Tool Search"
                block = tool_block(f"{title}{_call_suffix(payload)}", _tool_search_payload_summary(payload))
                _append_assistant_detail(current_assistant, pending, block, timestamp)
            elif inner_type == "tool_search_output":
                block = tool_block(
                    f"Tool Search Result{_call_suffix(payload)}",
                    _tool_search_payload_summary(payload),
                )
                _append_assistant_detail(current_assistant, pending, block, timestamp)
            else:
                _flush_pending(turns, pending)
                turns.append(
                    Turn(
                        role="event",
                        title=f"Event: {inner_type}",
                        timestamp=timestamp,
                        blocks=[json_block("Payload", payload)],
                    )
                )
                current_assistant = None
        elif outer_type == "compacted":
            _flush_pending(turns, pending)
            replacement_history = payload.get("replacement_history", []) if isinstance(payload, dict) else []
            restored = 0
            for item in replacement_history:
                if not isinstance(item, dict) or item.get("type") != "message":
                    continue
                turn = _turn_from_message_payload(
                    "codex",
                    item,
                    timestamp,
                    meta=clean_meta(["From compacted history"]),
                )
                if turn.blocks or turn.detail_blocks:
                    turns.append(turn)
                    restored += 1
            extra_payload = (
                {key: value for key, value in payload.items() if key != "replacement_history"}
                if isinstance(payload, dict)
                else {}
            )
            turns.append(
                Turn(
                    role="event",
                    title="Event: compacted",
                    timestamp=timestamp,
                    blocks=[
                        json_block(
                            "Payload",
                            {
                                **extra_payload,
                                "restored_messages": restored,
                            },
                        )
                    ],
                )
            )
            current_assistant = None
        elif outer_type == "event_msg":
            inner_type = payload.get("type", "unknown")
            if inner_type == "agent_message":
                turn = Turn(
                    role="assistant",
                    title="Assistant",
                    timestamp=timestamp,
                    meta=clean_meta([f"Phase: {payload.get('phase')}" if payload.get("phase") else None]),
                    blocks=[text_block("Message", str(payload.get("message", "")).strip() or "(empty)")],
                )
                if pending.has_items():
                    _, pending_blocks = pending.take()
                    turn.detail_blocks = pending_blocks
                turns.append(turn)
                current_assistant = turn
            elif inner_type == "agent_reasoning":
                block = text_block("Agent Reasoning", str(payload.get("text", "")).strip() or "(empty)")
                _append_assistant_detail(current_assistant, pending, block, timestamp)
            elif inner_type == "image_generation_end":
                block = tool_block("Image Generation Result", _image_payload_summary(payload))
                _append_assistant_detail(current_assistant, pending, block, timestamp)
            elif inner_type == "user_message":
                _flush_pending(turns, pending)
                turns.append(
                    Turn(
                        role="user",
                        title="User",
                        timestamp=timestamp,
                        blocks=[text_block("Message", str(payload.get("message", "")).strip() or "(empty)")],
                    )
                )
                current_assistant = None
            elif inner_type == "thread_goal_updated":
                _flush_pending(turns, pending)
                goal_turn = _goal_update_turn(payload, timestamp)
                goal_key = _goal_update_key(payload)
                existing_goal_turn = goal_update_turns.get(goal_key)
                if existing_goal_turn is None:
                    turns.append(goal_turn)
                    goal_update_turns[goal_key] = goal_turn
                else:
                    _replace_turn_content(existing_goal_turn, goal_turn)
                current_assistant = None
            else:
                _flush_pending(turns, pending)
                turns.append(
                    Turn(
                        role="event",
                        title=f"Event: {inner_type}",
                        timestamp=timestamp,
                        blocks=[json_block("Payload", payload)],
                    )
                )
                current_assistant = None
        else:
            _flush_pending(turns, pending)
            turns.append(
                Turn(
                    role="event",
                    title=f"Event: {outer_type}",
                    timestamp=timestamp,
                    blocks=[json_block("Payload", row if outer_type != "turn_context" else payload or row)],
                )
            )
            current_assistant = None

    _flush_pending(turns, pending)
    turns = _dedupe_adjacent_turns(turns)
    preview = _preview_from_turns(turns)
    facts = [
        ("Source", SOURCE_TITLES["codex"]),
        ("Session ID", session_id),
        ("Started", format_timestamp(started_at)),
        ("Turns", str(len(turns))),
        ("CWD", cwd),
        ("File", str(path)),
    ]
    return SessionExport("codex", session_id, started_at, cwd, preview, facts, turns)


def normalize_openclaw(path: pathlib.Path, rows: list[dict[str, Any]]) -> SessionExport:
    header = rows[0] if rows else {}
    session_id = str(header.get("id", path.stem))
    started_at = header.get("timestamp")
    cwd = str(header.get("cwd", ""))
    project_path = _openclaw_project_path(cwd)
    agent_id = path.parent.parent.name
    turns: list[Turn] = []
    current_assistant: Turn | None = None
    pending = PendingAssistant()

    for row in rows[1:]:
        row_type = row.get("type", "unknown")
        timestamp = row.get("timestamp")
        if row_type == "message":
            message = row.get("message", {})
            role = str(message.get("role", "unknown"))
            blocks, detail_blocks = _message_blocks("openclaw", role, message.get("content", []))
            meta = clean_meta(
                [
                    f"Tool: {message.get('toolName')}" if message.get("toolName") else None,
                    f"Tool Call ID: {message.get('toolCallId')}" if message.get("toolCallId") else None,
                ]
            )
            if message.get("details") is not None:
                detail_blocks.append(json_block("Details", message.get("details")))

            if role == "toolResult":
                block = text_block("Tool Result", first_block_text(blocks) or json_block("Tool Result", message).body)
                if current_assistant is not None:
                    current_assistant.detail_blocks.append(block)
                else:
                    pending.add(block, timestamp)
                continue

            turn = Turn(role=role, title=role.title(), timestamp=timestamp, meta=meta, blocks=blocks, detail_blocks=detail_blocks)
            if role == "assistant":
                if pending.has_items():
                    _, pending_blocks = pending.take()
                    turn.detail_blocks = pending_blocks + turn.detail_blocks
                turns.append(turn)
                current_assistant = turn
            else:
                _flush_pending(turns, pending)
                turns.append(turn)
                current_assistant = None
        else:
            _flush_pending(turns, pending)
            payload = {k: v for k, v in row.items() if k not in {"id", "parentId", "timestamp"}}
            turns.append(
                Turn(
                    role="event",
                    title=f"Event: {row_type}",
                    timestamp=timestamp,
                    blocks=[json_block("Payload", payload)],
                )
            )
            current_assistant = None

    _flush_pending(turns, pending)
    preview = _preview_from_turns(turns)
    facts = [
        ("Source", SOURCE_TITLES["openclaw"]),
        ("Session ID", session_id),
        ("Started", format_timestamp(started_at)),
        ("Turns", str(len(turns))),
        ("Agent", agent_id),
        ("CWD", cwd),
        ("File", str(path)),
    ]
    return SessionExport("openclaw", session_id, started_at, project_path, preview, facts, turns)


def normalize_cursor(path: pathlib.Path, rows: list[dict[str, Any]]) -> SessionExport:
    session_id = path.stem
    started_at = to_iso_from_epoch(path.stat().st_mtime)
    project_id = _cursor_project_name(path)
    turns: list[Turn] = []

    for row in rows:
        role = str(row.get("role", "unknown"))
        message = row.get("message", {})
        blocks, detail_blocks = _message_blocks("cursor", role, message.get("content", []))
        turns.append(
            Turn(
                role=role,
                title=role.title(),
                timestamp=None,
                blocks=blocks,
                detail_blocks=detail_blocks,
            )
        )

    preview = _preview_from_turns(turns)
    facts = [
        ("Source", SOURCE_TITLES["cursor"]),
        ("Session ID", session_id),
        ("Last Modified", format_timestamp(started_at)),
        ("Turns", str(len(turns))),
        ("Project", project_id),
        ("File", str(path)),
    ]
    return SessionExport("cursor", session_id, started_at, project_id, preview, facts, turns)


def normalize_session(source: str, path: pathlib.Path, rows: list[dict[str, Any]]) -> SessionExport:
    if source == "codex":
        return normalize_codex(path, rows)
    if source == "openclaw":
        return normalize_openclaw(path, rows)
    if source == "cursor":
        return normalize_cursor(path, rows)
    raise SystemExit(f"Unsupported source: {source}")
