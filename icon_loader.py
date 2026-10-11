"""Background loader for per-file icons and thumbnails (J01, A02).

Uses the shell's IShellItemImageFactory through ctypes, which returns the
same picture Explorer shows: thumbnails for images/videos and the real icon
for .exe/.lnk/.ico … at any size. All shell calls run in a worker thread;
only QImage (thread-safe) crosses back to the GUI thread.
"""

import ctypes
import logging
import queue
from ctypes import wintypes

from PySide6.QtCore import QCoreApplication, QObject, QThread, Signal
from PySide6.QtGui import QImage

log = logging.getLogger(__name__)

SIIGBF_ICONONLY = 0x4


class _GUID(ctypes.Structure):
    _fields_ = [
        ("d1", wintypes.DWORD),
        ("d2", wintypes.WORD),
        ("d3", wintypes.WORD),
        ("d4", ctypes.c_ubyte * 8),
    ]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BITMAP(ctypes.Structure):
    _fields_ = [
        ("bmType", ctypes.c_long),
        ("bmWidth", ctypes.c_long),
        ("bmHeight", ctypes.c_long),
        ("bmWidthBytes", ctypes.c_long),
        ("bmPlanes", wintypes.WORD),
        ("bmBitsPixel", wintypes.WORD),
        ("bmBits", ctypes.c_void_p),
    ]


_ole32 = ctypes.oledll.ole32
_shell32 = ctypes.windll.shell32
_gdi32 = ctypes.windll.gdi32
_shell32.SHCreateItemFromParsingName.argtypes = [
    wintypes.LPCWSTR,
    ctypes.c_void_p,
    ctypes.POINTER(_GUID),
    ctypes.POINTER(ctypes.c_void_p),
]
_shell32.SHCreateItemFromParsingName.restype = ctypes.HRESULT
_gdi32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]
_gdi32.GetDIBits.argtypes = [
    wintypes.HDC,
    wintypes.HBITMAP,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.UINT,
]
_gdi32.DeleteObject.argtypes = [wintypes.HANDLE]

_GetImage = ctypes.WINFUNCTYPE(
    ctypes.HRESULT, ctypes.c_void_p, _SIZE, ctypes.c_int, ctypes.POINTER(wintypes.HBITMAP)
)
_Release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)


def _guid(text: str) -> _GUID:
    g = _GUID()
    _ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(g))
    return g


_IID_IShellItemImageFactory = _guid("{bcc18b79-ba16-442f-80c4-8a59c30c463b}")


def _hbitmap_to_qimage(hbm: int) -> QImage:
    """Copy a 32bpp HBITMAP into a QImage, keeping its (premultiplied) alpha.

    QImage.fromHBITMAP drops alpha (Format_RGB32), which turns transparent
    icon corners black, so read the bits ourselves.
    """
    bm = _BITMAP()
    _gdi32.GetObjectW(hbm, ctypes.sizeof(bm), ctypes.byref(bm))
    w, h = bm.bmWidth, bm.bmHeight
    hdr = _BITMAPINFOHEADER()
    hdr.biSize = ctypes.sizeof(hdr)
    hdr.biWidth = w
    hdr.biHeight = -h  # top-down rows
    hdr.biPlanes = 1
    hdr.biBitCount = 32
    buf = ctypes.create_string_buffer(w * h * 4)
    hdc = ctypes.windll.user32.GetDC(None)
    try:
        _gdi32.GetDIBits(hdc, hbm, 0, h, buf, ctypes.byref(hdr), 0)
    finally:
        ctypes.windll.user32.ReleaseDC(None, hdc)
    data = buf.raw
    # Some providers return fully opaque bitmaps with alpha=0; treat as opaque.
    fmt = QImage.Format.Format_ARGB32_Premultiplied
    if not any(data[3::4]):
        fmt = QImage.Format.Format_RGB32
    return QImage(data, w, h, w * 4, fmt).copy()


def shell_image(path: str, size: int, icon_only: bool) -> QImage | None:
    """Icon or thumbnail for `path` as Explorer draws it. COM must be initialised."""
    unk = ctypes.c_void_p()
    try:
        _shell32.SHCreateItemFromParsingName(
            path, None, ctypes.byref(_IID_IShellItemImageFactory), ctypes.byref(unk)
        )
    except OSError:
        return None
    vtbl = ctypes.cast(
        ctypes.cast(unk, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p)
    )
    hbm = wintypes.HBITMAP()
    try:
        _GetImage(vtbl[3])(
            unk, _SIZE(size, size), SIIGBF_ICONONLY if icon_only else 0, ctypes.byref(hbm)
        )
    except OSError:
        return None
    finally:
        _Release(vtbl[2])(unk)
    try:
        return _hbitmap_to_qimage(hbm.value)
    finally:
        _gdi32.DeleteObject(hbm)


class _Worker(QThread):
    loaded = Signal(str, int, bool, QImage)

    def __init__(self, jobs: "queue.Queue[tuple[str, int, bool] | None]", parent=None):
        super().__init__(parent)
        self._jobs = jobs

    def run(self):
        _ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
        try:
            while True:
                job = self._jobs.get()
                if job is None:
                    return
                path, size, icon_only = job
                img = shell_image(path, size, icon_only)
                if img is not None and not img.isNull():
                    self.loaded.emit(path, size, icon_only, img)
        except Exception:
            log.exception("Icon loader thread crashed")
        finally:
            _ole32.CoUninitialize()


class IconLoader(QObject):
    """App-wide request queue; emits `loaded` on the GUI thread.

    One shared instance (see icon_loader()) serves every panel so a file's
    icon is fetched once no matter how many panels show it.
    """

    loaded = Signal(str, int, bool, QImage)  # path, size, icon_only, image

    def __init__(self):
        super().__init__()
        self._jobs: queue.Queue = queue.Queue()
        self._pending: set[tuple[str, int, bool]] = set()
        self._worker = _Worker(self._jobs)
        self._worker.loaded.connect(self._on_loaded)
        self._worker.start()

    def request(self, path: str, size: int, icon_only: bool = True) -> None:
        key = (path, size, icon_only)
        if key not in self._pending:
            self._pending.add(key)
            self._jobs.put(key)

    def stop(self) -> None:
        try:
            while True:
                self._jobs.get_nowait()
        except queue.Empty:
            pass
        self._pending.clear()
        self._jobs.put(None)
        self._worker.wait(2000)

    def _on_loaded(self, path: str, size: int, icon_only: bool, img: QImage):
        self._pending.discard((path, size, icon_only))
        self.loaded.emit(path, size, icon_only, img)


_instance: IconLoader | None = None


def icon_loader() -> IconLoader:
    global _instance
    if _instance is None:
        _instance = IconLoader()
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(_instance.stop)
    return _instance
