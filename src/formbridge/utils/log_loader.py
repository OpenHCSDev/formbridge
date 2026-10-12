"""Log file loader for subprocess use."""

import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        sys.stderr.write("Usage: python -m formbridge.utils.log_loader <path>\n")
        return 2

    log_path = Path(sys.argv[1])
    try:
        with open(log_path, encoding="utf-8", errors="replace") as handle:
            sys.stdout.write(handle.read())
        return 0
    except Exception as exc:
        sys.stderr.write(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
