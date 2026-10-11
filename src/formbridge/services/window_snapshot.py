"""Window screenshot requests and the observation receipts that justify them.

The toolkit that renders the window owns capture and observation; this module
declares what a request asks for and what an observation recorded.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, fields
from enum import StrEnum
from math import isfinite

from python_introspect import project_dataclass
from zmqruntime.timeouts import OperationDeadline

from formbridge.flash_trace import FlashTraceRecord


@dataclass(frozen=True, slots=True)
class FlashPaintElement:
    """One source actually painted, in owning-window coordinates."""

    key: str
    source_token: str
    rect: tuple[int, int, int, int]
    rgba: tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class FlashPaintFrame:
    """Receipt emitted after the flash painter has ended."""

    window_identity: int
    painted_at_monotonic: float
    configured_maximum_alpha: int
    configured_flash_duration_s: float
    elements: tuple[FlashPaintElement, ...]

    @property
    def has_maximum_alpha(self) -> bool:
        return any(element.rgba[3] == self.configured_maximum_alpha for element in self.elements)


class FrameObservation(ABC):
    """What a capture waits for before it renders; the toolkit implements each kind."""


class NoObservation(FrameObservation):
    """Capture at once."""


class FlashObservation(FrameObservation):
    """Watch the window's flash painter."""


class RenderObservation(FrameObservation):
    """Wait for the window's native renderer to complete a frame."""


def _maximum_alpha_frame(frame: FlashPaintFrame) -> bool:
    return frame.has_maximum_alpha


def _no_frame(frame: FlashPaintFrame) -> bool:
    return False


def _validate_render_observation(observation: WindowVisualObservation) -> None:
    if observation.render_frame is None:
        raise ValueError("Render-complete capture has no native completion receipt.")
    frame = observation.render_frame
    if (
        frame.window_identity != observation.window_identity
        or not observation.started_at_monotonic
        <= frame.completed_at_monotonic
        <= observation.completed_at_monotonic
    ):
        raise ValueError("Native completion receipt is outside this window observation.")


def _validate_visual_observation(observation: WindowVisualObservation) -> None:
    pass


class WindowSnapshotFrameCondition(StrEnum):
    """Capture conditions evaluated from real renderer receipts (wire spelling)."""

    IMMEDIATE = ("immediate", NoObservation, _no_frame, False, False, _validate_visual_observation)
    FLASH_MAXIMUM_ALPHA = (
        "flash_maximum_alpha",
        FlashObservation,
        _maximum_alpha_frame,
        False,
        True,
        _validate_visual_observation,
    )
    NO_FLASH = ("no_flash", FlashObservation, _no_frame, True, False, _validate_visual_observation)
    RENDER_COMPLETE = (
        "render_complete",
        RenderObservation,
        _no_frame,
        False,
        False,
        _validate_render_observation,
    )

    def __new__(
        cls,
        value,
        observation,
        accepts_frame,
        accepts_quiet,
        requests_native_render,
        validate,
    ):
        member = str.__new__(cls, value)
        member._value_ = value
        member.observation = observation
        member._accepts_frame = accepts_frame
        member.accepts_quiet = accepts_quiet
        member.requests_native_render = requests_native_render
        member._validate = validate
        return member

    @property
    def observes(self) -> bool:
        return self.observation is not NoObservation

    def accepts_frame(self, frame: FlashPaintFrame) -> bool:
        return self._accepts_frame(frame)

    def accepts_timeout(self, starts: int, frames: int) -> bool:
        return self.accepts_quiet and starts == 0 and frames == 0

    def validate_observation(self, observation: WindowVisualObservation | None) -> None:
        if observation is None:
            if self.observes:
                raise ValueError("Observed capture has no frame-condition receipt.")
            return
        if observation.condition is not self:
            raise ValueError("Frame-condition receipt does not match the capture contract.")
        self._validate(observation)


@dataclass(frozen=True, slots=True)
class WindowRenderFrame:
    """Native renderer completion witnessed after this observation was armed."""

    window_identity: int
    renderer_identity: int
    completed_at_monotonic: float


@dataclass(frozen=True, slots=True)
class WindowVisualObservation:
    """Actual target-window activity during one armed observation."""

    condition: WindowSnapshotFrameCondition
    window_identity: int
    started_at_monotonic: float
    completed_at_monotonic: float
    configured_flash_duration_s: float
    baseline_inactive: bool
    flash_start_count: int
    painted_frame_count: int
    frame: FlashPaintFrame | None = None
    # Failure diagnostics reuse the existing bounded process-local trace ring.
    # These contextual records are not asserted to be target-window-only.
    trace: tuple[FlashTraceRecord, ...] = ()
    render_frame: WindowRenderFrame | None = None
    observation_budget_s: float | None = None
    operation_deadline: OperationDeadline | None = None


@dataclass(frozen=True, slots=True)
class WindowSnapshotObservationFailure:
    """Failed observation with its actual activity evidence preserved."""

    error: Exception
    observation: WindowVisualObservation


class WindowSnapshotCaptureScope(StrEnum):
    """Which pixels a snapshot captures (wire spelling); the toolkit renders them."""

    WIDGET = "widget"
    WINDOW = "window"


@dataclass(frozen=True, kw_only=True)
class WindowSnapshotCaptureSpec:
    """Requested destination, capture scope and frame condition."""

    output_dir_path: str
    capture_scope: WindowSnapshotCaptureScope = WindowSnapshotCaptureScope.WIDGET
    frame_condition: WindowSnapshotFrameCondition = WindowSnapshotFrameCondition.IMMEDIATE
    observation_timeout_s: float = 5.0

    def __post_init__(self) -> None:
        if not isfinite(self.observation_timeout_s) or not 0 < self.observation_timeout_s <= 30:
            raise ValueError("observation_timeout_s must be finite and in (0, 30].")

    def snapshot_operation_deadline(self) -> OperationDeadline | None:
        """Optional enclosing operation supplied by a product request owner."""
        return None

    @staticmethod
    def observation_phase_budget(remaining_seconds: float) -> float:
        """Reserve the other half of an operation for capture/reply delivery."""
        return remaining_seconds / 2

    def same_capture_contract(self, other: WindowSnapshotCaptureSpec) -> bool:
        """Return whether two snapshot carriers request the same capture."""

        return project_dataclass(WindowSnapshotCaptureSpec, self) == project_dataclass(
            WindowSnapshotCaptureSpec, other
        )

    def capture_fields(self) -> dict[str, object]:
        """Project every capture-owned field, excluding independent carrier fields."""
        return {
            declared.name: getattr(self, declared.name)
            for declared in fields(WindowSnapshotCaptureSpec)
        }
