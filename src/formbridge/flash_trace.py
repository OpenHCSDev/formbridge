from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import (
    Any,
    Iterable,
)

logger = logging.getLogger("formbridge.flash_trace")


@dataclass(frozen=True, slots=True)
class FlashTraceRecord:
    """One bounded flash-pipeline diagnostic event."""

    timestamp: float
    event: str
    fields: tuple[tuple[str, str], ...]


class FlashTrace:
    """Process-local ring buffer with opt-in logger output for diagnostics."""

    _records: deque[FlashTraceRecord] = deque(maxlen=300)

    @classmethod
    def record(cls, event: str, **fields: Any) -> None:
        normalized_fields = tuple(
            (name, cls._format_value(value))
            for name, value in fields.items()
            if value is not None
        )
        cls._records.append(
            FlashTraceRecord(
                timestamp=time.time(),
                event=event,
                fields=normalized_fields,
            )
        )
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "event=%s %s",
                event,
                " ".join(f"{name}={value}" for name, value in normalized_fields),
            )

    @classmethod
    def recent(cls) -> tuple[FlashTraceRecord, ...]:
        """Return the recent flash trace ring buffer."""
        return tuple(cls._records)

    @classmethod
    def _format_value(cls, value: Any) -> str:
        if isinstance(value, (list, tuple, set, frozenset)):
            return cls._format_iterable(value)
        text = str(value).replace("\n", "\\n")
        if len(text) > 220:
            return f"{text[:217]}..."
        return text

    @classmethod
    def _format_iterable(cls, values: Iterable[Any]) -> str:
        formatted = [str(value) for value in values]
        if len(formatted) > 10:
            formatted = [*formatted[:10], f"...+{len(formatted) - 10}"]
        return "[" + ",".join(formatted) + "]"


def flash_trace(event: str, **fields: Any) -> None:
    """Record a flash diagnostic event."""
    FlashTrace.record(event, **fields)
