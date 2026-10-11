"""Panel search bar: live filter or deeper searches, regex toggle, history (D01-D07)."""

import re

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QToolButton,
    QWidget,
    QWidgetAction,
)

from panel_widgets import _PathLineEdit
from search_utils import make_matcher, search_history

# (mode id, label). "filter" hides non-matching rows in place; the others open
# a results window (search_dialog.SearchResultsDialog).
SEARCH_MODES = (
    ("filter", "篩選本資料夾"),
    ("recursive", "搜尋子資料夾"),
    ("content", "搜尋檔案內容"),
    ("everything", "Everything 全電腦"),
)


class _HistoryMenu(QMenu):
    """History popup: click an entry to reuse it, ✕ removes one, last item clears all."""

    picked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.aboutToShow.connect(self._rebuild)

    def _rebuild(self) -> None:
        self.clear()
        items = search_history.items()
        if not items:
            empty = self.addAction("（沒有搜尋歷史）")
            empty.setEnabled(False)
            return
        for text in items:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(4, 1, 4, 1)
            layout.setSpacing(2)
            pick = QPushButton(text)
            pick.setObjectName("historyItem")
            pick.setFlat(True)
            pick.clicked.connect(lambda _=False, t=text: self._pick(t))
            layout.addWidget(pick, 1)
            remove = QToolButton()
            remove.setText("✕")
            remove.setToolTip("刪除這筆")
            remove.clicked.connect(lambda _=False, t=text: self._remove(t))
            layout.addWidget(remove)
            action = QWidgetAction(self)
            action.setDefaultWidget(row)
            self.addAction(action)
        self.addSeparator()
        clear = self.addAction("清除全部歷史")
        clear.triggered.connect(search_history.clear)

    def _pick(self, text: str) -> None:
        self.close()
        self.picked.emit(text)

    def _remove(self, text: str) -> None:
        search_history.remove(text)
        # Rebuild after the click handler returns: the clicked button is deleted.
        QTimer.singleShot(0, self._refresh_open)

    def _refresh_open(self) -> None:
        self._rebuild()
        self.adjustSize()


class SearchBar(QWidget):
    """Filter the current folder live, or press Enter to search deeper."""

    filter_changed = Signal(object)  # name predicate or None
    search_requested = Signal(str, str, bool)  # mode, text, regex
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("searchBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)

        self.mode_box = QComboBox()
        for mode, label in SEARCH_MODES:
            self.mode_box.addItem(label, mode)
        self.mode_box.currentIndexChanged.connect(self._on_mode_changed)
        layout.addWidget(self.mode_box)

        self.input = _PathLineEdit()
        self.input.textChanged.connect(self._emit_filter)
        self.input.returnPressed.connect(self._on_enter)
        layout.addWidget(self.input, 1)

        self.regex_btn = QToolButton()
        self.regex_btn.setText(".*")
        self.regex_btn.setCheckable(True)
        self.regex_btn.setToolTip("使用正規表示式（未勾選時可用 * 與 ? 萬用字元）")
        self.regex_btn.toggled.connect(self._emit_filter)
        layout.addWidget(self.regex_btn)

        history_btn = QToolButton()
        history_btn.setText("▾")
        history_btn.setToolTip("搜尋歷史")
        self._history_menu = _HistoryMenu(self)
        self._history_menu.picked.connect(self._use_history)
        history_btn.setMenu(self._history_menu)
        history_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        layout.addWidget(history_btn)

        self.count_label = QLabel("")
        self.count_label.setObjectName("searchCount")
        layout.addWidget(self.count_label)

        btn_close = QPushButton("✕")
        btn_close.setFixedWidth(28)
        btn_close.clicked.connect(self._close)
        layout.addWidget(btn_close)

        self._on_mode_changed()
        self.setVisible(False)

    def mode(self) -> str:
        return self.mode_box.currentData()

    def activate(self, mode: str = "filter") -> None:
        index = self.mode_box.findData(mode)
        if index >= 0:
            self.mode_box.setCurrentIndex(index)
        self.setVisible(True)
        self.input.setFocus()
        self.input.selectAll()

    def set_count(self, shown: int, total: int) -> None:
        """D06: "符合 12 / 340 項"."""
        if self.mode() == "filter" and self.input.text().strip():
            self.count_label.setText(f"符合 {shown} / {total} 項")
        else:
            self.count_label.setText("")

    def _on_mode_changed(self) -> None:
        hints = {
            "filter": "輸入檔名篩選，例如 報告 或 *.jpg",
            "recursive": "按 Enter 搜尋所有子資料夾",
            "content": "輸入要找的文字，按 Enter 搜尋檔案內容",
            "everything": "按 Enter 用 Everything 搜尋整台電腦",
        }
        self.input.setPlaceholderText(hints[self.mode()])
        self.regex_btn.setEnabled(self.mode() != "content")
        self._emit_filter()

    def _emit_filter(self) -> None:
        if self.mode() != "filter":
            self._set_error("")
            self.filter_changed.emit(None)
            return
        try:
            matcher = make_matcher(self.input.text(), self.regex_btn.isChecked())
        except re.error:
            self._set_error("正規表示式有誤")
            return
        self._set_error("")
        self.filter_changed.emit(matcher)

    def _set_error(self, message: str) -> None:
        self.input.setProperty("error", bool(message))
        self.input.style().unpolish(self.input)
        self.input.style().polish(self.input)
        if message:
            self.count_label.setText(message)

    def _on_enter(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        search_history.add(text)
        if self.mode() != "filter":
            regex = self.regex_btn.isChecked() and self.mode() != "content"
            if regex:
                try:
                    re.compile(text)
                except re.error:
                    self._set_error("正規表示式有誤")
                    return
            self.search_requested.emit(self.mode(), text, regex)

    def _use_history(self, text: str) -> None:
        self.input.setText(text)
        self.input.setFocus()
        if self.mode() != "filter":
            self._on_enter()

    def _close(self) -> None:
        self.input.clear()
        self.count_label.setText("")
        self.setVisible(False)
        self.closed.emit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._close()
        else:
            super().keyPressEvent(event)
