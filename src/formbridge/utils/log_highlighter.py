"""Subprocess log line highlighter (JSONL)."""

import json
import re
import sys


_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2},\d{3}")
_LOG_LEVEL_RE = re.compile(r"\b(ERROR|WARNING|INFO|DEBUG|CRITICAL)\b")
_LOGGER_NAME_RE = re.compile(r" - ([\w\.]+) - ")
_FILE_PATH_RE = re.compile(r"(?:/[\w\-\.]+)+\.py")
_PYTHON_STRING_RE = re.compile(r"[\"'](?:[^\"'\\]|\\.)*[\"']")
_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")


def parse_line(text: str) -> list[dict]:
    segments = []

    match = _TIMESTAMP_RE.match(text)
    if match:
        segments.append({"start": match.start(), "length": match.end() - match.start(), "color": (105, 105, 105)})

    for match in _LOG_LEVEL_RE.finditer(text):
        level = match.group(1)
        if level in ("ERROR", "CRITICAL"):
            color = (255, 85, 85)
        elif level == "WARNING":
            color = (255, 140, 0)
        else:
            color = (100, 160, 210)
        segments.append({"start": match.start(), "length": match.end() - match.start(), "color": color, "bold": True})

    for match in _LOGGER_NAME_RE.finditer(text):
        segments.append({"start": match.start(1), "length": match.end(1) - match.start(1), "color": (147, 112, 219)})

    for match in _FILE_PATH_RE.finditer(text):
        segments.append({"start": match.start(), "length": match.end() - match.start(), "color": (34, 139, 34)})

    for match in _PYTHON_STRING_RE.finditer(text):
        segments.append({"start": match.start(), "length": match.end() - match.start(), "color": (206, 145, 120)})

    for match in _NUMBER_RE.finditer(text):
        segments.append({"start": match.start(), "length": match.end() - match.start(), "color": (181, 206, 168)})

    return segments


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_log_line_html(text: str) -> str:
    """Render one line from the authoritative parsed highlight segments."""
    segments = sorted(parse_line(text), key=lambda segment: segment["start"])
    cursor = 0
    parts: list[str] = ['<span style="white-space: pre-wrap;">']
    text_len = len(text)

    for segment in segments:
        start = max(0, segment["start"])
        end = min(text_len, start + segment["length"])
        if end <= start or start < cursor:
            continue
        if start > cursor:
            parts.append(_escape_html(text[cursor:start]))

        red, green, blue = segment["color"]
        style = f"color: rgb({red},{green},{blue});"
        if segment.get("bold"):
            style += " font-weight: 700;"
        parts.append(
            f'<span style="{style}">{_escape_html(text[start:end])}</span>'
        )
        cursor = end

    if cursor < text_len:
        parts.append(_escape_html(text[cursor:]))

    parts.append("</span>")
    return "".join(parts)


def main() -> int:
    for line in sys.stdin:
        try:
            payload = json.loads(line)
            text = payload.get("text", "")
            segments = parse_line(text)
            sys.stdout.write(json.dumps({"segments": segments}, ensure_ascii=True) + "\n")
            sys.stdout.flush()
        except Exception as exc:
            sys.stderr.write(str(exc))
            sys.stderr.flush()
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
