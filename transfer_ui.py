"""Operation queue (C04), its progress window (C03, C05) and the conflict dialog (C01)."""

import os
from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from copy_engine import OVERWRITE, RENAME, SKIP, Progress, TransferResult, TransferWorker
from long_path import lp
from undo import undo_stack


def format_bytes(n: float) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(n)
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    return f"{int(size)} {units[idx]}" if idx == 0 else f"{size:.1f} {units[idx]}"


def format_eta(seconds: float) -> str:
    if seconds < 0:
        return "計算中"
    seconds = int(seconds)
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _describe(op: str, sources: list[str], destination: str) -> str:
    verb = "複製" if op == "copy" else "移動"
    first = os.path.basename(sources[0]) if sources else ""
    more = f" 等 {len(sources)} 項" if len(sources) > 1 else ""
    return f"{verb} {first}{more} → {destination}"


class _Job:
    def __init__(self, op, sources, destination, verify, on_done):
        self.op = op
        self.sources = sources
        self.destination = destination
        self.verify = verify
        self.on_done = on_done
        self.label = _describe(op, sources, destination)


class OperationQueue(QObject):
    """Runs copy/move jobs one after another (one disk-heavy job at a time)."""

    changed = Signal()
    progress = Signal(object)  # Progress of the running job
    conflict = Signal(str, str)  # src, dst -> answered via worker().resolve_conflict

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pending: list[_Job] = []
        self._job: _Job | None = None
        self._worker: TransferWorker | None = None

    def enqueue(
        self,
        op: str,
        sources: list[str],
        destination: str,
        verify: bool = False,
        on_done: Callable[[TransferResult], None] | None = None,
    ) -> None:
        self._pending.append(_Job(op, list(sources), destination, verify, on_done))
        self.changed.emit()
        self._start_next()

    def current(self) -> _Job | None:
        return self._job

    def worker(self) -> TransferWorker | None:
        return self._worker

    def pending_labels(self) -> list[str]:
        return [j.label for j in self._pending]

    def remove_pending(self, index: int) -> None:
        if 0 <= index < len(self._pending):
            del self._pending[index]
            self.changed.emit()

    def is_busy(self) -> bool:
        return self._job is not None

    def cancel_all(self) -> None:
        self._pending.clear()
        if self._worker:
            self._worker.cancel()
        self.changed.emit()

    def shutdown(self) -> None:
        self.cancel_all()
        if self._worker:
            self._worker.wait(5000)

    def _start_next(self) -> None:
        if self._job or not self._pending:
            return
        self._job = self._pending.pop(0)
        w = TransferWorker(self._job.op, self._job.sources, self._job.destination, self._job.verify)
        w.progress.connect(self.progress)
        w.conflict.connect(lambda s, d, *_: self.conflict.emit(s, d))
        w.done.connect(self._on_done)
        self._worker = w
        self.changed.emit()
        w.start()

    def _on_done(self, result: TransferResult) -> None:
        job, worker = self._job, self._worker
        self._job = None
        self._worker = None
        if worker:
            worker.wait()
            worker.deleteLater()
        if result.records:
            label = job.label if result.undo_complete else job.label + "（覆蓋的檔案無法還原）"
            undo_stack.push(label, result.records)
        if job and job.on_done:
            job.on_done(result)
        self.changed.emit()
        self._start_next()


class ConflictDialog(QDialog):
    """Overwrite / skip / keep both, optionally for every remaining conflict."""

    def __init__(self, src: str, dst: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("檔案已存在")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.choice = SKIP
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"目的資料夾已有「{os.path.basename(dst)}」。"))

        grid = QGridLayout()
        for row, (title, path) in enumerate((("來源", src), ("目的地", dst))):
            grid.addWidget(QLabel(title), row, 0)
            info = QLabel(self._info(path))
            info.setObjectName("dimText")
            info.setToolTip(path)
            grid.addWidget(info, row, 1)
        layout.addLayout(grid)

        self._all = QCheckBox("其餘衝突都套用相同動作")
        layout.addWidget(self._all)

        buttons = QHBoxLayout()
        for text, choice in (("覆蓋", OVERWRITE), ("略過", SKIP), ("保留兩者（改名）", RENAME)):
            btn = QPushButton(text)
            btn.clicked.connect(lambda _=False, c=choice: self._pick(c))
            buttons.addWidget(btn)
        buttons.addStretch()
        cancel = QPushButton("取消整個操作")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

    @staticmethod
    def _info(path: str) -> str:
        try:
            st = os.stat(lp(path))
        except OSError:
            return path
        when = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
        if os.path.isdir(lp(path)):
            return f"資料夾（合併內容）  修改 {when}"
        return f"{format_bytes(st.st_size)}  修改 {when}"

    def _pick(self, choice: str) -> None:
        self.choice = choice
        self.accept()

    def apply_all(self) -> bool:
        return self._all.isChecked()


class QueueWindow(QDialog):
    """Non-modal window: running job (bytes, speed, ETA, pause/cancel) plus the queue."""

    def __init__(self, queue: OperationQueue, parent=None):
        super().__init__(parent)
        self._queue = queue
        self.setWindowTitle("檔案操作")
        self.setMinimumWidth(520)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        self._title = QLabel("")
        self._title.setWordWrap(True)
        layout.addWidget(self._title)
        self._file = QLabel("")
        self._file.setObjectName("dimText")
        layout.addWidget(self._file)
        self._bar = QProgressBar()
        self._bar.setRange(0, 1000)
        layout.addWidget(self._bar)
        self._stats = QLabel("")
        layout.addWidget(self._stats)

        row = QHBoxLayout()
        self._pause_btn = QPushButton("暫停")
        self._pause_btn.clicked.connect(self._toggle_pause)
        row.addWidget(self._pause_btn)
        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.setToolTip("取消後不能續傳；要稍後繼續請按「暫停」")
        self._cancel_btn.clicked.connect(self._cancel_current)
        row.addWidget(self._cancel_btn)
        row.addStretch()
        layout.addLayout(row)

        self._pending_box = QWidget()
        pending_layout = QVBoxLayout(self._pending_box)
        pending_layout.setContentsMargins(0, 8, 0, 0)
        pending_layout.addWidget(QLabel("等待中的操作"))
        self._pending = QListWidget()
        self._pending.setMaximumHeight(120)
        pending_layout.addWidget(self._pending)
        remove = QPushButton("移出佇列")
        remove.clicked.connect(lambda: self._queue.remove_pending(self._pending.currentRow()))
        pending_layout.addWidget(remove, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._pending_box)

        queue.changed.connect(self._refresh)
        queue.progress.connect(self._on_progress)
        queue.conflict.connect(self._on_conflict)
        self._last_label = ""
        self._refresh()

    def _refresh(self) -> None:
        job = self._queue.current()
        if job is None:
            self._bar.setValue(0)
            self.hide()
            return
        if job.label != self._last_label:
            self._last_label = job.label
            self._title.setText(job.label)
            self._file.setText("")
            self._stats.setText("")
            self._bar.setValue(0)
            self._pause_btn.setText("暫停")
        labels = self._queue.pending_labels()
        self._pending.clear()
        self._pending.addItems(labels)
        self._pending_box.setVisible(bool(labels))
        if not self.isVisible():
            self.show()

    def _on_progress(self, p: Progress) -> None:
        if p.bytes_total:
            self._bar.setValue(int(p.bytes_done * 1000 / p.bytes_total))
        elif p.files_total:
            self._bar.setValue(int(p.files_done * 1000 / p.files_total))
        self._file.setText(p.name)
        paused = self._queue.worker() and self._queue.worker().is_paused()
        speed = "已暫停" if paused else f"{format_bytes(p.speed)}/s"
        self._stats.setText(
            f"{format_bytes(p.bytes_done)} / {format_bytes(p.bytes_total)}　"
            f"檔案 {p.files_done} / {p.files_total}　{speed}　剩餘 {format_eta(p.eta)}"
        )

    def _toggle_pause(self) -> None:
        w = self._queue.worker()
        if not w:
            return
        if w.is_paused():
            w.resume()
            self._pause_btn.setText("暫停")
        else:
            w.pause()
            self._pause_btn.setText("繼續")
            self._stats.setText(self._stats.text().rsplit("　", 2)[0] + "　已暫停")

    def _cancel_current(self) -> None:
        w = self._queue.worker()
        if w:
            w.cancel()

    def _on_conflict(self, src: str, dst: str) -> None:
        w = self._queue.worker()
        if not w:
            return
        dlg = ConflictDialog(src, dst, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            w.resolve_conflict(dlg.choice, dlg.apply_all())
        else:
            w.cancel()

    def closeEvent(self, event) -> None:
        # Closing the window only hides it; the job keeps running.
        event.ignore()
        self.hide()
