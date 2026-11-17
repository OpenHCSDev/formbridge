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

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QPainter, QPalette
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from pyqt_reactive.widgets.fitted_text import ElidedLine


@runtime_checkable
class PlacementEdge(Protocol):
    """Where a pane sits: an edge of the workspace. The widgets only need to know which end
    of the pane is interior-facing, the arrow character for the toggle bar, and how far the
    toggle's heading is rotated so it reads along the bar."""

    @classmethod
    def toggle_symbol(cls, collapsed: bool) -> str: ...

    @classmethod
    def title_rotation_degrees(cls) -> int: ...


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
    """A sidebar's expanded pane: content fills the pane and the placement controls sit in a
    horizontal row at the bottom, regardless of the edge the pane is on. A row keeps the
    controls compact on a narrow side-edge pane where a vertical stack would eat screen."""

    def __init__(self, layout: PlacementLayout, identity: object,
                 content: QWidget, owner: SidebarControlsOwner, *,
                 applied: Callable[[], None],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        # Object-name is the hook the host's QSS selector reads — matching
        # `pyqt_reactive.theming.style_generator.generate_sidebar_pane_style()`'s
        # `QWidget#SidebarPane` selector — so the host can paint the pane with the
        # shared scheme's sidebar tone without the style bleeding into unrelated
        # QWidget children.
        self.setObjectName("SidebarPane")
        self._layout = layout
        self._identity = identity
        self._owner = owner
        self.content = content
        self._controls = [
            QtPlacementControl(action, layout, identity, applied, parent=self)
            for action in owner.placement_actions()
        ]
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)
        self._build_layout()

    def present(self) -> None:
        self._owner.present_placement_controls(self._controls, self._layout, self._identity)

    def _build_layout(self) -> None:
        """Content fills the pane; controls sit in a row at the bottom."""
        self.content.setParent(self)
        for control in self._controls:
            control.setParent(self)
        band = QHBoxLayout()
        band.setContentsMargins(2, 2, 2, 2)
        band.setSpacing(2)
        for control in self._controls:
            band.addWidget(control)
        band.addStretch(1)
        self._outer.addWidget(self.content, 1)
        self._outer.addLayout(band)


class _RotatableTitle(ElidedLine):
    """An elided one-line heading that can be painted rotated 90° either way, so the same
    widget reads correctly on a horizontal strip (top/bottom bar, rotation=0) or a vertical
    column (left/right bar, rotation=-90, book-spine convention).

    Rotation is a property on the title itself, not on the surrounding layout: a nominal
    axis each edge owns, read from the placement, not branched on the edge's identity."""

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self._rotation = 0

    def set_rotation(self, degrees: int) -> None:
        if self._rotation != degrees:
            self._rotation = degrees
            self.updateGeometry()
            self.update()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt virtual method name
        hint = super().sizeHint()
        return QSize(hint.height(), hint.width()) if self._rotation % 180 else hint

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt virtual method name
        hint = super().minimumSizeHint()
        return QSize(hint.height(), hint.width()) if self._rotation % 180 else hint

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt virtual method name
        if not self._rotation % 360:
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        # Qt's rotate() is clockwise; translate the origin to the corner the rotated text
        # starts from so a paint rectangle of (widget.height × widget.width) maps onto the
        # widget without clipping.
        if self._rotation % 360 == 270 or self._rotation == -90:
            painter.translate(0, self.height())
        else:  # 90 or -270
            painter.translate(self.width(), 0)
        painter.rotate(self._rotation)
        paint_rect = QRect(0, 0, self.height(), self.width())
        flags, text = self.drawn(paint_rect)
        painter.drawText(paint_rect, flags, text)


class SidebarToggle(QWidget):
    """A sidebar's bar: an arrow and the pane's heading, nothing else. A press shows or hides
    the pane; the arrow points the way the pane opens. On a vertical edge (left/right) the
    heading rotates to read along the bar's long axis and the arrows stack above and below
    it; on a horizontal edge they lie across a single row. The axis flip is driven by the
    placement edge's own `title_rotation_degrees()` — no per-edge branches here."""

    def __init__(self, layout: PlacementLayout, identity: object, *,
                 heading: Callable[[], str], shown: Callable[[], bool],
                 toggled: Callable[[], None],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        # Object-name hooks the host's QSS selector — matches
        # `pyqt_reactive.theming.style_generator.generate_sidebar_bar_style()`'s
        # `QWidget#SidebarToggle` — so the bar paints the scheme's header tone
        # instead of leaking its parent's colour.
        self.setObjectName("SidebarToggle")
        self._layout = layout
        self._identity = identity
        self._heading = heading
        self._shown = shown
        self._toggled = toggled
        self._left = QLabel(self)
        self._left.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._right = QLabel(self)
        self._right.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title = _RotatableTitle("")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Outer is always QVBoxLayout; a horizontal arrangement is a QHBoxLayout nested
        # inside it. Qt forbids replacing a widget's top-level layout, so the axis change
        # happens by rebuilding the outer layout's contents, not by swapping the layout
        # itself (mirroring SidebarPane._apply_layout_for).
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(4, 0, 4, 0)
        self._outer.setSpacing(4)
        self._current_rotation: int | None = None
        self._apply_orientation(None)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            self._toggled()
        else:
            super().mousePressEvent(event)

    def _apply_orientation(self, placement: Placement | None) -> None:
        """Rebuild the bar's arrangement for the placement's edge. `None` is the pre-placement
        default (initial build): horizontal, no rotation."""
        rotation = placement.side.title_rotation_degrees() if placement is not None else 0
        if rotation == self._current_rotation:
            return
        self._current_rotation = rotation
        self._title.set_rotation(rotation)
        # Reparent the three children back onto self; QLayout.takeAt() leaves the widgets
        # alive but detaches them from the layout, so nothing is destroyed here.
        for child in (self._left, self._title, self._right):
            child.setParent(self)
        while self._outer.count():
            item = self._outer.takeAt(0)
            sub = item.layout()
            if sub is not None:
                while sub.count():
                    sub.takeAt(0)
        if rotation:
            # Vertical bar — arrows stack above and below the rotated heading, and the
            # bar's cross-axis minimum moves from height to width so it draws as a strip.
            self._outer.addWidget(self._left)
            self._outer.addWidget(self._title, 1)
            self._outer.addWidget(self._right)
            self.setMinimumHeight(0)
            self.setMinimumWidth(40)
        else:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            row.addWidget(self._left)
            row.addWidget(self._title, 1)
            row.addWidget(self._right)
            self._outer.addLayout(row)
            self.setMinimumWidth(0)
            self.setMinimumHeight(40)

    def present(self) -> None:
        placement = self._layout.get(self._identity)
        self._apply_orientation(placement)
        shown = self._shown()
        heading = self._heading()
        arrow = placement.side.toggle_symbol(not shown)
        self._left.setText(arrow)
        self._right.setText(arrow)
        self._title.setText(heading)
        self.setToolTip(("Hide " if shown else "Show ") + heading)
