"""Quad File Manager — entry point (single instance)."""

import logging
import os
import sys

# Ensure the script directory is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# J05: every log goes to ~/.catfm/app.log (same file launcher.py uses).
LOG_DIR = os.path.join(os.path.expanduser("~"), ".catfm")
LOG_FILE = os.path.join(LOG_DIR, "app.log")
os.makedirs(LOG_DIR, exist_ok=True)

# Redirect stdout/stderr when running under pythonw (no console),
# so crashes and prints are captured instead of vanishing.
if sys.stdout is None or sys.stderr is None:
    _log_file = open(LOG_FILE, "a", buffering=1, encoding="utf-8")
    sys.stdout = sys.stdout or _log_file
    sys.stderr = sys.stderr or _log_file


from PySide6.QtCore import QLibraryInfo, Qt, QTranslator  # noqa: E402
from PySide6.QtNetwork import QLocalServer, QLocalSocket  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from file_manager import FileManagerWindow  # noqa: E402


def _setup_logging() -> None:
    handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])

    def _excepthook(exc_type, exc, tb):
        logging.getLogger("catfm").critical("Unhandled exception", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _excepthook


APP_KEY = "CatFileManager-SingleInstance"
_LOCK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".app.lock")


def _write_lockfile():
    try:
        with open(_LOCK_PATH, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass


def _activate_existing():
    """Try to connect to an already-running instance and bring it to front."""
    socket = QLocalSocket()
    socket.connectToServer(APP_KEY)
    if socket.waitForConnected(500):
        socket.write(b"activate")
        socket.waitForBytesWritten(500)
        socket.disconnectFromServer()
        return True
    return False


def main():
    _setup_logging()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    # Standard dialog buttons (OK/Cancel/Yes/No/Close) in Traditional Chinese
    translator = QTranslator(app)
    qt_dir = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load("qtbase_zh_TW", qt_dir):
        app.installTranslator(translator)
    else:
        logging.warning("無法載入 Qt 繁中翻譯：%s", qt_dir)

    # Check if another instance is already running
    if _activate_existing():
        sys.exit(0)

    # Start local server for single-instance detection
    server = QLocalServer()
    server.removeServer(APP_KEY)  # clean up stale socket
    server.listen(APP_KEY)

    # Only write lockfile after we are confirmed as the running instance
    _write_lockfile()

    window = FileManagerWindow()
    window.show()

    def _on_new_connection():
        conn = server.nextPendingConnection()
        if conn:
            # Bring existing window to front
            window.setWindowState(window.windowState() & ~Qt.WindowState.WindowMinimized)
            window.raise_()
            window.activateWindow()
            conn.close()

    server.newConnection.connect(_on_new_connection)

    import atexit

    atexit.register(lambda: os.path.exists(_LOCK_PATH) and os.remove(_LOCK_PATH))

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
