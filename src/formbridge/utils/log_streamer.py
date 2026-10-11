"""Stream log file lines as JSONL chunks for UI consumption."""

import argparse
import json
import sys
from collections import deque
from pathlib import Path

from formbridge.utils.log_highlighter import build_log_line_html

def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def tail_lines(path: Path, max_lines: int) -> list[str]:
    if max_lines <= 0:
        return []

    buf: deque[str] = deque(maxlen=max_lines)
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            buf.append(line.rstrip("\n"))
    return list(buf)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--tail-lines", type=int, default=100_000)
    parser.add_argument("--chunk-lines", type=int, default=1000)
    parser.add_argument("--html", action="store_true")
    args = parser.parse_args()

    log_path = Path(args.path)
    try:
        lines = tail_lines(log_path, args.tail_lines)
        chunk: list = []
        for line in lines:
            if args.html:
                chunk.append({"text": line, "html": build_log_line_html(line)})
            else:
                chunk.append(line)
            if len(chunk) >= args.chunk_lines:
                emit({"type": "chunk", "lines": chunk})
                chunk = []

        if chunk:
            emit({"type": "chunk", "lines": chunk})

        emit({"type": "done"})
        return 0
    except Exception as exc:
        sys.stderr.write(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
