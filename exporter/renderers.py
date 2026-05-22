from __future__ import annotations

import html
import re

from .models import Block, SessionExport, Turn
from .utils import SOURCE_TITLES, format_timestamp


def _safe_link_href(raw_url: str) -> str:
    url = raw_url.strip()
    if re.match(r"^(https?|file)://", url, flags=re.I) or url.startswith(("/", "#", "./", "../")):
        return html.escape(url, quote=True)
    return "#"


def _render_inline_markdown(text: str) -> str:
    code_spans: list[str] = []

    def stash_code(match: re.Match[str]) -> str:
        code_spans.append(f"<code>{html.escape(match.group(1))}</code>")
        return f"\x00CODE{len(code_spans) - 1}\x00"

    escaped = re.sub(r"`([^`\n]+)`", stash_code, text)
    escaped = html.escape(escaped)

    def render_link(match: re.Match[str]) -> str:
        label = match.group(1)
        href = _safe_link_href(html.unescape(match.group(2)))
        return f"<a href='{href}'>{label}</a>"

    escaped = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", render_link, escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", escaped)
    for index, code_html in enumerate(code_spans):
        escaped = escaped.replace(html.escape(f"\x00CODE{index}\x00"), code_html)
    return escaped


def _render_paragraph(lines: list[str]) -> str:
    body = "<br />".join(_render_inline_markdown(line) for line in lines).strip()
    return f"<p>{body}</p>" if body else ""


def _render_list(items: list[str], ordered: bool) -> str:
    tag = "ol" if ordered else "ul"
    body = "".join(f"<li>{_render_inline_markdown(item)}</li>" for item in items)
    return f"<{tag}>{body}</{tag}>"


def _language_class(info: str) -> str:
    language = info.strip().split(maxsplit=1)[0] if info.strip() else ""
    if not re.match(r"^[A-Za-z0-9_.+-]+$", language):
        return ""
    return f" class='language-{html.escape(language, quote=True)}'"


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    return [cell.strip() for cell in stripped.split("|")]


def _is_table_separator(line: str) -> bool:
    cells = _split_table_row(line)
    return bool(cells) and all(re.match(r"^:?-{3,}:?$", cell.replace(" ", "")) for cell in cells)


def _render_table(header_line: str, separator_line: str, body_lines: list[str]) -> str:
    del separator_line
    headers = _split_table_row(header_line)
    rows = [_split_table_row(line) for line in body_lines]
    head_html = "".join(f"<th>{_render_inline_markdown(cell)}</th>" for cell in headers)
    row_html = []
    for row in rows:
        padded = row + [""] * max(0, len(headers) - len(row))
        row_html.append("<tr>" + "".join(f"<td>{_render_inline_markdown(cell)}</td>" for cell in padded[: len(headers)]) + "</tr>")
    return f"<table><thead><tr>{head_html}</tr></thead><tbody>{''.join(row_html)}</tbody></table>"


def render_markdown_html(text: str) -> str:
    lines = text.splitlines()
    html_parts: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    list_ordered = False
    quote_lines: list[str] = []
    in_code = False
    code_language = ""
    code_lines: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            html_parts.append(_render_paragraph(paragraph))
            paragraph.clear()

    def flush_list() -> None:
        if list_items:
            html_parts.append(_render_list(list_items, list_ordered))
            list_items.clear()

    def flush_quote() -> None:
        if quote_lines:
            html_parts.append(f"<blockquote>{_render_paragraph(quote_lines)}</blockquote>")
            quote_lines.clear()

    def flush_blocks() -> None:
        flush_paragraph()
        flush_list()
        flush_quote()

    index = 0
    while index < len(lines):
        line = lines[index]
        fence_match = re.match(r"^\s*```\s*(.*?)\s*$", line)
        if fence_match:
            if in_code:
                language_class = _language_class(code_language)
                code = html.escape("\n".join(code_lines))
                html_parts.append(f"<pre><code{language_class}>{code}\n</code></pre>")
                in_code = False
                code_language = ""
                code_lines.clear()
            else:
                flush_blocks()
                in_code = True
                code_language = fence_match.group(1)
            index += 1
            continue
        if in_code:
            code_lines.append(line)
            index += 1
            continue

        if not line.strip():
            flush_blocks()
            index += 1
            continue

        if index + 1 < len(lines) and "|" in line and _is_table_separator(lines[index + 1]):
            flush_blocks()
            body_lines: list[str] = []
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                body_lines.append(lines[index])
                index += 1
            html_parts.append(_render_table(line, lines[index - len(body_lines) - 1], body_lines))
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading_match:
            flush_blocks()
            level = min(len(heading_match.group(1)) + 2, 6)
            html_parts.append(f"<h{level}>{_render_inline_markdown(heading_match.group(2).strip())}</h{level}>")
            index += 1
            continue

        unordered_match = re.match(r"^\s*[-*+]\s+(.+)$", line)
        ordered_match = re.match(r"^\s*\d+[.)]\s+(.+)$", line)
        if unordered_match or ordered_match:
            flush_paragraph()
            flush_quote()
            ordered = ordered_match is not None
            if list_items and list_ordered != ordered:
                flush_list()
            list_ordered = ordered
            list_items.append((ordered_match or unordered_match).group(1).strip())
            index += 1
            continue

        quote_match = re.match(r"^\s*>\s?(.*)$", line)
        if quote_match:
            flush_paragraph()
            flush_list()
            quote_lines.append(quote_match.group(1))
            index += 1
            continue

        flush_list()
        flush_quote()
        paragraph.append(line)
        index += 1

    if in_code:
        language_class = _language_class(code_language)
        code = html.escape("\n".join(code_lines))
        html_parts.append(f"<pre><code{language_class}>{code}\n</code></pre>")
    flush_blocks()
    return "".join(html_parts) or "&nbsp;"


def _include_turn(turn: Turn, detail: bool) -> bool:
    if detail:
        return bool(turn.blocks or turn.detail_blocks)
    return turn.role in {"user", "assistant"} and bool(turn.blocks)


def _render_main_block_html(block: Block) -> str:
    if block.kind == "text":
        body = render_markdown_html(block.body)
        return f"<div class='message-body'>{body}</div>"
    language = f" data-language='{html.escape(block.language or '')}'" if block.language else ""
    return (
        f"<section class='part'><div class='part-title'>{html.escape(block.title)}</div>"
        f"<pre{language}>{html.escape(block.body)}</pre></section>"
    )


def _render_detail_block_html(block: Block, collapsed: bool = False) -> str:
    open_attr = "" if collapsed else " open"
    return (
        f"<details class='subpart'{open_attr}>"
        f"<summary>{html.escape(block.title)}</summary>"
        f"<pre>{html.escape(block.body)}</pre>"
        "</details>"
    )


def _role_class(role: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", role.lower())


def _is_technical_turn(turn: Turn) -> bool:
    return turn.role not in {"user", "assistant"}


def render_html(session: SessionExport, detail: bool) -> str:
    facts_html = "".join(
        "<div class='fact'>"
        f"<div class='fact-label'>{html.escape(label)}</div>"
        f"<div class='fact-value'>{html.escape(value)}</div>"
        "</div>"
        for label, value in session.facts
        if value
    )
    cards: list[str] = []
    for turn in session.turns:
        if not _include_turn(turn, detail):
            continue
        meta = []
        if turn.timestamp:
            meta.append(html.escape(format_timestamp(turn.timestamp)))
        meta.extend(html.escape(item) for item in turn.meta)
        meta_html = f"<div class='meta'>{' | '.join(meta)}</div>" if meta else ""
        blocks_html = "".join(_render_main_block_html(block) for block in turn.blocks)
        detail_html = ""
        if detail and turn.detail_blocks:
            collapse_details = _is_technical_turn(turn)
            detail_html = (
                "<div class='subparts'>"
                + "".join(_render_detail_block_html(block, collapsed=collapse_details) for block in turn.detail_blocks)
                + "</div>"
            )
        content_html = f"{meta_html}{blocks_html}{detail_html}"
        if detail and _is_technical_turn(turn):
            cards.append(
                f"<details class='entry technical role-{_role_class(turn.role)}'>"
                f"<summary><span class='badge'>{html.escape(turn.role)}</span>"
                f"<span class='summary-title'>{html.escape(turn.title)}</span>"
                f"<span class='summary-meta'>{' | '.join(meta)}</span></summary>"
                f"<div class='technical-body'>{content_html}</div></details>"
            )
        else:
            cards.append(
                f"<article class='entry role-{_role_class(turn.role)}'>"
                f"<div class='entry-head'><span class='badge'>{html.escape(turn.role)}</span></div>"
                f"<h2>{html.escape(turn.title)}</h2>"
                f"{content_html}</article>"
            )
    preview = html.escape(session.preview or "(empty)")
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{html.escape(session.source.title())} Session Export</title>
    <style>
      :root {{
        color-scheme: light;
	        --bg: #f6f7fb;
	        --card: #ffffff;
	        --border: #d7dde7;
	        --text: #1f2937;
	        --muted: #6b7280;
	        --user: #0f766e;
	        --assistant: #1d4ed8;
	        --developer: #4b5563;
	        --event: #7c2d12;
	        --context: #6d28d9;
	        --code-bg: #f2f5fa;
	      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        background: var(--bg);
        color: var(--text);
        font: 15px/1.7 "Segoe UI", "Microsoft YaHei", sans-serif;
      }}
      .wrap {{
        max-width: 1100px;
        margin: 0 auto;
        padding: 24px 16px 48px;
      }}
	      .summary, .entry {{
	        background: var(--card);
	        border: 1px solid var(--border);
	        border-radius: 10px;
	        box-shadow: 0 4px 16px rgba(15, 23, 42, 0.05);
	      }}
      .summary {{
        padding: 20px;
        margin-bottom: 18px;
      }}
      .summary h1 {{
        margin: 0 0 8px;
        font-size: 24px;
      }}
      .facts {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 10px;
        margin-top: 14px;
      }}
      .fact {{
        padding: 10px 12px;
        border: 1px solid var(--border);
        border-radius: 10px;
        background: #fbfcff;
      }}
      .fact-label {{
        font-size: 12px;
        color: var(--muted);
      }}
      .fact-value {{
        word-break: break-word;
      }}
	      .entry {{
	        padding: 16px 18px;
	        margin-bottom: 14px;
	      }}
	      details.entry {{
	        display: block;
	      }}
	      details.entry > summary {{
	        cursor: pointer;
	        list-style: none;
	        display: grid;
	        grid-template-columns: auto minmax(160px, 1fr) auto;
	        gap: 10px;
	        align-items: center;
	      }}
	      details.entry > summary::-webkit-details-marker {{
	        display: none;
	      }}
	      details.entry > summary::after {{
	        content: "Show";
	        color: var(--muted);
	        font-size: 12px;
	      }}
	      details.entry[open] > summary::after {{
	        content: "Hide";
	      }}
	      .technical {{
	        padding: 12px 14px;
	        background: #fffdfb;
	        border-color: #e5d7cf;
	      }}
	      .technical[open] > summary {{
	        margin-bottom: 10px;
	      }}
	      .summary-title {{
	        font-size: 15px;
	        font-weight: 700;
	      }}
	      .summary-meta {{
	        color: var(--muted);
	        font-size: 12px;
	        overflow: hidden;
	        text-overflow: ellipsis;
	        white-space: nowrap;
	      }}
	      .technical-body {{
	        padding-top: 2px;
	      }}
      .entry-head {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 6px;
      }}
      .entry h2 {{
        margin: 0 0 6px;
        font-size: 18px;
      }}
      .badge {{
        display: inline-block;
        padding: 3px 10px;
        border-radius: 999px;
        color: #fff;
        font-size: 12px;
        font-weight: 700;
        text-transform: capitalize;
      }}
	      .role-user .badge {{ background: var(--user); }}
	      .role-assistant .badge {{ background: var(--assistant); }}
	      .role-developer .badge {{ background: var(--developer); }}
	      .role-event .badge {{ background: var(--event); }}
	      .role-context .badge {{ background: var(--context); }}
      .meta {{
        color: var(--muted);
        font-size: 12px;
        margin-bottom: 10px;
      }}
	      .message-body {{
	        white-space: pre-wrap;
	        word-break: break-word;
	      }}
      .part, .subpart {{
        margin-top: 10px;
      }}
	      .subparts {{
	        margin-top: 14px;
	        padding-left: 14px;
	        border-left: 2px solid #e4e9f2;
	      }}
	      .subpart {{
	        border: 1px solid #e3e8f0;
	        border-radius: 8px;
	        background: #fbfcff;
	        padding: 8px 10px;
	      }}
	      .subpart + .subpart {{
	        margin-top: 8px;
	      }}
	      .subpart > summary {{
	        cursor: pointer;
	        color: var(--muted);
	        font-size: 12px;
	        font-weight: 700;
	        text-transform: uppercase;
	      }}
	      .subpart > pre {{
	        margin-top: 8px;
	      }}
	      .part-title, .subpart-title {{
	        font-size: 12px;
	        font-weight: 700;
        color: var(--muted);
        margin-bottom: 6px;
        text-transform: uppercase;
      }}
	      pre {{
	        white-space: pre-wrap;
	        word-break: break-word;
	        overflow-wrap: anywhere;
	        margin: 0;
	        padding: 12px;
	        max-height: 70vh;
	        overflow: auto;
	        border-radius: 8px;
	        background: var(--code-bg);
	        border: 1px solid #e7ebf3;
	        font: 12px/1.55 "Cascadia Code", Consolas, monospace;
	      }}
	      table {{
	        width: 100%;
	        border-collapse: collapse;
	        margin: 10px 0;
	        font-size: 14px;
	      }}
	      th, td {{
	        border: 1px solid #dbe3ef;
	        padding: 7px 9px;
	        text-align: left;
	        vertical-align: top;
	      }}
	      th {{
	        background: #eef3f8;
	        font-weight: 700;
	      }}
	      tr:nth-child(even) td {{
	        background: #fafcff;
	      }}
	      @media (max-width: 720px) {{
	        .wrap {{ padding: 12px 8px 32px; }}
	        .entry {{ padding: 12px; }}
	        details.entry > summary {{
	          grid-template-columns: auto 1fr;
	        }}
	        .summary-meta {{
	          grid-column: 2;
	        }}
	      }}
	    </style>
  </head>
  <body>
    <div class="wrap">
      <section class="summary">
        <h1>{html.escape(SOURCE_TITLES.get(session.source, session.source.title()))} Session Export</h1>
        <div>{preview}</div>
        <div class="facts">{facts_html}</div>
      </section>
      {''.join(cards)}
    </div>
  </body>
</html>
"""


def _render_main_block_md(block: Block) -> str:
    if block.kind == "text":
        return block.body
    language = block.language or ""
    return f"**{block.title}**\n\n```{language}\n{block.body}\n```"


def _render_detail_block_md(block: Block) -> str:
    language = block.language or ""
    if block.kind == "text":
        return f"### {block.title}\n\n```\n{block.body}\n```"
    return f"### {block.title}\n\n```{language}\n{block.body}\n```"


def render_md(session: SessionExport, detail: bool) -> str:
    sections = [f"# {SOURCE_TITLES.get(session.source, session.source.title())} Session Export", ""]
    sections.extend(f"- {label}: {value}" for label, value in session.facts if value)
    sections.extend(["", "## Preview", session.preview or "(empty)", ""])
    for turn in session.turns:
        if not _include_turn(turn, detail):
            continue
        sections.append(f"## {turn.title}")
        sections.append(f"- Role: {turn.role}")
        if turn.timestamp:
            sections.append(f"- Time: {format_timestamp(turn.timestamp)}")
        sections.extend(f"- {item}" for item in turn.meta)
        sections.append("")
        for block in turn.blocks:
            sections.append(_render_main_block_md(block))
            sections.append("")
        if detail:
            for block in turn.detail_blocks:
                sections.append(_render_detail_block_md(block))
                sections.append("")
    return "\n".join(sections).rstrip() + "\n"
