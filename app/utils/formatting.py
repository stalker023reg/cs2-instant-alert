"""
CS2 Instant Alert — Text Formatting Utilities.

Helpers for Telegram MarkdownV2, message templates, etc.
"""

from __future__ import annotations

import re


def escape_markdown_v2(text: str) -> str:
    """
    Escape special characters for Telegram MarkdownV2.

    Characters that must be escaped:
    _ * [ ] ( ) ~ ` > # + - = | { } . !
    """
    special_chars = r"_*[]()~`>#+-=|{}.!"
    return re.sub(f"([{re.escape(special_chars)}])", r"\\\1", text)


def bold(text: str) -> str:
    """Wrap text in MarkdownV2 bold."""
    return f"*{escape_markdown_v2(text)}*"


def italic(text: str) -> str:
    """Wrap text in MarkdownV2 italic."""
    return f"_{escape_markdown_v2(text)}_"


def code(text: str) -> str:
    """Wrap text in MarkdownV2 inline code."""
    return f"`{escape_markdown_v2(text)}`"


def code_block(text: str, language: str = "") -> str:
    """Wrap text in MarkdownV2 code block."""
    escaped = text.replace("`", "\\`")
    return f"```{language}\n{escaped}\n```"


def link(text: str, url: str) -> str:
    """Create a MarkdownV2 link."""
    escaped_text = escape_markdown_v2(text)
    # URL should NOT be escaped
    return f"[{escaped_text}]({url})"


def truncate(text: str, max_length: int = 4000, suffix: str = "...") -> str:
    """Truncate text to max length, respecting word boundaries."""
    if len(text) <= max_length:
        return text

    truncated = text[: max_length - len(suffix)]
    last_space = truncated.rfind(" ")
    if last_space > max_length * 0.8:
        truncated = truncated[:last_space]

    return truncated + suffix


def escape_html(text: str) -> str:
    """Escape special characters for Telegram HTML."""
    import html
    return html.escape(text)


def bold_html(text: str) -> str:
    """Wrap text in HTML bold."""
    return f"<b>{escape_html(text)}</b>"


def code_html(text: str) -> str:
    """Wrap text in HTML inline code."""
    return f"<code>{escape_html(text)}</code>"


# ─── Steam BB-Code → Telegram HTML ───

# Category icons for CS2 patch notes sections
_SECTION_ICONS: dict[str, str] = {
    "maps": "🗺",
    "gameplay": "🎮",
    "armory": "🎨",
    "misc": "⚙️",
    "premier": "🏆",
    "workshop": "🔧",
    "networking": "🌐",
    "audio": "🔊",
    "ui": "🖥",
    "rendering": "🖼",
    "anti-cheat": "🛡",
    "vac": "🛡",
    "overwatch": "👁",
    "security": "🔒",
    "server": "🖧",
    "linux": "🐧",
    "input": "🕹",
}


def _get_section_icon(section_name: str) -> str:
    """Return a contextual emoji for a patch notes section."""
    lower = section_name.lower().strip()
    for key, icon in _SECTION_ICONS.items():
        if key in lower:
            return icon
    return "📌"


def _classify_list_item(text: str) -> str:
    """Return an emoji prefix based on item content."""
    lower = text.lower().strip()
    if re.match(r'^(fix|fixed|resolved|corrected)', lower):
        return "🛠"
    if re.match(r'^(add|added|new|introduced)', lower):
        return "✅"
    if re.match(r'^(remove|removed|disabled)', lower):
        return "❌"
    if re.match(r'^(update|updated|changed|adjusted|improved)', lower):
        return "🔄"
    return "▸"


def format_steam_patchnotes_html(raw_text: str, max_length: int = 3500) -> str:
    """
    Convert Steam BB-code patch notes into clean Telegram HTML.

    Handles: [p]\\[ SECTION ][/p], [list], [*][p]...[/p][/*],
             [url=...]...[/url], [h3]...[/h3], [img]...[/img], nested lists.
    """
    text = raw_text

    # ── 1. Convert [url=...] tags to HTML links ──
    text = re.sub(
        r'\[url=?"?(.*?)"?\](.*?)\[/url\]',
        r'<a href="\1">\2</a>',
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # ── 2. Remove images (can't display in Telegram text) ──
    text = re.sub(r'\[img\].*?\[/img\]', '', text, flags=re.IGNORECASE | re.DOTALL)

    # ── 2.5. Remove empty paragraphs before section detection ──
    text = re.sub(r'\[p\]\s*\[/p\]', '', text)

    # ── 3. Extract section headers: [p]\[ SECTION ][/p] ──
    def _replace_section(m: re.Match) -> str:
        name = m.group(1).strip()
        icon = _get_section_icon(name)
        return f"\n\n{'─' * 18}\n{icon} <b>{name}</b>\n"

    # Pattern: optional [p][/p] then [p]\[ SECTION_NAME ][/p]
    # Steam uses: [p]\[ GAMEPLAY ][/p] with various escaping
    text = re.sub(
        r'(?:\[p\]\s*\[/p\]\s*)?'       # optional empty [p][/p] before
        r'\[p\]\s*\\?\[\s*'              # opening [p]\[ or [p][
        r'(.*?)'                          # section name
        r'\s*\]\\?\s*\[/p\]',            # closing ][/p] or ]\[/p]
        _replace_section,
        text,
    )

    # ── 4. Convert [h3] headings ──
    text = re.sub(r'\[h3\](.*?)\[/h3\]', r'\n<b>\1</b>\n', text, flags=re.IGNORECASE)

    # ── 4.5. Convert standalone [p]SubHeading[/p] (e.g., map names) ──
    # These are short standalone paragraphs that aren't section headers
    def _replace_subheading(m: re.Match) -> str:
        name = m.group(1).strip()
        if not name or len(name) > 60:
            return m.group(0)  # Not a subheading, leave as-is
        return f"\n<b>{name}</b>"

    text = re.sub(r'\[p\]([^[\]]{1,60})\[/p\](?=\s*\[list\])', _replace_subheading, text)

    # ── 5. Process list items ──
    def _replace_item(m: re.Match) -> str:
        content = m.group(1).strip()
        if not content:
            return ""
        icon = _classify_list_item(content)
        return f"  {icon} {content}\n"

    # Items with [p] wrappers: [*][p]text[/p][/*]
    text = re.sub(r'\[\*\]\[p\](.*?)\[/p\]\[/\*\]', _replace_item, text, flags=re.DOTALL)
    # Items without [p]: [*]text[/*]
    text = re.sub(r'\[\*\](.*?)\[/\*\]', _replace_item, text, flags=re.DOTALL)

    # ── 6. Clean remaining BB-code tags ──
    tags_to_strip = [
        'list', '/list', 'p', '/p', 'b', '/b', 'i', '/i',
        'u', '/u', 'spoiler', '/spoiler', 'noparse', '/noparse',
        'hr', 'table', '/table', 'tr', '/tr', 'td', '/td', 'th', '/th',
    ]
    for tag in tags_to_strip:
        text = text.replace(f'[{tag}]', '')

    # Remove any remaining [tag] or [tag=...] patterns
    text = re.sub(r'\[/?[a-zA-Z]+(?:=[^\]]*?)?\]', '', text)

    # Clean up escaped brackets from Steam
    text = text.replace('\\[', '[').replace('\\]', ']')

    # ── 7. Normalize whitespace ──
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)
    text = text.strip()

    # ── 8. Smart truncation at section boundary ──
    if len(text) > max_length:
        # Try to cut at a section divider
        divider = '─' * 18
        cut_pos = text.rfind(divider, 0, max_length)
        if cut_pos > max_length * 0.4:
            text = text[:cut_pos].rstrip()
        else:
            # Fall back to last newline
            cut_pos = text.rfind('\n', 0, max_length - 30)
            if cut_pos > 0:
                text = text[:cut_pos]
            else:
                text = text[:max_length - 30]
        text += "\n\n<i>…продолжение по ссылке ниже</i>"

    return text

