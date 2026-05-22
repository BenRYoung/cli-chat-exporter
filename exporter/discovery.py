from __future__ import annotations

import argparse
import glob
import os
import pathlib
from dataclasses import dataclass

from .utils import SOURCE_PATTERNS, is_windows, resolve_path, run_wsl


@dataclass(frozen=True)
class CandidatePath:
    path: pathlib.Path
    username: str | None = None


def detect_source(rows: list[dict], path: pathlib.Path) -> str:
    if rows:
        first = rows[0]
        row_type = first.get("type")
        if row_type == "session_meta":
            return "codex"
        if row_type == "session":
            return "openclaw"
        if row_type == "message" and isinstance(first.get("message"), dict):
            return "openclaw"
        if first.get("role") and isinstance(first.get("message"), dict):
            return "cursor"

    posix = path.as_posix()
    if "/.codex/sessions/" in posix:
        return "codex"
    if "/.openclaw/agents/" in posix:
        return "openclaw"
    if "/.cursor/projects/" in posix:
        return "cursor"
    raise SystemExit(f"Could not detect session source for {path}")


def expand_pattern(pattern: str, platform: str) -> str:
    if is_windows():
        home = run_wsl(platform, 'printf %s "$HOME"')
        return pattern.replace("~", home, 1)
    return os.path.expanduser(pattern)


def regular_user_homes() -> list[tuple[str, pathlib.Path]]:
    import pwd

    homes: dict[str, pathlib.Path] = {}
    for entry in pwd.getpwall():
        if entry.pw_uid < 1000 and entry.pw_name != "root":
            continue
        home = pathlib.Path(entry.pw_dir)
        if not home.is_absolute() or not home.exists():
            continue
        homes[entry.pw_name] = home
    return sorted(homes.items(), key=lambda item: (item[0] != "root", item[0]))


def home_for_user(username: str) -> pathlib.Path:
    import pwd

    try:
        entry = pwd.getpwnam(username)
    except KeyError as exc:
        raise SystemExit(f"User not found: {username}") from exc
    home = pathlib.Path(entry.pw_dir)
    if not home.is_absolute() or not home.exists():
        raise SystemExit(f"Home directory not found for user {username}: {home}")
    return home


def expand_pattern_for_home(pattern: str, home: pathlib.Path) -> str:
    if pattern.startswith("~/"):
        return str(home / pattern[2:])
    return pattern.replace("~", str(home), 1)


def find_candidate_paths(args: argparse.Namespace) -> list[CandidatePath]:
    selected_user = str(getattr(args, "user", "all") or "all")
    home_override = getattr(args, "home_override", None)
    if args.session_file:
        path = resolve_path(args.session_file, args.platform)
        if not path.exists():
            raise SystemExit(f"Session file not found: {path}")
        username = None if selected_user == "all" else selected_user
        return [CandidatePath(path, username)]

    sources = list(SOURCE_PATTERNS) if args.source in {"all", "auto"} else [args.source]
    candidates: list[CandidatePath] = []
    if home_override:
        home = pathlib.Path(home_override).expanduser()
        username = None if selected_user in {"", "all"} else selected_user
        for source in sources:
            pattern = expand_pattern_for_home(SOURCE_PATTERNS[source], home)
            for raw in glob.glob(pattern):
                path = pathlib.Path(raw)
                if path.is_file():
                    candidates.append(CandidatePath(path, username))
    elif selected_user:
        if is_windows():
            raise SystemExit("--user is only supported from Linux/WSL paths.")
        user_homes = regular_user_homes() if selected_user == "all" else [(selected_user, home_for_user(selected_user))]
        for username, home in user_homes:
            for source in sources:
                pattern = expand_pattern_for_home(SOURCE_PATTERNS[source], home)
                for raw in glob.glob(pattern):
                    path = pathlib.Path(raw)
                    if path.is_file():
                        candidates.append(CandidatePath(path, username))
    else:
        for source in sources:
            for raw in glob.glob(expand_pattern(SOURCE_PATTERNS[source], args.platform)):
                path = pathlib.Path(raw)
                if path.is_file():
                    candidates.append(CandidatePath(path))

    if args.session_id:
        candidates = [
            candidate
            for candidate in candidates
            if args.session_id in candidate.path.name or candidate.path.stem == args.session_id
        ]
        if not candidates:
            raise SystemExit(f"No session file matched session id: {args.session_id}")
        if len(candidates) > 1:
            preview = "\n".join(str(candidate.path) for candidate in candidates[:10])
            raise SystemExit(f"Multiple session files matched session id {args.session_id}:\n{preview}")

    if not candidates and getattr(args, "fail_on_no_sessions", True):
        raise SystemExit("No session files found for the requested source(s).")

    return sorted(candidates, key=lambda item: item.path.stat().st_mtime, reverse=True)
