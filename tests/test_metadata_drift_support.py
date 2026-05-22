'''
验证 Codex 与 Cursor 新 metadata 类型的解析与诊断支持。

用法：
    /home/shrimp/softEngine/miniconda3/envs/Skills/bin/python \
        tests/test_metadata_drift_support.py
'''

from __future__ import annotations

import json
import pathlib
import sys
import tempfile

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from exporter.diagnostics import diagnose_session
from exporter.parsers import normalize_session
from exporter.renderers import render_md


def write_jsonl(path: pathlib.Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    path.write_text(f"{text}\n", encoding="utf-8")


def assert_codex_image_and_reasoning_are_supported() -> None:
    image_payload = "a" * 2048
    rows = [
        {
            "type": "session_meta",
            "timestamp": "2026-05-20T00:00:00Z",
            "payload": {
                "id": "codex-new-metadata",
                "timestamp": "2026-05-20T00:00:00Z",
                "cwd": "/tmp/chat-manager-metadata",
            },
        },
        {
            "type": "response_item",
            "timestamp": "2026-05-20T00:00:01Z",
            "payload": {
                "type": "image_generation_call",
                "id": "ig_test",
                "result": image_payload,
            },
        },
        {
            "type": "event_msg",
            "timestamp": "2026-05-20T00:00:02Z",
            "payload": {
                "type": "image_generation_end",
                "call_id": "ig_test",
                "result": image_payload,
            },
        },
        {
            "type": "event_msg",
            "timestamp": "2026-05-20T00:00:03Z",
            "payload": {"type": "agent_reasoning", "text": "正在分析图片生成结果。"},
        },
        {
            "type": "event_msg",
            "timestamp": "2026-05-20T00:00:04Z",
            "payload": {"type": "thread_rolled_back", "num_turns": 1},
        },
        {
            "type": "event_msg",
            "timestamp": "2026-05-20T00:00:05Z",
            "payload": {"type": "item_completed", "item": {"text": "任务完成"}},
        },
        {
            "type": "response_item",
            "timestamp": "2026-05-20T00:00:06Z",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Image ready."}],
            },
        },
    ]
    with tempfile.TemporaryDirectory() as raw_root:
        session_path = pathlib.Path(raw_root) / "codex.jsonl"
        write_jsonl(session_path, rows)
        session = normalize_session("codex", session_path, rows)
        issues = diagnose_session("codex", session_path, rows, session)
        unknown_issues = [issue.short() for issue in issues if issue.reason.startswith("unknown")]
        assert not unknown_issues, unknown_issues
        detail_md = render_md(session, detail=True)
        assert "Image Generation" in detail_md
        assert "Agent Reasoning" in detail_md
        assert "2048 characters" in detail_md
        assert image_payload not in detail_md


def assert_cursor_tool_use_is_supported() -> None:
    rows = [
        {
            "role": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "SwitchMode",
                        "input": {"target_mode_id": "plan"},
                    },
                    {"type": "text", "text": "Done."},
                ]
            },
        }
    ]
    with tempfile.TemporaryDirectory() as raw_root:
        session_path = pathlib.Path(raw_root) / "cursor.jsonl"
        write_jsonl(session_path, rows)
        session = normalize_session("cursor", session_path, rows)
        issues = diagnose_session("cursor", session_path, rows, session)
        unknown_issues = [issue.short() for issue in issues if issue.reason.startswith("unknown")]
        assert not unknown_issues, unknown_issues
        detail_md = render_md(session, detail=True)
        assert "Tool Use: SwitchMode" in detail_md
        assert "target_mode_id" in detail_md


def main() -> int:
    assert_codex_image_and_reasoning_are_supported()
    assert_cursor_tool_use_is_supported()
    print("metadata drift support tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
