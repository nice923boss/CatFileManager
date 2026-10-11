"""Quad File Manager — entry point (single instance)."""

import os
import sys

# Ensure the script directory is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Redirect stdout/stderr to a log file when running under pythonw (no console),
# so crashes and prints are captured instead of vanishing.
if sys.stdout is None or sys.stderr is None:
    _log_dir = os.path.expanduser("~")
    _log_file = open(os.path.join(_log_dir, ".catfm_app.log"), "a", buffering=1, encoding="utf-8")
    sys.stdout = _log_file
    sys.stderr = _log_file

from PySide6.QtCore import Qt
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from file_manager import FileManagerWindow

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
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

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
