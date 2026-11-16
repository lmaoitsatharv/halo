"""Scrolling a page should scroll the page.

Qt lets a slider, dropdown or number box take the mouse wheel whenever the pointer passes over it,
so scrolling down Settings quietly changed whatever the pointer crossed. The guard lets these
controls take the wheel only once they have been clicked (or tabbed to); otherwise the wheel goes
to the page that holds them, and over a control with no page to scroll it does nothing at all.
"""
from PySide6.QtCore import QObject, QEvent, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (QAbstractScrollArea, QAbstractSlider, QAbstractSpinBox, QApplication, QComboBox,
                               QScrollBar)


GUARDED = (QAbstractSlider, QComboBox, QAbstractSpinBox)


def guarded(widget):
    return isinstance(widget, GUARDED) and not isinstance(widget, QScrollBar)


class WheelGuard(QObject):
    """An application-wide event filter. Install once; it ends with its parent."""

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QEvent.Type.Polish and guarded(obj):
            # The wheel must never hand these controls the focus by itself (a click or Tab still does).
            if obj.focusPolicy() == Qt.FocusPolicy.WheelFocus:
                obj.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        elif kind == QEvent.Type.Wheel and guarded(obj) and not obj.hasFocus():
            page = obj.parentWidget()
            while page is not None and not isinstance(page, QAbstractScrollArea):
                page = page.parentWidget()
            if page is not None:
                viewport = page.viewport()
                at = event.globalPosition()
                forwarded = QWheelEvent(viewport.mapFromGlobal(at), at, event.pixelDelta(), event.angleDelta(),
                                        event.buttons(), event.modifiers(), event.phase(), event.inverted(),
                                        event.source())
                QApplication.sendEvent(viewport, forwarded)
            return True
        return False


def install(parent):
    """Guard every control in the application; the guard is removed when parent is deleted."""
    guard = WheelGuard(parent)
    QApplication.instance().installEventFilter(guard)
    return guard
