"""The wall runs up to the window's top edge; Windows' minimise, maximise and close keys stay, over the wall.

Qt 6.9+ can expand a window's client area into its title bar (Qt::ExpandedClientAreaHint, the same
value as MaximizeUsingFullscreenGeometryHint). On Windows, Qt then draws the title strip itself, on a
layered child window: with NoTitleBarBackgroundHint it leaves the strip clear, and without
WindowTitleHint it draws only the three keys, never the icon or title text. The taskbar and Alt+Tab
still use the window title. Presses on the strip that no widget accepts become title-bar drags.
"""
import ctypes
from ctypes import wintypes
import math
import sys

from PySide6.QtCore import Qt

TITLE_STRIP = sys.platform == "win32"
EXPANDED = Qt.WindowType.MaximizeUsingFullscreenGeometryHint
WORKSPACE_FLAGS = (Qt.WindowType.Window | Qt.WindowType.CustomizeWindowHint | Qt.WindowType.WindowSystemMenuHint
                   | Qt.WindowType.WindowMinMaxButtonsHint | Qt.WindowType.WindowCloseButtonHint
                   | EXPANDED | Qt.WindowType.NoTitleBarBackgroundHint)
SM_CYCAPTION, SM_CYSIZEFRAME, SM_CXPADDEDBORDER = 4, 33, 92
FALLBACK = 32


def strip_height(widget):
    """How tall the strip holding the window keys is, in the widget's own (device-independent) pixels.

    Qt sizes the strip from the window's DPI: the caption height plus the resize border.
    """
    if not TITLE_STRIP:
        return 0
    try:
        user32 = ctypes.windll.user32
        handle = widget.windowHandle()
        dpi = user32.GetDpiForWindow(int(widget.winId())) if handle is not None else 0
        if not dpi:
            dpi = round(96 * widget.devicePixelRatioF())
        native = sum(user32.GetSystemMetricsForDpi(index, dpi)
                     for index in (SM_CYCAPTION, SM_CYSIZEFRAME, SM_CXPADDEDBORDER))
        if native <= 0:
            return FALLBACK
        return math.ceil(native / max(1., widget.devicePixelRatioF()))
    except (OSError, AttributeError):
        return FALLBACK


def redraw(widget):
    """Repaint the strip now, so the keys take the new light right after the wall changes.

    Qt draws the strip again on the window's next paint; asking Windows for one is enough.
    """
    if not TITLE_STRIP or widget.windowHandle() is None or not widget.windowFlags() & EXPANDED:
        return False
    try:
        RDW_INVALIDATE, RDW_UPDATENOW = 0x1, 0x100
        return bool(ctypes.windll.user32.RedrawWindow(int(widget.winId()), None, None, RDW_INVALIDATE | RDW_UPDATENOW))
    except (OSError, AttributeError):
        return False


# Windows still keeps its own fallback caption for this window and paints it, in the old "basic" look,
# straight over the wall in a few moments. handle_message stops each of them.
WM_SETTEXT, WM_SETICON, WM_NCACTIVATE = 0x000C, 0x0080, 0x0086
WM_NCLBUTTONDOWN, WM_NCLBUTTONUP, WM_NCLBUTTONDBLCLK = 0x00A1, 0x00A2, 0x00A3
HTSIZE, HTMINBUTTON, HTMAXBUTTON, HTCLOSE = 4, 8, 9, 20
KEY_HITS = (HTSIZE, HTMINBUTTON, HTMAXBUTTON, HTCLOSE)
GWL_STYLE, WS_VISIBLE = -16, 0x10000000
_api = {}


def _user32():
    if not _api:
        user32 = ctypes.windll.user32
        user32.DefWindowProcW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        user32.GetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int)
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t)
        user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        _api["user32"] = user32
    return _api["user32"]


def handle_message(address):
    """Look at one Windows message for the main window. Returns (handled, result) for nativeEvent.

    - Focus changes (WM_NCACTIVATE): Windows may not repaint its caption (lParam -1, as documented).
    - The three keys: Qt acts on the press itself, so Windows' own button tracking, which draws old
      buttons and then sends a second minimise or maximise, never starts.
    - A new title or icon: Windows updates it without drawing a caption, while the window is briefly
      marked not visible.
    """
    if not TITLE_STRIP or not address:
        return False, 0
    msg = wintypes.MSG.from_address(int(address))
    message = msg.message
    if message == WM_NCACTIVATE:
        return True, _user32().DefWindowProcW(msg.hWnd, message, msg.wParam, -1)
    if message in (WM_NCLBUTTONDOWN, WM_NCLBUTTONUP, WM_NCLBUTTONDBLCLK) and msg.wParam in KEY_HITS:
        return True, 0
    if message in (WM_SETTEXT, WM_SETICON):
        user32 = _user32()
        style = user32.GetWindowLongPtrW(msg.hWnd, GWL_STYLE)
        if not style & WS_VISIBLE:
            return False, 0
        user32.SetWindowLongPtrW(msg.hWnd, GWL_STYLE, style & ~WS_VISIBLE)
        try:
            result = user32.DefWindowProcW(msg.hWnd, message, msg.wParam, msg.lParam)
        finally:
            user32.SetWindowLongPtrW(msg.hWnd, GWL_STYLE, style)
        return True, result
    return False, 0
