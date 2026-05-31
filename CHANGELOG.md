# Changelog

## 0.3.1

- Added parser and diagnostic support for Codex goal metadata updates.
- Added parser and diagnostic support for Codex tool search metadata.
- Coalesced repeated Codex goal update heartbeats in detail exports to keep long-running session output manageable.
- Added regression coverage for Codex goal and tool search metadata drift.

## 0.3.0

- Added native Windows current-user discovery for Cursor session transcripts.
- Removed the legacy `--platform` / WSL path conversion flow from CLI exports.
- Hid spawned Python and service processes on Windows to avoid extra console windows.
- Stopped the background service automatically when npm removes or replaces package files.
- Added regression coverage for Windows Codex/Cursor discovery and Cursor Windows project path decoding.

## 0.2.2

- Added Windows support for Codex session discovery and export.
- Added regression coverage for Windows-style Codex session paths.
- Kept generated package archives out of the public checkout.

## 0.2.1

- Added parser support for newer Codex image generation and agent reasoning metadata.
- Added parser support for Cursor `tool_use` content parts.
- Suppressed repeated metadata drift warnings for confirmed Codex and Cursor record types.
- Added regression coverage for metadata drift parsing and diagnostics.
- Hardened scheduler tests against local timezone differences in GitHub Actions.

## 0.2.0

- Added manifest-backed incremental export detection based on source and output fingerprints.
- Updated changed or resumed sessions by atomically replacing stale exports.
- Added separate `Updated files` and `Skipped unchanged files` reporting.
- Added regression coverage for unchanged exports, resumed sessions, manifest adoption, and output repair.

## 0.1.0

Initial stable release.

- Added the `cce` npm CLI.
- Export current-user Codex, Cursor, and OpenClaw histories.
- Generate concise and detailed Markdown / HTML archives.
- Added local configuration with `cce config`.
- Added lightweight scheduled exports with `cce service`.
- Added `cce doctor` for runtime diagnostics.
- Kept the npm CLI scoped to the current local user.

## 0.1.0-alpha.1

- Public prerelease used to validate npm packaging and local installation.

## 0.1.0-alpha.0

- Initial prerelease.
