"""Reusable Qt sidebar widgets: a toggle bar, an expanded pane with placement controls, and
one placement button.

A sidebar is a pane with controls (arrows to move it, Float/Push to lift it over the content)
and a toggle bar that opens the pane. Every Qt host of a formbridge-shaped sidebar — Toad's
phone layout today, future bus-aware editors — draws the same three widgets over the same
small protocol family declared below. The host owns which sidebars exist, the placement
family they offer and how each pane's contents render; the widgets own only how a toggle
toggles, how controls apply the action family and how the pane arranges itself relative to
its edge.

Edge-aware placement: the pane's controls dock on the interior-facing side of the pane
(bottom of a bottom-edge pane, top of a top-edge pane, right of a left-edge pane, left of a
right-edge pane), decided by the edge the pane is currently on. The host passes a resolver
that reads the current placement from whichever layout it owns.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Protocol, runtime_checkable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from pyqt_reactive.widgets.fitted_text import ElidedLine


@runtime_checkable
class PlacementEdge(Protocol):
    """Where a pane sits: an edge of the workspace. The widgets only need to know which end
    of the pane is interior-facing and the arrow character for the toggle bar."""

    @classmethod
    def toggle_symbol(cls, collapsed: bool) -> str: ...


@runtime_checkable
class LeadingPlacementEdge(PlacementEdge, Protocol):
    """The pane sits at the near end of its axis (left, top): controls dock at the far end."""


@runtime_checkable
class Placement(Protocol):
    """One sidebar's current placement: which edge it's on, whether it floats."""

    side: type[PlacementEdge]
    floating: bool


class PlacementAction(Protocol):
    """One placement action (an arrow, Float/Push). The layout applies it; the family draws
    it through the control's set_* hooks."""

    @property
    def label(self) -> str: ...
    def apply(self, layout: object, identity: object) -> None: ...


class PlacementLayout(Protocol):
    """A placement store the host owns. The pane reads the current placement through `get`
    and passes itself on `apply` from each control."""

    def get(self, identity: object) -> Placement: ...


class SidebarControlsOwner(Protocol):
    """How the host builds a pane's controls. Yields one PlacementAction per control; the
    pane constructs one QtPlacementControl per action and arranges them. The matching
    `present_placement_controls` call updates each control's label/tooltip/visibility from
    the current layout."""

    def placement_actions(self) -> Iterable[PlacementAction]: ...
    def present_placement_controls(self, controls: Iterable["QtPlacementControl"],
                                   layout: PlacementLayout, identity: object) -> None: ...


class QtPlacementControl(QToolButton, metaclass=PyQtWidgetMeta):
    """One placement control as a Qt button: an arrow that moves the pane to its edge, or
    Float/Push. Pressing it applies the action to the shared layout, exactly as the Textual
    sibling does; the family owns what the press does and how the control reads."""

    def __init__(self, action: PlacementAction, layout: PlacementLayout,
                 identity: object, applied: Callable[[], None],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Keep this a child widget even when transiently reparented to None during
        # layout rearrangement. Without Qt.Widget, Qt-for-Android gives any parent-less
        # QWidget its own top-level QWindow + EGL surface; the second surface races
        # QtAndroidAccessibility::runInObjectContext() for the eglSurface() mutex and
        # trips the deadlock protector (SIGABRT a second after ApplicationActive).
        self.setWindowFlags(Qt.WindowType.Widget)
        self.action = action
        self._layout = layout
        self._identity = identity
        self._applied = applied
        self.setText(action.label)
        self.setAutoRaise(True)
        self.setMinimumHeight(36)
        self.clicked.connect(self._apply)

    def _apply(self) -> None:
        self.action.apply(self._layout, self._identity)
        self._applied()

    def set_shown(self, shown: bool) -> None:
        self.setVisible(shown)

    def set_label(self, label: str) -> None:
        self.setText(label)

    def set_tooltip(self, tooltip: str) -> None:
        self.setToolTip(tooltip)


class SidebarPane(QWidget):
    """A sidebar's expanded pane: the placement controls over or under its content, depending
    on the edge the pane is on. Controls dock on the pane's interior-facing side so they stay
    adjacent to the content and away from the workspace wall:

      - leading edge (left, top): controls at the TRAILING end (bottom of a top-edge pane,
        right of a left-edge pane).
      - trailing edge (right, bottom): controls at the LEADING end (top of a bottom-edge
        pane, left of a right-edge pane).

    Axis follows the edge too: horizontal pane (top/bottom edge) → controls in a row at the
    far edge; vertical pane (left/right edge) → controls in a column at the far edge.
    """

    def __init__(self, layout: PlacementLayout, identity: object,
                 content: QWidget, owner: SidebarControlsOwner, *,
                 applied: Callable[[], None],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self._layout = layout
        self._identity = identity
        self._owner = owner
        self.content = content
        self._controls = [
            QtPlacementControl(action, layout, identity, applied, parent=self)
            for action in owner.placement_actions()
        ]
        # The pane's layout is rebuilt on every present() because the edge may have changed.
        # No widgets are destroyed; they are re-parented into the new axis+order.
        self._column: QVBoxLayout | None = None
        self._row: QHBoxLayout | None = None
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)
        self._apply_layout_for(None)

    def present(self) -> None:
        placement = self._layout.get(self._identity)
        self._apply_layout_for(placement)
        self._owner.present_placement_controls(self._controls, self._layout, self._identity)

    def _apply_layout_for(self, placement: Placement | None) -> None:
        """Arrange content and controls for the current edge; controls always face the
        interior of the workspace."""
        # Remove children from any existing arrangement; they are re-added below.
        for child in (self.content, *self._controls):
            child.setParent(self)
        while self._outer.count():
            self._outer.takeAt(0)
        axis_horizontal = self._is_horizontal_axis(placement)
        controls_leading = self._controls_leading(placement)
        if axis_horizontal:
            band: QHBoxLayout | QVBoxLayout = QHBoxLayout()
        else:
            band = QVBoxLayout()
        band.setContentsMargins(2, 2, 2, 2)
        band.setSpacing(2)
        for control in self._controls:
            band.addWidget(control)
        band.addStretch(1)
        if controls_leading:
            self._outer.addLayout(band)
            self._outer.addWidget(self.content, 1)
        else:
            self._outer.addWidget(self.content, 1)
            self._outer.addLayout(band)

    @staticmethod
    def _is_horizontal_axis(placement: Placement | None) -> bool:
        """Top/bottom edges run the pane horizontally (content laid out on a row); left/right
        run vertically. Floating always uses a horizontal strip over the content."""
        if placement is None or placement.floating:
            return True
        return placement.side.__name__.startswith(("Top", "Bottom"))

    @staticmethod
    def _controls_leading(placement: Placement | None) -> bool:
        """Controls sit on the pane's interior-facing side. On a trailing edge (right,
        bottom) the pane's leading end IS the interior, so controls go first. On a leading
        edge (left, top) controls go last. Floating defaults to leading (top of the overlay
        strip), matching the Textual overlay layout."""
        if placement is None or placement.floating:
            return True
        return isinstance(placement.side, type) and any(
            base.__name__ in {"TrailingSidebarEdge", "TrailingPlacementEdge"}
            for base in placement.side.__mro__
        )


class SidebarToggle(QWidget):
    """A sidebar's bar: an arrow and the pane's heading, nothing else. A press shows or hides
    the pane; the arrow points the way the pane opens."""

    def __init__(self, layout: PlacementLayout, identity: object, *,
                 heading: Callable[[], str], shown: Callable[[], bool],
                 toggled: Callable[[], None],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self._layout = layout
        self._identity = identity
        self._heading = heading
        self._shown = shown
        self._toggled = toggled
        self.setMinimumHeight(40)
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(4)
        self._left = QLabel(self)
        self._right = QLabel(self)
        self._title = ElidedLine("")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self._left)
        row.addWidget(self._title, 1)
        row.addWidget(self._right)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            self._toggled()
        else:
            super().mousePressEvent(event)

    def present(self) -> None:
        placement = self._layout.get(self._identity)
        shown = self._shown()
        heading = self._heading()
        arrow = placement.side.toggle_symbol(not shown)
        self._left.setText(arrow)
        self._right.setText(arrow)
        self._title.setText(heading)
        self.setToolTip(("Hide " if shown else "Show ") + heading)
