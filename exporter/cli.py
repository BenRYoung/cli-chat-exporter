from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import tempfile
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

from .diagnostics import ParseIssue, diagnose_session
from .discovery import detect_source, find_candidate_paths
from .parsers import normalize_session
from .renderers import render_html, render_md
from .utils import default_output_root, load_jsonl, sanitize_rel_path


@dataclass(frozen=True)
class ExportOptions:
    platform: str = "ubuntu"
    source: str = "all"
    session_file: str | None = None
    session_id: str | None = None
    format: str = "both"
    output: str | None = None
    user: str | None = "all"
    overwrite: bool = False
    fail_on_no_sessions: bool = True
    home_override: pathlib.Path | None = None


@dataclass
class ExportResult:
    log_path: pathlib.Path
    output_root: pathlib.Path
    user: str | None
    outputs: list[pathlib.Path] = field(default_factory=list)
    updated_outputs: list[pathlib.Path] = field(default_factory=list)
    skipped_outputs: list[pathlib.Path] = field(default_factory=list)
    variant_counts: Counter[str] = field(default_factory=Counter)
    source_variant_counts: dict[str, Counter[str]] = field(default_factory=dict)
    issues: list[ParseIssue] = field(default_factory=list)

    @property
    def written_files(self) -> int:
        return len(self.outputs)

    @property
    def updated_files(self) -> int:
        return len(self.updated_outputs)

    @property
    def skipped_files(self) -> int:
        return len(self.skipped_outputs)

    @property
    def concise_exports(self) -> int:
        return self.variant_counts["concise"]

    @property
    def detail_exports(self) -> int:
        return self.variant_counts["detail"]


def export_root(output: str | None) -> pathlib.Path:
    return pathlib.Path(output).expanduser() if output else default_output_root()


def output_path_for_session(
    root: pathlib.Path,
    session,
    suffix: str,
    single_session: bool,
    username: str | None = None,
) -> pathlib.Path:
    if username:
        root = root / sanitize_rel_path(username)
    if single_session:
        return root / f"{session.session_id}{suffix}"
    return root / session.source / sanitize_rel_path(session.project_path) / f"{session.session_id}{suffix}"


@dataclass(frozen=True)
class OutputWriteResult:
    status: str
    old_size: int | None = None
    new_size: int = 0
    old_mtime_ns: int | None = None


@dataclass(frozen=True)
class FileFingerprint:
    size: int
    mtime_ns: int
    sha256: str

    def to_dict(self) -> dict[str, int | str]:
        return {
            "size": self.size,
            "mtime_ns": self.mtime_ns,
            "sha256": self.sha256,
        }


def fingerprint_file(path: pathlib.Path) -> FileFingerprint:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    stat = path.stat()
    return FileFingerprint(stat.st_size, stat.st_mtime_ns, digest.hexdigest())


def fingerprint_from_dict(value: object) -> FileFingerprint | None:
    if not isinstance(value, dict):
        return None
    try:
        return FileFingerprint(
            size=int(value["size"]),
            mtime_ns=int(value["mtime_ns"]),
            sha256=str(value["sha256"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def manifest_path_for_root(root: pathlib.Path) -> pathlib.Path:
    return root / ".chatmanager_export_manifest.json"


def load_manifest(root: pathlib.Path) -> dict:
    path = manifest_path_for_root(root)
    if not path.exists():
        return {"version": 1, "sessions": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "sessions": {}}
    if not isinstance(data, dict):
        return {"version": 1, "sessions": {}}
    sessions = data.get("sessions")
    if not isinstance(sessions, dict):
        data["sessions"] = {}
    data["version"] = 1
    return data


def save_manifest(root: pathlib.Path, manifest: dict) -> None:
    path = manifest_path_for_root(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temp_path = pathlib.Path(handle.name)
    try:
        with handle:
            handle.write(content)
        temp_path.replace(path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def manifest_key(username: str | None, session) -> str:
    parts = [
        username or "",
        session.source,
        session.project_path,
        session.session_id,
    ]
    return "\x1f".join(parts)


def output_fingerprints(paths: list[pathlib.Path]) -> dict[str, dict[str, int | str]]:
    return {str(path): fingerprint_file(path).to_dict() for path in paths}


def source_record(source_path: pathlib.Path, source_fingerprint: FileFingerprint) -> dict[str, int | str]:
    return {
        "path": str(source_path),
        **source_fingerprint.to_dict(),
    }


def manifest_source_matches(record: object, source_path: pathlib.Path, source_fingerprint: FileFingerprint) -> bool:
    if not isinstance(record, dict):
        return False
    source = record.get("source")
    if not isinstance(source, dict):
        return False
    saved = fingerprint_from_dict(source)
    return (
        saved == source_fingerprint
        and source.get("path") == str(source_path)
    )


def manifest_outputs_match(record: object, output_paths: list[pathlib.Path]) -> bool:
    if not isinstance(record, dict):
        return False
    outputs = record.get("outputs")
    if not isinstance(outputs, dict):
        return False
    for path in output_paths:
        saved = fingerprint_from_dict(outputs.get(str(path)))
        if saved is None or not path.exists():
            return False
        if fingerprint_file(path) != saved:
            return False
    return True


def existing_outputs_are_not_older_than_source(
    output_paths: list[pathlib.Path],
    source_fingerprint: FileFingerprint,
) -> bool:
    if not output_paths or any(not path.exists() for path in output_paths):
        return False
    return min(path.stat().st_mtime_ns for path in output_paths) >= source_fingerprint.mtime_ns


def write_output(path: pathlib.Path, content: str, overwrite: bool = False) -> OutputWriteResult:
    path.parent.mkdir(parents=True, exist_ok=True)
    content_bytes = content.encode("utf-8")
    existing_stat = path.stat() if path.exists() else None
    if existing_stat and not overwrite:
        old_size = existing_stat.st_size
        old_mtime_ns = existing_stat.st_mtime_ns
        if old_size == len(content_bytes):
            try:
                if path.read_text(encoding="utf-8") == content:
                    return OutputWriteResult(
                        "skipped",
                        old_size=old_size,
                        new_size=len(content_bytes),
                        old_mtime_ns=old_mtime_ns,
                    )
            except UnicodeDecodeError:
                pass
        status = "updated"
    else:
        status = "written"
    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temp_path = pathlib.Path(handle.name)
    try:
        with handle:
            handle.write(content)
        temp_path.replace(path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return OutputWriteResult(
        status,
        old_size=existing_stat.st_size if existing_stat else None,
        new_size=len(content_bytes),
        old_mtime_ns=existing_stat.st_mtime_ns if existing_stat else None,
    )


def render_and_write_output(
    log_path: pathlib.Path,
    issues: list[ParseIssue],
    source: str,
    session_path: pathlib.Path,
    output_path: pathlib.Path,
    render_content: Callable[[], str],
    overwrite: bool,
) -> str:
    try:
        content = render_content()
        write_result = write_output(output_path, content, overwrite=overwrite)
    except Exception as exc:
        issue = ParseIssue(
            source,
            session_path,
            "export failed",
            f"{type(exc).__name__}: {exc}; output={output_path}",
        )
        issues.append(issue)
        log_line(log_path, f"DIAGNOSTIC {issue.source}: {issue.reason}: {issue.detail} file={issue.path}")
        return "failed"
    if write_result.status == "written":
        log_line(log_path, f"Wrote: {output_path.resolve()}")
        return "written"
    if write_result.status == "updated":
        log_line(
            log_path,
            (
                f"Updated existing: {output_path.resolve()} "
                f"old_size={write_result.old_size} new_size={write_result.new_size} "
                f"old_mtime_ns={write_result.old_mtime_ns}"
            ),
        )
        return "updated"
    log_line(
        log_path,
        (
            f"Skipped unchanged: {output_path.resolve()} "
            f"size={write_result.old_size} mtime_ns={write_result.old_mtime_ns}"
        ),
    )
    return "skipped"


def log_root() -> pathlib.Path:
    env_log_root = os.environ.get("CCE_EXPORT_LOG_DIR")
    if env_log_root:
        return pathlib.Path(env_log_root).expanduser()
    return pathlib.Path(__file__).resolve().parents[1] / "export_logs"


def create_log_file() -> pathlib.Path:
    root = log_root()
    root.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return root / f"export_{timestamp}_{os.getpid()}.log"


def log_line(log_path: pathlib.Path, message: str) -> None:
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(message.rstrip() + "\n")


def source_hint(path: pathlib.Path, requested_source: str) -> str:
    if requested_source != "auto":
        return requested_source
    posix = path.as_posix()
    if "/.codex/sessions/" in posix:
        return "codex"
    if "/.cursor/projects/" in posix:
        return "cursor"
    if "/.openclaw/agents/" in posix:
        return "openclaw"
    return "unknown"


def ensure_output_permissions(root: pathlib.Path) -> None:
    if not root.exists():
        return
    try:
        root.chmod(0o777)
        for item in root.rglob("*"):
            if item.is_dir():
                item.chmod(0o777)
            elif item.is_file():
                item.chmod(0o666)
    except OSError:
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export Codex, OpenClaw, or Cursor session JSONL to self-contained HTML or Markdown."
    )
    parser.add_argument("--platform", default="ubuntu", help="Session storage varies among platforms")
    parser.add_argument(
        "--source",
        choices=("all", "auto", "codex", "openclaw", "cursor"),
        default="all",
        help="Session source. Defaults to all discovered sources.",
    )
    parser.add_argument("--session-file", help="Path to a session JSONL file")
    parser.add_argument("--session-id", help="Filter auto-discovered files by session id or file stem")
    parser.add_argument("--format", choices=("html", "md", "both"), default="both", help="Export format")
    parser.add_argument("--output", default=str(default_output_root()), help="Output root directory")
    parser.add_argument("--user", default="all", help="Local user to export, or 'all' for all regular local users.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing output files instead of skipping them.")
    return parser.parse_args()


def options_from_args(args: argparse.Namespace) -> ExportOptions:
    return ExportOptions(
        platform=args.platform,
        source=args.source,
        session_file=args.session_file,
        session_id=args.session_id,
        format=args.format,
        output=args.output,
        user=args.user,
        overwrite=args.overwrite,
    )


def namespace_from_options(options: ExportOptions) -> argparse.Namespace:
    return argparse.Namespace(
        platform=options.platform,
        source=options.source,
        session_file=options.session_file,
        session_id=options.session_id,
        format=options.format,
        output=options.output,
        user=options.user,
        overwrite=options.overwrite,
        fail_on_no_sessions=options.fail_on_no_sessions,
        home_override=options.home_override,
    )


def resolve_session_source(requested_source: str, single_session: bool, rows: list[dict], session_path: pathlib.Path) -> str:
    if requested_source not in {"all", "auto"} and single_session:
        return requested_source
    return detect_source(rows, session_path)


def run_export(options: ExportOptions) -> ExportResult:
    args = namespace_from_options(options)
    candidate_paths = find_candidate_paths(args)
    single_session = bool(options.session_file or options.session_id)
    root = export_root(options.output)
    log_path = create_log_file()
    manifest = load_manifest(root)
    manifest_sessions = manifest.setdefault("sessions", {})
    outputs: list[pathlib.Path] = []
    updated_outputs: list[pathlib.Path] = []
    skipped_outputs: list[pathlib.Path] = []
    variant_counts: Counter[str] = Counter()
    source_variant_counts: dict[str, Counter[str]] = defaultdict(Counter)
    issues: list[ParseIssue] = []
    log_line(log_path, f"Output root: {root}")
    log_line(log_path, f"User: {options.user}")
    log_line(log_path, f"Source: {options.source}")
    log_line(log_path, f"Format: {options.format}")
    log_line(log_path, f"Overwrite: {options.overwrite}")
    for candidate in candidate_paths:
        session_path = candidate.path
        log_line(log_path, f"Reading: {session_path}")
        try:
            rows = load_jsonl(session_path)
            if not rows:
                raise ValueError("empty session file")
            source = resolve_session_source(options.source, single_session, rows, session_path)
            session = normalize_session(source, session_path, rows)
        except Exception as exc:
            source = source_hint(session_path, options.source)
            issue = ParseIssue(source, session_path, "parse failed", f"{type(exc).__name__}: {exc}")
            issues.append(issue)
            log_line(log_path, f"DIAGNOSTIC {issue.source}: {issue.reason}: {issue.detail} file={issue.path}")
            continue
        session_issues = diagnose_session(source, session_path, rows, session)
        issues.extend(session_issues)
        for issue in session_issues:
            log_line(log_path, f"DIAGNOSTIC {issue.source}: {issue.reason}: {issue.detail} file={issue.path}")
        source_fingerprint = fingerprint_file(session_path)
        planned_outputs: dict[str, list[tuple[pathlib.Path, Callable[[], str]]]] = {}
        for variant, detail in (("concise", False), ("detail", True)):
            planned_outputs[variant] = []
            if options.format in {"html", "both"}:
                html_path = output_path_for_session(root, session, f"_{variant}.html", single_session, candidate.username)
                planned_outputs[variant].append((html_path, lambda detail=detail: render_html(session, detail=detail)))
            if options.format in {"md", "both"}:
                md_path = output_path_for_session(root, session, f"_{variant}.md", single_session, candidate.username)
                planned_outputs[variant].append((md_path, lambda detail=detail: render_md(session, detail=detail)))

        expected_paths = [output_path for items in planned_outputs.values() for output_path, _ in items]
        key = manifest_key(candidate.username, session)
        manifest_record = manifest_sessions.get(key)
        if (
            not options.overwrite
            and manifest_source_matches(manifest_record, session_path, source_fingerprint)
            and manifest_outputs_match(manifest_record, expected_paths)
        ):
            for output_path in expected_paths:
                skipped_outputs.append(output_path)
                log_line(log_path, f"Skipped unchanged by manifest: {output_path.resolve()}")
            for variant in planned_outputs:
                variant_counts[variant] += 1
                source_variant_counts[source][variant] += 1
            continue

        if (
            not options.overwrite
            and not manifest_record
            and existing_outputs_are_not_older_than_source(expected_paths, source_fingerprint)
        ):
            for output_path in expected_paths:
                skipped_outputs.append(output_path)
                log_line(log_path, f"Adopted unchanged existing: {output_path.resolve()}")
            manifest_sessions[key] = {
                "source": source_record(session_path, source_fingerprint),
                "outputs": output_fingerprints(expected_paths),
            }
            for variant in planned_outputs:
                variant_counts[variant] += 1
                source_variant_counts[source][variant] += 1
            continue

        session_had_failure = False
        for variant, rendered_output_callables in planned_outputs.items():
            rendered_outputs: list[tuple[pathlib.Path, str]] = []
            try:
                for output_path, render_content in rendered_output_callables:
                    rendered_outputs.append((output_path, render_content()))
            except Exception as exc:
                issue = ParseIssue(
                    source,
                    session_path,
                    "export failed",
                    f"{type(exc).__name__}: {exc}; variant={variant}",
                )
                issues.append(issue)
                log_line(log_path, f"DIAGNOSTIC {issue.source}: {issue.reason}: {issue.detail} file={issue.path}")
                session_had_failure = True
                continue

            for output_path, content in rendered_outputs:
                write_status = render_and_write_output(
                    log_path,
                    issues,
                    source,
                    session_path,
                    output_path,
                    lambda content=content: content,
                    options.overwrite,
                )
                if write_status == "written":
                    outputs.append(output_path)
                elif write_status == "updated":
                    updated_outputs.append(output_path)
                elif write_status == "skipped":
                    skipped_outputs.append(output_path)
                elif write_status == "failed":
                    session_had_failure = True
            variant_counts[variant] += 1
            source_variant_counts[source][variant] += 1

        if not session_had_failure and all(path.exists() for path in expected_paths):
            manifest_sessions[key] = {
                "source": source_record(session_path, source_fingerprint),
                "outputs": output_fingerprints(expected_paths),
            }

    try:
        save_manifest(root, manifest)
        ensure_output_permissions(root)
    except OSError as exc:
        log_line(log_path, f"WARNING permission update failed: {exc}")
        print(f"Warning: could not relax output permissions for {root}: {exc}")
    log_line(log_path, f"Output files: {len(outputs)}")
    log_line(log_path, f"Updated files: {len(updated_outputs)}")
    log_line(log_path, f"Skipped unchanged files: {len(skipped_outputs)}")
    log_line(log_path, f"Concise sessions: {variant_counts['concise']}")
    log_line(log_path, f"Detail sessions: {variant_counts['detail']}")
    return ExportResult(
        log_path=log_path,
        output_root=root,
        user=options.user,
        outputs=outputs,
        updated_outputs=updated_outputs,
        skipped_outputs=skipped_outputs,
        variant_counts=variant_counts,
        source_variant_counts=dict(source_variant_counts),
        issues=issues,
    )


def print_export_result(result: ExportResult) -> None:
    print(f"Export log: {result.log_path}")
    print(f"User: {result.user}")
    print(f"Output root: {result.output_root}")
    print(f"Concise exports: {result.concise_exports}")
    print(f"Detail exports: {result.detail_exports}")
    print(f"Written files: {result.written_files}")
    print(f"Updated files: {result.updated_files}")
    print(f"Skipped unchanged files: {result.skipped_files}")
    for source in sorted(result.source_variant_counts):
        counts = result.source_variant_counts[source]
        print(f"{source}: concise={counts['concise']}, detail={counts['detail']}")
    if result.issues:
        issues_by_source: dict[str, list[ParseIssue]] = defaultdict(list)
        for issue in result.issues:
            issues_by_source[issue.source].append(issue)
        for source in sorted(issues_by_source):
            sample = "; ".join(issue.short() for issue in issues_by_source[source][:3])
            warning = f"Warning: {source} metadata may have changed. Please review parser support. Evidence: {sample}"
            log_line(result.log_path, warning)
            print(warning)


def main() -> int:
    args = parse_args()
    result = run_export(options_from_args(args))
    print_export_result(result)
    return 0
