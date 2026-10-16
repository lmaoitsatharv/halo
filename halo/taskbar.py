"""Let Windows reveal its taskbar above Halo's monitor-sized windows."""
import ctypes
from ctypes import wintypes
import logging
import sys


def allow_taskbar_reveal(window_id):
    """Mark a native Halo surface before it is shown, without shell changes.

    A monitor-sized frameless window can suppress an auto-hidden taskbar even
    when it passes input through. Windows documents NonRudeHWND as the opt-out
    from that fullscreen heuristic. Qt fullscreen layout and keyboard handling
    are unchanged. Apply it again when Qt recreates a native handle.
    https://learn.microsoft.com/windows/win32/api/shobjidl_core/nf-shobjidl_core-itaskbarlist2-markfullscreenwindow
    """
    if sys.platform != "win32" or not window_id:
        return False
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        set_property = user32.SetPropW
        set_property.argtypes = (wintypes.HWND, wintypes.LPCWSTR, wintypes.HANDLE)
        set_property.restype = wintypes.BOOL
        if set_property(int(window_id), "NonRudeHWND", 1):
            return True
        logging.warning("Couldn't mark Halo desktop overlay: %s", ctypes.get_last_error())
    except OSError:
        logging.exception("Couldn't access Windows desktop overlay policy")
    return False
