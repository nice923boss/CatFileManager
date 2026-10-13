"""Settings dialog (I01): appearance, startup, operations, shortcuts, context menu."""

import copy

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from panel_context_menu import CONTEXT_MENU_ITEMS, SEPARATOR_PREFIX, ordered_menu_ids
from settings import DEFAULT_PREFS
from shortcuts import ACTIONS, action, find_conflicts, key_for

_THEMES = (("dark", "深色"), ("light", "淺色"), ("system", "跟隨 Windows"))
_LAYOUTS = (
    ("1", "單一面板"),
    ("2h", "左右兩欄"),
    ("2v", "上下兩列"),
    ("3", "三面板"),
    ("4", "四面板"),
)
_MENU_LABELS = dict(CONTEXT_MENU_ITEMS)


def _combo(options, current: str) -> QComboBox:
    box = QComboBox()
    for value, label in options:
        box.addItem(label, value)
    box.setCurrentIndex(max(0, box.findData(current)))
    return box


def _path_row(edit: QLineEdit, pick) -> QWidget:
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(edit, 1)
    btn = QPushButton("瀏覽…")
    btn.clicked.connect(pick)
    lay.addWidget(btn)
    return row


class SettingsDialog(QDialog):
    def __init__(self, prefs: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("設定")
        self.resize(620, 560)
        self._prefs = copy.deepcopy(prefs)

        tabs = QTabWidget()
        tabs.addTab(self._build_appearance(), "外觀")
        tabs.addTab(self._build_startup(), "啟動")
        tabs.addTab(self._build_operations(), "操作與搜尋")
        tabs.addTab(self._build_shortcuts(), "快捷鍵")
        tabs.addTab(self._build_context_menu(), "右鍵選單")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("確定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs, 1)
        layout.addWidget(buttons)

    # --- tabs ---

    def _build_appearance(self) -> QWidget:
        p = self._prefs
        page = QWidget()
        form = QFormLayout(page)
        self.theme_box = _combo(_THEMES, p["theme"])
        form.addRow("主題：", self.theme_box)

        self.font_default = QCheckBox("使用系統預設字型")
        self.font_default.setChecked(not p["font_family"])
        self.font_box = QFontComboBox()
        if p["font_family"]:
            self.font_box.setCurrentText(p["font_family"])
        self.font_box.setEnabled(bool(p["font_family"]))
        self.font_default.toggled.connect(lambda on: self.font_box.setEnabled(not on))
        form.addRow("字型：", self.font_default)
        form.addRow("", self.font_box)

        self.font_size = QSpinBox()
        self.font_size.setRange(9, 24)
        self.font_size.setValue(p["font_size"])
        self.font_size.setSuffix(" px")
        form.addRow("字型大小：", self.font_size)

        self.layout_box = _combo(_LAYOUTS, p["layout"])
        form.addRow("面板版面：", self.layout_box)

        self.show_hidden = QCheckBox("顯示隱藏檔與系統檔")
        self.show_hidden.setChecked(p["show_hidden"])
        self.show_ext = QCheckBox("顯示副檔名")
        self.show_ext.setChecked(p["show_extensions"])
        self.color_by_type = QCheckBox("依檔案類型著色（圖片、影片、壓縮檔、執行檔）")
        self.color_by_type.setChecked(p["color_by_type"])
        for box in (self.show_hidden, self.show_ext, self.color_by_type):
            form.addRow("", box)
        return page

    def _build_startup(self) -> QWidget:
        p = self._prefs
        page = QWidget()
        form = QFormLayout(page)
        self.start_last = QRadioButton("開啟上次關閉時的資料夾")
        self.start_fixed = QRadioButton("開啟下列固定資料夾")
        (self.start_fixed if p["startup_mode"] == "fixed" else self.start_last).setChecked(True)
        form.addRow(self.start_last)
        form.addRow(self.start_fixed)

        self.startup_edits: list[QLineEdit] = []
        paths = list(p["startup_paths"]) + [""] * 4
        for i in range(4):
            edit = QLineEdit(paths[i])
            edit.setPlaceholderText("留空則沿用上次的資料夾")
            self.startup_edits.append(edit)
            form.addRow(
                f"面板 {i + 1}：", _path_row(edit, lambda _=False, e=edit: self._pick_dir(e))
            )
        self.start_fixed.toggled.connect(self._sync_startup_enabled)
        self._sync_startup_enabled()
        return page

    def _sync_startup_enabled(self):
        for edit in self.startup_edits:
            edit.parentWidget().setEnabled(self.start_fixed.isChecked())

    def _build_operations(self) -> QWidget:
        p = self._prefs
        page = QWidget()
        form = QFormLayout(page)
        self.verify_copy = QCheckBox("複製完成後比對檔案內容（較慢，但能確認資料完整）")
        self.verify_copy.setChecked(p["verify_after_copy"])
        form.addRow(self.verify_copy)

        self.es_path = QLineEdit(p["everything_path"])
        self.es_path.setPlaceholderText("留空則自動尋找 es.exe")
        form.addRow("Everything es.exe：", _path_row(self.es_path, self._pick_es))
        hint = QLabel(
            "需先安裝 Everything 並執行，再下載命令列工具 es.exe。"
            "搜尋列的「Everything」模式會用它搜尋整台電腦。"
        )
        hint.setObjectName("dimText")
        hint.setWordWrap(True)
        form.addRow("", hint)
        return page

    def _build_shortcuts(self) -> QWidget:
        overrides = self._prefs.get("shortcuts", {})
        page = QWidget()
        lay = QVBoxLayout(page)
        self.key_table = QTableWidget(len(ACTIONS), 2)
        self.key_table.setHorizontalHeaderLabels(["功能", "快捷鍵"])
        self.key_table.verticalHeader().setVisible(False)
        self.key_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.key_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.key_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.key_table.setColumnWidth(1, 200)

        self.key_edits: dict[str, QKeySequenceEdit] = {}
        for row, a in enumerate(ACTIONS):
            self.key_table.setItem(row, 0, QTableWidgetItem(a.label))
            edit = QKeySequenceEdit(QKeySequence(key_for(a.id, overrides)))
            edit.setMaximumSequenceLength(1)
            edit.setClearButtonEnabled(True)
            edit.keySequenceChanged.connect(self._update_conflicts)
            self.key_table.setCellWidget(row, 1, edit)
            self.key_edits[a.id] = edit
        lay.addWidget(self.key_table, 1)

        self.conflict_label = QLabel("")
        self.conflict_label.setObjectName("errorHint")
        self.conflict_label.setWordWrap(True)
        lay.addWidget(self.conflict_label)

        reset = QPushButton("全部還原預設")
        reset.clicked.connect(self._reset_keys)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(reset)
        lay.addLayout(row)
        self._update_conflicts()
        return page

    def _build_context_menu(self) -> QWidget:
        p = self._prefs
        page = QWidget()
        lay = QVBoxLayout(page)
        hint = QLabel("取消勾選可隱藏項目，用右側按鈕調整順序。")
        hint.setObjectName("dimText")
        lay.addWidget(hint)

        body = QHBoxLayout()
        self.menu_list = QListWidget()
        self.menu_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._fill_menu_list(
            ordered_menu_ids(p["context_menu_order"]), set(p["context_menu_hidden"])
        )
        body.addWidget(self.menu_list, 1)

        side = QVBoxLayout()
        for text, step in (("上移", -1), ("下移", 1)):
            btn = QPushButton(text)
            btn.clicked.connect(lambda _=False, s=step: self._move_menu_item(s))
            side.addWidget(btn)
        reset = QPushButton("還原預設")
        reset.clicked.connect(
            lambda: self._fill_menu_list([i for i, _ in CONTEXT_MENU_ITEMS], set())
        )
        side.addWidget(reset)
        side.addStretch(1)
        body.addLayout(side)
        lay.addLayout(body, 1)
        return page

    # --- helpers ---

    def _pick_dir(self, edit: QLineEdit):
        path = QFileDialog.getExistingDirectory(self, "選擇資料夾", edit.text())
        if path:
            edit.setText(path.replace("/", "\\"))

    def _pick_es(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "選擇 es.exe", self.es_path.text(), "es.exe (es.exe);;程式 (*.exe)"
        )
        if path:
            self.es_path.setText(path.replace("/", "\\"))

    def _key_overrides(self) -> dict[str, str]:
        """Only keys that differ from the defaults are stored."""
        portable = QKeySequence.SequenceFormat.PortableText
        result = {}
        for aid, edit in self.key_edits.items():
            key = edit.keySequence().toString(portable)
            # Normalise the default too ("Delete" round-trips as "Del").
            if key != QKeySequence(action(aid).default_key).toString(portable):
                result[aid] = key
        return result

    def _update_conflicts(self, *_):
        conflicts = find_conflicts(self._key_overrides())
        if not conflicts:
            self.conflict_label.setText("")
            return
        lines = [
            f"{key}：" + "、".join(action(aid).label for aid in ids)
            for key, ids in conflicts.items()
        ]
        self.conflict_label.setText("以下快捷鍵重複，請修改後再按確定：\n" + "\n".join(lines))

    def _reset_keys(self):
        for aid, edit in self.key_edits.items():
            edit.setKeySequence(QKeySequence(action(aid).default_key))

    def _fill_menu_list(self, ids: list[str], hidden: set[str]):
        self.menu_list.clear()
        for item_id in ids:
            is_sep = item_id.startswith(SEPARATOR_PREFIX)
            item = QListWidgetItem("──────── 分隔線" if is_sep else _MENU_LABELS[item_id])
            item.setData(Qt.ItemDataRole.UserRole, item_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Unchecked if item_id in hidden else Qt.CheckState.Checked
            )
            self.menu_list.addItem(item)

    def _move_menu_item(self, step: int):
        row = self.menu_list.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < self.menu_list.count():
            return
        item = self.menu_list.takeItem(row)
        self.menu_list.insertItem(target, item)
        self.menu_list.setCurrentRow(target)

    def _on_accept(self):
        if find_conflicts(self._key_overrides()):
            QMessageBox.warning(self, "快捷鍵重複", "有快捷鍵重複，請到「快捷鍵」分頁修改。")
            return
        self.accept()

    # --- result ---

    def prefs(self) -> dict:
        """New prefs dict built from the dialog (the input dict is not modified)."""
        items = [self.menu_list.item(r) for r in range(self.menu_list.count())]
        menu_ids = [i.data(Qt.ItemDataRole.UserRole) for i in items]
        hidden = [
            i.data(Qt.ItemDataRole.UserRole)
            for i in items
            if i.checkState() == Qt.CheckState.Unchecked
        ]
        default_order = [i for i, _ in CONTEXT_MENU_ITEMS]
        return {
            **DEFAULT_PREFS,
            **self._prefs,
            "theme": self.theme_box.currentData(),
            "font_family": "" if self.font_default.isChecked() else self.font_box.currentText(),
            "font_size": self.font_size.value(),
            "layout": self.layout_box.currentData(),
            "show_hidden": self.show_hidden.isChecked(),
            "show_extensions": self.show_ext.isChecked(),
            "color_by_type": self.color_by_type.isChecked(),
            "startup_mode": "fixed" if self.start_fixed.isChecked() else "last",
            "startup_paths": [e.text().strip() for e in self.startup_edits],
            "verify_after_copy": self.verify_copy.isChecked(),
            "everything_path": self.es_path.text().strip(),
            "shortcuts": self._key_overrides(),
            "context_menu_hidden": hidden,
            "context_menu_order": [] if menu_ids == default_order else menu_ids,
        }
