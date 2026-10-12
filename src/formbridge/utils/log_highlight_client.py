"""Subprocess-backed log highlighting client."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from dataclasses import dataclass

from zmqruntime.process_launch import BackgroundProcessLaunchPolicy


@dataclass(frozen=True, slots=True)
class HighlightedSegmentDTO:
    start: int
    length: int
    color: tuple[int, int, int]
    bold: bool = False


class LogHighlightClient:
    """Own one serial highlighting subprocess for one log delegate."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen[str] | None = None
        self._state_lock = threading.Lock()
        self._io_lock = threading.Lock()
        self._closed = False

    def _ensure_process(self) -> subprocess.Popen:
        with self._state_lock:
            if self._closed:
                raise RuntimeError("Log highlight client is closed")
            if self._proc and self._proc.poll() is None:
                return self._proc

            launch_policy = BackgroundProcessLaunchPolicy.current()
            self._proc = subprocess.Popen(
                [
                    launch_policy.python_executable(sys.executable),
                    "-m",
                    "formbridge.utils.log_highlighter",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                **launch_policy.popen_arguments(),
            )
            return self._proc

    def parse_line(self, text: str) -> list[HighlightedSegmentDTO] | None:
        try:
            with self._io_lock:
                proc = self._ensure_process()
                if not proc.stdin or not proc.stdout:
                    return None

                payload = json.dumps({"text": text}, ensure_ascii=True)
                proc.stdin.write(payload + "\n")
                proc.stdin.flush()

                line = proc.stdout.readline()
                if not line:
                    return None
                data = json.loads(line)
                segments = []
                for seg in data.get("segments", []):
                    segments.append(
                        HighlightedSegmentDTO(
                            start=seg["start"],
                            length=seg["length"],
                            color=tuple(seg["color"]),
                            bold=seg.get("bold", False),
                        )
                    )
                return segments
        except Exception:
            return None

    def shutdown(self) -> None:
        """Close this client and interrupt an in-flight subprocess read."""

        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            proc = self._proc
            self._proc = None

        if not proc:
            return
        try:
            proc.terminate()
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        except ProcessLookupError:
            pass
