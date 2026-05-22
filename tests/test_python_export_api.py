'''
Smoke tests for the reusable Python export API used by the npm wrapper.

Usage:
    python tests/test_python_export_api.py
'''

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from exporter.cli import ExportOptions, manifest_path_for_root, run_export
from exporter.discovery import find_candidate_paths


def write_jsonl(path: pathlib.Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    path.write_text(f"{text}\n", encoding="utf-8")


def codex_rows(session_id: str, follow_up: bool = False) -> list[dict]:
    rows = [
        {
            "type": "session_meta",
            "timestamp": "2026-05-13T00:00:00Z",
            "payload": {
                "id": session_id,
                "timestamp": "2026-05-13T00:00:00Z",
                "cwd": "/tmp/chat-manager-incremental",
            },
        },
        {
            "type": "response_item",
            "timestamp": "2026-05-13T00:00:01Z",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Initial request."}],
            },
        },
        {
            "type": "response_item",
            "timestamp": "2026-05-13T00:00:02Z",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Initial answer."}],
            },
        },
    ]
    if follow_up:
        rows.extend(
            [
                {
                    "type": "response_item",
                    "timestamp": "2026-05-13T00:05:01Z",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "Follow-up after resume."}],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-05-13T00:05:02Z",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "Updated answer after resume."}],
                    },
                },
            ]
        )
    return rows


def assert_source_all_maps_to_discovery_all() -> None:
    with tempfile.TemporaryDirectory() as raw_home:
        home = pathlib.Path(raw_home)
        codex_path = home / ".codex" / "sessions" / "2026" / "05" / "11" / "rollout-test.jsonl"
        cursor_path = home / ".cursor" / "projects" / "p" / "agent-transcripts" / "s" / "test.jsonl"
        openclaw_path = home / ".openclaw" / "agents" / "a" / "sessions" / "test.jsonl"
        for path in (codex_path, cursor_path, openclaw_path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n", encoding="utf-8")

        args = SimpleNamespace(
            session_file=None,
            session_id=None,
            source="all",
            user=None,
            platform="ubuntu",
            home_override=home,
        )
        candidates = find_candidate_paths(argparse.Namespace(**vars(args)))
        found = {candidate.path for candidate in candidates}
        assert found == {codex_path, cursor_path, openclaw_path}, found


def assert_run_export_api_returns_result_for_empty_scope() -> None:
    with tempfile.TemporaryDirectory() as raw_root:
        root = pathlib.Path(raw_root)
        options = ExportOptions(
            platform="ubuntu",
            source="codex",
            session_file=None,
            session_id=None,
            format="both",
            output=str(root / "out"),
            user=None,
            overwrite=False,
            fail_on_no_sessions=False,
            home_override=root / "empty_home",
        )
        result = run_export(options)
        assert result.output_root == root / "out"
        assert result.written_files == 0
        assert result.skipped_files == 0
        assert result.concise_exports == 0
        assert result.detail_exports == 0
        assert result.log_path.exists()


def assert_windows_codex_current_home_is_discovered() -> None:
    with tempfile.TemporaryDirectory() as raw_home:
        home = pathlib.Path(raw_home)
        session_path = home / ".codex" / "sessions" / "2026" / "05" / "22" / "windows-codex.jsonl"
        session_path.parent.mkdir(parents=True, exist_ok=True)
        session_path.write_text("{}\n", encoding="utf-8")

        args = SimpleNamespace(
            session_file=None,
            session_id=None,
            source="codex",
            user="tester",
            platform="ubuntu",
            home_override=None,
            fail_on_no_sessions=True,
        )

        with (
            patch("exporter.discovery.is_windows", return_value=True),
            patch("exporter.discovery.current_windows_user", return_value="tester"),
            patch("pathlib.Path.home", return_value=home),
        ):
            candidates = find_candidate_paths(argparse.Namespace(**vars(args)))

        found = [candidate.path for candidate in candidates]
        assert found == [session_path], found


def assert_incremental_export_updates_changed_outputs() -> None:
    session_id = "api-incremental-session"
    with tempfile.TemporaryDirectory() as raw_root:
        root = pathlib.Path(raw_root)
        session_path = root / "session.jsonl"
        output_root = root / "out"
        options = ExportOptions(
            platform="ubuntu",
            source="auto",
            session_file=str(session_path),
            session_id=None,
            format="both",
            output=str(output_root),
            user=None,
            overwrite=False,
            fail_on_no_sessions=True,
        )
        write_jsonl(session_path, codex_rows(session_id))
        first = run_export(options)
        assert first.written_files == 4
        assert first.updated_files == 0
        assert first.skipped_files == 0

        detail_md = output_root / f"{session_id}_detail.md"
        initial_detail = detail_md.read_text(encoding="utf-8")
        assert "Updated answer after resume." not in initial_detail

        write_jsonl(session_path, codex_rows(session_id, follow_up=True))
        second = run_export(options)
        assert second.written_files == 0
        assert second.updated_files == 4
        assert second.skipped_files == 0
        assert "Updated answer after resume." in detail_md.read_text(encoding="utf-8")

        third = run_export(options)
        assert third.written_files == 0
        assert third.updated_files == 0
        assert third.skipped_files == 4

        manifest_path_for_root(output_root).unlink()
        adopted = run_export(options)
        assert adopted.written_files == 0
        assert adopted.updated_files == 0
        assert adopted.skipped_files == 4

        detail_md.write_text("corrupted\n", encoding="utf-8")
        repaired = run_export(options)
        assert repaired.written_files == 0
        assert repaired.updated_files == 1
        assert repaired.skipped_files == 3
        assert "Updated answer after resume." in detail_md.read_text(encoding="utf-8")


def main() -> int:
    assert_source_all_maps_to_discovery_all()
    assert_run_export_api_returns_result_for_empty_scope()
    assert_windows_codex_current_home_is_discovered()
    assert_incremental_export_updates_changed_outputs()
    print("python export api tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
