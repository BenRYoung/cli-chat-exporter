from __future__ import annotations

import datetime as dt
import html
import json
import os
import pathlib
import re
import subprocess
from typing import Any

from .models import Block

SOURCE_PATTERNS = {
    "codex": "~/.codex/sessions/*/*/*/*.jsonl",
    "openclaw": "~/.openclaw/agents/*/sessions/*.jsonl",
    "cursor": "~/.cursor/projects/*/agent-transcripts/*/*.jsonl",
}

SOURCE_TITLES = {
    "codex": "Codex",
    "openclaw": "OpenClaw",
    "cursor": "Cursor",
}


def is_windows() -> bool:
    return os.name == "nt"


def run_wsl(distro: str, command: str) -> str:
    result = subprocess.run(
        ["wsl.exe", "-d", distro, "--", "bash", "-lc", command],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def linux_to_unc(path: str, distro: str) -> pathlib.Path:
    if not path.startswith("/"):
        raise ValueError(f"Not a Linux absolute path: {path}")
    windows_path = path.replace("/", "\\")
    return pathlib.Path(f"\\\\wsl$\\{distro}{windows_path}")


def resolve_path(raw_path: str, distro: str) -> pathlib.Path:
    if raw_path.startswith("\\\\wsl$\\"):
        return pathlib.Path(raw_path)
    if is_windows() and raw_path.startswith("/"):
        return linux_to_unc(raw_path, distro)
    return pathlib.Path(raw_path).expanduser()


def default_output_root() -> pathlib.Path:
    env_output_root = os.environ.get("CCE_DEFAULT_OUTPUT")
    if env_output_root:
        return pathlib.Path(env_output_root).expanduser()
    return pathlib.Path.home() / "AIChatRecords"


def read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def load_jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in read_text(path).splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def slugify(value: str) -> str:
    value = re.sub(r"[^\w.-]+", "-", value, flags=re.UNICODE).strip("-")
    return value or "session"


def short_text(value: str, limit: int = 80) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def format_timestamp(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    except ValueError:
        return value


def to_iso_from_epoch(seconds: float) -> str:
    return dt.datetime.fromtimestamp(seconds, tz=dt.timezone.utc).isoformat()


def json_pretty(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def parse_json_maybe(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def clean_meta(values: list[str | None]) -> list[str]:
    return [value for value in values if value]


def text_block(title: str, body: str) -> Block:
    return Block(kind="text", title=title, body=body)


def json_block(title: str, value: Any) -> Block:
    return Block(kind="json", title=title, body=json_pretty(value), language="json")


def tool_block(title: str, payload: Any) -> Block:
    if isinstance(payload, str):
        return Block(kind="tool", title=title, body=payload)
    return Block(kind="tool", title=title, body=json_pretty(payload), language="json")


def html_escape(text: str) -> str:
    return html.escape(text)


def strip_reply_marker(text: str) -> str:
    return re.sub(r"^\s*\[\[[^\]]+\]\]\s*", "", text.strip(), count=1)


def extract_wrapped_tag(text: str, tag: str) -> str | None:
    match = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", text, flags=re.S)
    if not match:
        return None
    return match.group(1).strip()


def strip_xmlish_tags(text: str) -> str:
    return re.sub(r"</?[\w_:-]+(?:\s+[^>]*)?>", "", text)


def extract_subagent_notification(text: str) -> tuple[str | None, Block | None]:
    wrapped = extract_wrapped_tag(text, "subagent_notification")
    if not wrapped:
        return None, None
    payload = parse_json_maybe(wrapped)
    if not isinstance(payload, dict):
        return strip_xmlish_tags(wrapped).strip(), None

    status = payload.get("status")
    completed = status.get("completed") if isinstance(status, dict) else None
    agent_name = payload.get("agent_nickname") or payload.get("agent_path") or "subagent"
    if isinstance(completed, str) and completed.strip():
        return f"Subagent {agent_name} completed:\n\n{completed.strip()}", json_block("Subagent Notification", payload)
    return f"Subagent {agent_name} notification", json_block("Subagent Notification", payload)


def split_sender_metadata(text: str) -> tuple[str | None, str]:
    match = re.match(
        r"^\s*Sender \(untrusted metadata\):\s*```json\s*(.*?)\s*```\s*(.*)$",
        text,
        flags=re.S,
    )
    if not match:
        return None, text.strip()
    sender = match.group(1).strip()
    body = match.group(2).strip()
    return sender, body


def beautify_message_text(source: str, role: str, text: str) -> tuple[str, list[Block]]:
    body = text.strip()
    extras: list[Block] = []
    if not body:
        return "", extras

    if role == "assistant":
        return strip_reply_marker(body), extras

    if role != "user":
        return body, extras

    sender_meta, body = split_sender_metadata(body)
    if sender_meta:
        extras.append(json_block("Sender Metadata", parse_json_maybe(sender_meta)))

    if source == "cursor":
        attached = extract_wrapped_tag(body, "attached_files")
        if attached:
            extras.append(text_block("Attached Files", attached))
        query = extract_wrapped_tag(body, "user_query")
        if query:
            return strip_xmlish_tags(query).strip(), extras

    if source == "codex":
        subagent_message, subagent_detail = extract_subagent_notification(body)
        if subagent_message:
            if subagent_detail:
                extras.append(subagent_detail)
            return subagent_message, extras

    cleaned = strip_xmlish_tags(body).strip()
    return cleaned or body, extras


def first_block_text(blocks: list[Block]) -> str:
    for block in blocks:
        if block.kind == "text" and block.body.strip():
            return block.body.strip()
    return ""


def sanitize_rel_path(raw_path: str) -> pathlib.Path:
    value = raw_path.strip().replace("\\", "/")
    if not value:
        return pathlib.Path("_unknown")
    value = re.sub(r"^[A-Za-z]:", lambda match: match.group(0)[0], value)
    value = value.lstrip("/")
    parts = [part for part in value.split("/") if part not in {"", ".", ".."}]
    if not parts:
        return pathlib.Path("_unknown")
    return pathlib.Path(*(slugify(part) for part in parts))
