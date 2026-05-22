# Privacy

CLI Chat Exporter is designed as a local archive tool.

## What It Reads

It scans supported local application history directories for the current user:

- Codex
- Cursor
- OpenClaw

## What It Writes

It writes Markdown and HTML exports to the configured output directory.

## What It Does Not Do

- It does not upload chat records.
- It does not request elevated privileges through the npm CLI.
- It does not read other users' home directories through the npm CLI.
- It does not write sudoers rules or system-wide services.

Detailed exports may contain sensitive metadata and tool payloads. Store them in a location you trust.
