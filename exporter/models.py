from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Block:
    kind: str
    title: str
    body: str
    language: str | None = None


@dataclass
class Turn:
    role: str
    title: str
    timestamp: str | None
    meta: list[str] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    detail_blocks: list[Block] = field(default_factory=list)


@dataclass
class SessionExport:
    source: str
    session_id: str
    started_at: str | None
    project_path: str
    preview: str
    facts: list[tuple[str, str]]
    turns: list[Turn]
