"""Results window for subfolder / content / Everything searches (D01, D04, D05)."""

import logging
import os
import time

from PySide6.QtCore import QMimeData, Qt, QUrl
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from search_engine import Hit, SearchWorker, run_install_script
from transfer_ui import format_bytes

log = logging.getLogger(__name__)

_MODE_TITLES = {
    "recursive": "搜尋子資料夾",
    "content": "搜尋檔案內容",
    "everything": "Everything 搜尋",
}

_PATH_ROLE = Qt.ItemDataRole.UserRole
_IS_DIR_ROLE = Qt.ItemDataRole.UserRole + 1


class _SortItem(QTreeWidgetItem):
    """Sort size and date columns by their raw value, not the display text."""

    def __lt__(self, other):
        col = self.treeWidget().sortColumn() if self.treeWidget() else 0
        if col in (2, 3):
            return (self.data(col, _PATH_ROLE) or 0) < (other.data(col, _PATH_ROLE) or 0)
        return self.text(col).lower() < other.text(col).lower()


class _ResultTree(QTreeWidget):
    """Results can be dragged out to a panel or to Explorer."""

    def mimeData(self, items):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(i.data(0, _PATH_ROLE)) for i in items])
        return mime

    def mimeTypes(self):
        return ["text/uri-list"]

    def supportedDropActions(self):
        return Qt.DropAction.CopyAction


class SearchResultsDialog(QDialog):
    """Non-modal: results stream in while the search runs; act on them directly."""

    def __init__(self, panel, mode: str, root: str, text: str, regex: bool, es_path: str = ""):
        super().__init__(panel.window())
        self._panel = panel
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        where = "整台電腦" if mode == "everything" else root
        self.setWindowTitle(f"{_MODE_TITLES.get(mode, '搜尋')}：{text}（{where}）")
        self.resize(900, 520)

        layout = QVBoxLayout(self)
        self.tree = _ResultTree()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["名稱", "位置", "大小", "修改日期"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(1, Qt.SortOrder.AscendingOrder)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setDragEnabled(True)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.tree.setColumnWidth(0, 240)
        self.tree.setColumnWidth(1, 380)
        self.tree.setColumnWidth(2, 80)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_menu)
        self.tree.itemDoubleClicked.connect(lambda item, _col: self._go_to(item))
        layout.addWidget(self.tree, 1)

        bottom = QHBoxLayout()
        self.status = QLabel("搜尋中…")
        self.status.setObjectName("dimText")
        bottom.addWidget(self.status, 1)
        # Shown when an Everything search fails because es.exe / Everything is missing.
        self.install_btn = QPushButton("一鍵安裝 Everything")
        self.install_btn.clicked.connect(self._install_everything)
        self.install_btn.hide()
        bottom.addWidget(self.install_btn)
        self.retry_btn = QPushButton("重新搜尋")
        self.retry_btn.clicked.connect(self._start_search)
        self.retry_btn.hide()
        bottom.addWidget(self.retry_btn)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.clicked.connect(self._stop)
        bottom.addWidget(self.stop_btn)
        layout.addLayout(bottom)

        self._search_args = (mode, root, text, regex, es_path)
        self._worker = None
        self._start_search()

    def _start_search(self) -> None:
        if self._worker is not None:
            self._worker.wait()  # already done; let the thread finish before dropping it
        self.tree.clear()
        self.install_btn.hide()
        self.retry_btn.hide()
        self.stop_btn.setEnabled(True)
        self.status.setText("搜尋中…")
        self._count = 0
        self._user_stopped = False
        self._worker = SearchWorker(*self._search_args)
        self._worker.found.connect(self._add_hits)
        self._worker.scanning.connect(lambda folder: self.status.setText(f"搜尋中… {folder}"))
        self._worker.done.connect(self._on_done)
        self._worker.start()

    # --- results ---

    def _add_hits(self, hits: list[Hit]) -> None:
        self.tree.setSortingEnabled(False)
        for hit in hits:
            item = _SortItem()
            item.setText(0, os.path.basename(hit.path) or hit.path)
            item.setText(1, os.path.dirname(hit.path))
            item.setText(2, "" if hit.is_dir else format_bytes(hit.size))
            item.setText(3, time.strftime("%Y/%m/%d %H:%M", time.localtime(hit.modified)))
            item.setData(0, _PATH_ROLE, hit.path)
            item.setData(0, _IS_DIR_ROLE, hit.is_dir)
            item.setData(2, _PATH_ROLE, -1 if hit.is_dir else hit.size)
            item.setData(3, _PATH_ROLE, hit.modified)
            item.setToolTip(0, hit.path)
            self.tree.addTopLevelItem(item)
        self.tree.setSortingEnabled(True)
        self._count += len(hits)
        self.status.setText(f"搜尋中… 已找到 {self._count} 項")

    def _on_done(self, error: str, truncated: bool) -> None:
        self.stop_btn.setEnabled(False)
        if error:
            self.status.setText(error)
            self.status.setWordWrap(True)  # long messages must not squeeze the buttons
            self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            if self._worker.needs_install:
                self.install_btn.show()
                self.retry_btn.show()
            return
        if self._user_stopped:
            text = f"已停止，共 {self._count} 項"
        else:
            text = f"完成，共 {self._count} 項"
            if truncated:
                text += f"（只顯示前 {SearchWorker.LIMIT} 項，請縮小搜尋範圍）"
        self.status.setText(text)

    def _stop(self) -> None:
        self._user_stopped = True
        self._worker.cancel()

    def _install_everything(self) -> None:
        try:
            run_install_script()
        except OSError as e:
            log.exception("Could not start install_everything.ps1")
            self.status.setText(f"無法啟動安裝腳本：{e}")
            return
        self.status.setText("已開啟安裝視窗，裝好後按「重新搜尋」")

    # --- actions ---

    def _selected(self) -> list[str]:
        return [i.data(0, _PATH_ROLE) for i in self.tree.selectedItems()]

    def _go_to(self, item: QTreeWidgetItem) -> None:
        path = item.data(0, _PATH_ROLE)
        if item.data(0, _IS_DIR_ROLE):
            self._panel.navigate_to(path)
        else:
            self._panel.reveal(path)
        self._panel.activated.emit(self._panel.panel_id)

    def _show_menu(self, pos) -> None:
        paths = self._selected()
        if not paths:
            return
        menu = QMenu(self)
        if len(paths) == 1:
            item = self.tree.currentItem()
            menu.addAction("開啟", lambda: self._panel._shell_open(paths[0]))
            menu.addAction("在面板中顯示", lambda: self._go_to(item))
            menu.addSeparator()
        menu.addAction("複製路徑", lambda: QApplication.clipboard().setText("\n".join(paths)))
        targets = [self._panel, *self._panel.other_panels]
        for verb, op in (("複製到", "_copy_to"), ("移動到", "_move_to")):
            sub = menu.addMenu(verb)
            for p in targets:
                if p.isHidden() or not p.current_path():
                    continue
                sub.addAction(
                    f"面板 {p.panel_id + 1}：{p.current_path()}",
                    lambda p=p, op=op: getattr(p, op)(paths, p.current_path()),
                )
        menu.addSeparator()
        menu.addAction("刪除（移至資源回收筒）", lambda: self._delete(paths))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _delete(self, paths: list[str]) -> None:
        self._panel._delete(paths)
        self._drop_missing()

    def _drop_missing(self) -> None:
        for i in reversed(range(self.tree.topLevelItemCount())):
            if not os.path.lexists(self.tree.topLevelItem(i).data(0, _PATH_ROLE)):
                self.tree.takeTopLevelItem(i)

    def closeEvent(self, event) -> None:
        self._worker.cancel()
        self._worker.wait(3000)
        super().closeEvent(event)
