"""Progress and hash dialogs used by the file panels."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from file_operations import HashCalculateWorker


class FileProgressDialog(QDialog):
    """Progress dialog for file copy/move operations."""

    def __init__(self, operation: str, total: int, parent=None):
        super().__init__(parent)
        op_name = {"copy": "複製", "move": "移動", "zip": "壓縮"}.get(operation, "處理")
        self.setWindowTitle(f"正在{op_name}檔案")
        self.setMinimumWidth(420)
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)

        self._label_op = QLabel(f"正在{op_name}...")
        layout.addWidget(self._label_op)

        self._label_file = QLabel("")
        self._label_file.setStyleSheet("color: gray;")
        layout.addWidget(self._label_file)

        self._progress = QProgressBar()
        self._progress.setRange(0, total)
        self._progress.setValue(0)
        layout.addWidget(self._progress)

        self._cancel_btn = QPushButton("取消")
        layout.addWidget(self._cancel_btn)

        self._cancelled = False
        self._cancel_btn.clicked.connect(self._on_cancel)

    def _on_cancel(self) -> None:
        self._cancelled = True
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.setText("正在取消...")

    def update_progress(self, current: int, total: int, filename: str) -> None:
        self._progress.setRange(0, total)
        self._progress.setValue(current)
        if filename:
            self._label_file.setText(filename)


def _format_bytes(n: int) -> str:
    """Return human-readable size like '3.2 MB'."""
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(n)
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    if idx == 0:
        return f"{int(size)} {units[idx]}"
    return f"{size:.2f} {units[idx]}"


class HashDialog(QDialog):
    """Compute and display MD5 / SHA-1 / SHA-256 for the selected files."""

    def __init__(self, paths: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("計算哈希值")
        self.setModal(False)
        self.resize(760, 480)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)

        self._label_status = QLabel("準備計算...")
        layout.addWidget(self._label_status)

        self._label_file = QLabel("")
        self._label_file.setStyleSheet("color: gray;")
        layout.addWidget(self._label_file)

        self._progress = QProgressBar()
        self._progress.setRange(0, 1000)
        self._progress.setValue(0)
        layout.addWidget(self._progress)

        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._text.setFont(mono)
        self._text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self._text)

        btn_row = QHBoxLayout()
        self._btn_copy = QPushButton("複製全部")
        self._btn_copy.clicked.connect(self._copy_all)
        self._btn_copy.setEnabled(False)
        btn_row.addWidget(self._btn_copy)
        btn_row.addStretch()
        self._btn_close = QPushButton("取消")
        self._btn_close.clicked.connect(self.close)
        btn_row.addWidget(self._btn_close)
        layout.addLayout(btn_row)

        self._total_files = len(paths)
        self._done_files = 0
        self._errors: list[str] = []
        self._lines: list[str] = []

        self._worker = HashCalculateWorker(paths, parent=self)
        self._worker.progress.connect(self._on_progress)
        self._worker.file_done.connect(self._on_file_done)
        self._worker.file_error.connect(self._on_file_error)
        self._worker.finished_all.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, idx: int, total: int, name: str, done: int, size: int) -> None:
        if total <= 0:
            return
        if size > 0:
            frac_file = done / size
        else:
            frac_file = 1.0
        overall = int(((idx + frac_file) / total) * 1000)
        self._progress.setValue(overall)
        self._label_status.setText(f"正在計算 [{idx + 1}/{total}]：{name}")
        if size > 0:
            self._label_file.setText(f"{_format_bytes(done)} / {_format_bytes(size)}")
        else:
            self._label_file.setText("(空檔案)")

    def _on_file_done(self, path: str, h: dict) -> None:
        self._done_files += 1
        entry = (
            f"檔案：{path}\n"
            f"  MD5     : {h['md5']}\n"
            f"  SHA-1   : {h['sha1']}\n"
            f"  SHA-256 : {h['sha256']}"
        )
        self._append_entry(entry)

    def _on_file_error(self, path: str, msg: str) -> None:
        self._errors.append(f"{path}: {msg}")
        entry = f"檔案：{path}\n  錯誤：{msg}"
        self._append_entry(entry)

    def _append_entry(self, entry: str) -> None:
        self._lines.append(entry)
        current = self._text.toPlainText()
        if current:
            self._text.setPlainText(current + "\n\n" + entry)
        else:
            self._text.setPlainText(entry)
        self._btn_copy.setEnabled(True)

    def _on_finished(self) -> None:
        self._progress.setValue(1000)
        parts = [f"已完成：{self._done_files}/{self._total_files} 個檔案"]
        if self._errors:
            parts.append(f"錯誤 {len(self._errors)} 個")
        self._label_status.setText("，".join(parts))
        self._label_file.setText("")
        self._btn_close.setText("關閉")

    def _copy_all(self) -> None:
        text = self._text.toPlainText()
        if text:
            QApplication.clipboard().setText(text)

    def _stop_worker(self) -> None:
        if self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)

    def reject(self) -> None:
        self._stop_worker()
        super().reject()

    def closeEvent(self, event) -> None:
        self._stop_worker()
        super().closeEvent(event)
