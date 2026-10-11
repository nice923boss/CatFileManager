"""Batch rename (C10): sequence numbers, find/replace (regex), case, date prefix."""

import os
import re
import time
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

_INVALID_CHARS = set('<>:"/\\|?*')

# Trailing characters that already separate name from number, so no "_" is added.
_SEPARATOR_TAIL = ("_", "-", " ", ".")

CASE_MODES = (("upper", "全部大寫"), ("lower", "全部小寫"), ("title", "每個單字首字大寫"))
DATE_FORMATS = (
    ("%Y%m%d_", "20261011_"),
    ("%Y-%m-%d_", "2026-10-11_"),
    ("%Y%m%d-%H%M%S_", "20261011-153000_"),
)


def _split_name(path: str) -> tuple[str, str]:
    """(stem, extension); folders have no extension."""
    name = os.path.basename(path)
    if os.path.isdir(path):
        return name, ""
    return os.path.splitext(name)


def build_rename_pairs(
    paths: list[str],
    base: str,
    start: int,
    digits: int,
) -> list[tuple[str, str]]:
    """Return (source, target) pairs renaming *paths* to base_NN, keeping extensions."""
    sep = "" if base.endswith(_SEPARATOR_TAIL) else "_"
    return build_transform_pairs(
        paths, lambda _stem, _path, i: f"{base}{sep}{start + i:0{digits}d}"
    )


def build_transform_pairs(
    paths: list[str], new_stem: Callable[[str, str, int], str]
) -> list[tuple[str, str]]:
    """(source, target) pairs; *new_stem(stem, path, index)* gives the new stem."""
    pairs: list[tuple[str, str]] = []
    for i, src in enumerate(paths):
        stem, ext = _split_name(src)
        pairs.append((src, os.path.join(os.path.dirname(src), new_stem(stem, src, i) + ext)))
    return pairs


def replace_text(stem: str, find: str, repl: str, regex: bool, ignore_case: bool) -> str:
    """Replace *find* in *stem*. Raises re.error for an invalid pattern."""
    if not find:
        return stem
    pattern = find if regex else re.escape(find)
    if not regex:
        repl = repl.replace("\\", "\\\\")  # plain text: no group references
    return re.sub(pattern, repl, stem, flags=re.IGNORECASE if ignore_case else 0)


def change_case(stem: str, mode: str) -> str:
    if mode == "upper":
        return stem.upper()
    if mode == "lower":
        return stem.lower()
    return stem.title()


def date_prefix(stem: str, timestamp: float, fmt: str) -> str:
    return time.strftime(fmt, time.localtime(timestamp)) + stem


def execute_batch_rename(pairs: list[tuple[str, str]]) -> tuple[int, list[str]]:
    """Rename in two phases (source → temp → target) so targets that overlap
    other sources in the same batch (e.g. shifting sequence numbers) never collide.

    Returns (success_count, error_messages).
    """
    staged: list[tuple[str, str, str]] = []  # (tmp, dst, src)
    for i, (src, dst) in enumerate(pairs):
        tmp = f"{src}.__batchtmp{i}__"
        while os.path.exists(tmp):
            tmp += "x"
        try:
            os.rename(src, tmp)
        except OSError as e:
            # Roll back everything already staged and abort
            for done_tmp, _, done_src in staged:
                try:
                    os.rename(done_tmp, done_src)
                except OSError:
                    pass
            return 0, [f"{os.path.basename(src)}: {e}"]
        staged.append((tmp, dst, src))

    success = 0
    errors: list[str] = []
    for tmp, dst, src in staged:
        try:
            os.rename(tmp, dst)
            success += 1
        except OSError as e:
            errors.append(f"{os.path.basename(src)}: {e}")
            try:
                os.rename(tmp, src)
            except OSError:
                errors.append(f"無法還原：{os.path.basename(src)}")
    return success, errors


class BatchRenameDialog(QDialog):
    """Pick a rename mode, see a live preview, OK renames the changed items."""

    _PREVIEW_LIMIT = 12

    def __init__(self, paths: list[str], parent=None):
        super().__init__(parent)
        self._paths = paths
        self.setWindowTitle(f"批次重新命名（{len(paths)} 個項目）")
        self.setMinimumWidth(520)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._mode = QComboBox()
        for label in ("加上序號", "取代文字", "大小寫轉換", "加日期前綴"):
            self._mode.addItem(label)
        form.addRow("方式：", self._mode)
        layout.addLayout(form)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_sequence(paths))
        self._stack.addWidget(self._build_replace())
        self._stack.addWidget(self._build_case())
        self._stack.addWidget(self._build_date())
        self._mode.currentIndexChanged.connect(self._stack.setCurrentIndex)
        self._mode.currentIndexChanged.connect(self._update_preview)
        layout.addWidget(self._stack)

        note = QLabel("只改主檔名，副檔名保留不變。")
        note.setObjectName("dimText")
        layout.addWidget(note)

        layout.addWidget(QLabel("預覽："))
        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setMinimumHeight(170)
        layout.addWidget(self._preview)

        self._hint = QLabel("")
        self._hint.setObjectName("errorHint")
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        self._name_edit.setFocus()
        self._name_edit.selectAll()
        self._update_preview()

    # --- option pages ---

    def _build_sequence(self, paths: list[str]) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        self._name_edit = QLineEdit(_split_name(paths[0])[0])
        self._name_edit.setPlaceholderText("序號會自動加在後面")
        form.addRow("新名稱：", self._name_edit)
        self._start_spin = QSpinBox()
        self._start_spin.setRange(0, 999999)
        self._start_spin.setValue(1)
        form.addRow("起始序號：", self._start_spin)
        self._digits_spin = QSpinBox()
        self._digits_spin.setRange(1, 6)
        self._digits_spin.setValue(max(2, len(str(len(paths)))))
        form.addRow("序號位數：", self._digits_spin)
        for w in (self._start_spin, self._digits_spin):
            w.valueChanged.connect(self._update_preview)
        self._name_edit.textChanged.connect(self._update_preview)
        return page

    def _build_replace(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        self._find_edit = QLineEdit()
        self._repl_edit = QLineEdit()
        self._repl_edit.setPlaceholderText("留空表示刪除找到的文字")
        self._regex_box = QCheckBox("使用正規表示式（取代文字可用 \\1 引用群組）")
        self._icase_box = QCheckBox("不分大小寫")
        form.addRow("尋找：", self._find_edit)
        form.addRow("取代為：", self._repl_edit)
        form.addRow("", self._regex_box)
        form.addRow("", self._icase_box)
        for w in (self._find_edit, self._repl_edit):
            w.textChanged.connect(self._update_preview)
        for w in (self._regex_box, self._icase_box):
            w.toggled.connect(self._update_preview)
        return page

    def _build_case(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        self._case_box = QComboBox()
        for value, label in CASE_MODES:
            self._case_box.addItem(label, value)
        self._case_box.currentIndexChanged.connect(self._update_preview)
        form.addRow("轉換為：", self._case_box)
        return page

    def _build_date(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        self._date_fmt = QComboBox()
        for fmt, example in DATE_FORMATS:
            self._date_fmt.addItem(example, fmt)
        self._date_source = QComboBox()
        self._date_source.addItem("檔案修改日期", "modified")
        self._date_source.addItem("今天", "today")
        for w in (self._date_fmt, self._date_source):
            w.currentIndexChanged.connect(self._update_preview)
        form.addRow("格式：", self._date_fmt)
        form.addRow("日期來源：", self._date_source)
        return page

    # --- pairs / validation ---

    def _all_pairs(self) -> list[tuple[str, str]]:
        """Pairs for every selected item (unchanged ones included). May raise re.error."""
        mode = self._mode.currentIndex()
        if mode == 0:
            return build_rename_pairs(
                self._paths,
                self._name_edit.text().strip(),
                self._start_spin.value(),
                self._digits_spin.value(),
            )
        if mode == 1:
            find, repl = self._find_edit.text(), self._repl_edit.text()
            regex, icase = self._regex_box.isChecked(), self._icase_box.isChecked()
            return build_transform_pairs(
                self._paths, lambda stem, _p, _i: replace_text(stem, find, repl, regex, icase)
            )
        if mode == 2:
            case = self._case_box.currentData()
            return build_transform_pairs(self._paths, lambda stem, _p, _i: change_case(stem, case))
        fmt = self._date_fmt.currentData()
        today = time.time()
        use_today = self._date_source.currentData() == "today"
        return build_transform_pairs(
            self._paths,
            lambda stem, p, _i: date_prefix(stem, today if use_today else os.path.getmtime(p), fmt),
        )

    def rename_pairs(self) -> list[tuple[str, str]]:
        """Only the items whose name actually changes."""
        return [(s, d) for s, d in self._all_pairs() if s != d]

    def _validate(self, pairs: list[tuple[str, str]]) -> str:
        """Return an error message, or empty string if the new names are usable."""
        if self._mode.currentIndex() == 0 and not self._name_edit.text().strip():
            return "請輸入新名稱"
        if not pairs:
            return "沒有檔名需要變更"
        for _, dst in pairs:
            name = os.path.basename(dst)
            if not name.strip(". "):
                return "有項目的新名稱是空的"
            bad = sorted(set(name) & _INVALID_CHARS)
            if bad:
                return "名稱不可包含字元：" + " ".join(bad)
        # Two items in the batch must not end up with the same name
        targets = [os.path.normcase(d) for _, d in self._all_pairs()]
        if len(set(targets)) != len(targets):
            return "有多個項目會變成同一個名稱"
        return ""

    def _update_preview(self, *_):
        try:
            pairs = self.rename_pairs()
            error = self._validate(pairs)
        except re.error as e:
            pairs, error = [], f"正規表示式錯誤：{e}"
        except OSError as e:
            pairs, error = [], f"無法讀取檔案日期：{e}"
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not error)
        self._hint.setText(error)
        lines = [f"{os.path.basename(s)}  →  {os.path.basename(d)}" for s, d in pairs]
        if len(lines) > self._PREVIEW_LIMIT:
            lines = lines[: self._PREVIEW_LIMIT - 1] + ["⋮", lines[-1]]
        if pairs:
            lines.insert(0, f"將變更 {len(pairs)} / {len(self._paths)} 個項目：")
        self._preview.setPlainText("\n".join(lines))

    def accept(self):
        # Block target names that collide with files outside this batch
        pairs = self.rename_pairs()
        sources = {os.path.normcase(os.path.normpath(s)) for s in self._paths}
        conflicts = [
            os.path.basename(dst)
            for _, dst in pairs
            if os.path.exists(dst) and os.path.normcase(os.path.normpath(dst)) not in sources
        ]
        if conflicts:
            QMessageBox.warning(
                self,
                "批次重新命名",
                "以下名稱與現有檔案衝突，請改用其他名稱：\n" + "\n".join(conflicts[:8]),
            )
            return
        super().accept()
