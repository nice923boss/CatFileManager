"""Command palette (H06), shortcut list (H01) and About dialog (K04)."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
)

from shortcuts import ACTIONS, key_for
from version import CHANGELOG, VERSION

REPO_URL = "https://github.com/nice923boss/CatFileManager"


def _key_text(action_id: str, overrides: dict[str, str]) -> str:
    key = key_for(action_id, overrides)
    return QKeySequence(key).toString(QKeySequence.SequenceFormat.NativeText) if key else ""


class CommandPalette(QDialog):
    """Type to filter every command, Enter runs the highlighted one."""

    def __init__(self, overrides: dict[str, str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("命令面板")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.resize(480, 420)
        self._chosen = ""

        layout = QVBoxLayout(self)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("輸入命令名稱…")
        self.filter.textChanged.connect(self._apply_filter)
        self.filter.returnPressed.connect(self._accept_current)
        self.filter.installEventFilter(self)
        layout.addWidget(self.filter)

        self.list = QListWidget()
        self.list.itemActivated.connect(lambda _item: self._accept_current())
        for a in ACTIONS:
            if a.id == "command_palette":
                continue
            key = _key_text(a.id, overrides)
            item = QListWidgetItem(f"{a.label}　　{key}" if key else a.label)
            item.setData(Qt.ItemDataRole.UserRole, a.id)
            self.list.addItem(item)
        layout.addWidget(self.list)
        self._apply_filter("")

    def eventFilter(self, obj, event):
        # Up / Down in the filter box move the list highlight.
        if obj is self.filter and event.type() == event.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                self._move(-1 if event.key() == Qt.Key.Key_Up else 1)
                return True
        return super().eventFilter(obj, event)

    def _visible_rows(self) -> list[int]:
        return [r for r in range(self.list.count()) if not self.list.item(r).isHidden()]

    def _move(self, step: int):
        rows = self._visible_rows()
        if not rows:
            return
        cur = self.list.currentRow()
        pos = rows.index(cur) if cur in rows else -1
        self.list.setCurrentRow(rows[max(0, min(len(rows) - 1, pos + step))])

    def _apply_filter(self, text: str):
        words = text.lower().split()
        for r in range(self.list.count()):
            item = self.list.item(r)
            haystack = f"{item.text()} {item.data(Qt.ItemDataRole.UserRole)}".lower()
            item.setHidden(not all(w in haystack for w in words))
        rows = self._visible_rows()
        self.list.setCurrentRow(rows[0] if rows else -1)

    def _accept_current(self):
        item = self.list.currentItem()
        if item is not None and not item.isHidden():
            self._chosen = item.data(Qt.ItemDataRole.UserRole)
            self.accept()

    def chosen(self) -> str:
        return self._chosen


class ShortcutListDialog(QDialog):
    """F1: every command with its current key; edit keys in Settings."""

    def __init__(self, overrides: dict[str, str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("快捷鍵一覽")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.resize(460, 560)

        layout = QVBoxLayout(self)
        table = QTableWidget(len(ACTIONS), 2)
        table.setHorizontalHeaderLabels(["功能", "快捷鍵"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        for row, a in enumerate(ACTIONS):
            table.setItem(row, 0, QTableWidgetItem(a.label))
            table.setItem(row, 1, QTableWidgetItem(_key_text(a.id, overrides) or "（未設定）"))
        layout.addWidget(table)

        hint = QLabel("快捷鍵可在「設定 → 快捷鍵」修改。")
        hint.setObjectName("dimText")
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("關於 CatFileManager")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.resize(460, 420)

        layout = QVBoxLayout(self)
        title = QLabel(f"<h2>CatFileManager {VERSION}</h2>")
        layout.addWidget(title)
        info = QLabel(
            "四面板檔案管理工具<br>"
            "製作者：黃政文<br>"
            "授權：MIT（免費開源）<br>"
            f'<a href="{REPO_URL}">{REPO_URL}</a>'
        )
        info.setOpenExternalLinks(True)
        info.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        layout.addWidget(info)

        changelog = QTextBrowser()
        html = ["<h3>更新紀錄</h3>"]
        for version, lines in CHANGELOG:
            items = "".join(f"<li>{line}</li>" for line in lines)
            html.append(f"<b>{version}</b><ul>{items}</ul>")
        changelog.setHtml("".join(html))
        layout.addWidget(changelog, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
