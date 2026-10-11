"""Batch rename — rename multiple files to a common base name with sequence numbers."""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QSpinBox,
    QDialogButtonBox, QPlainTextEdit, QMessageBox,
)

_INVALID_CHARS = set('<>:"/\\|?*')

# Trailing characters that already separate name from number, so no "_" is added.
_SEPARATOR_TAIL = ("_", "-", " ", ".")


def build_rename_pairs(
    paths: list[str], base: str, start: int, digits: int,
) -> list[tuple[str, str]]:
    """Return (source, target) pairs renaming *paths* to base_NN, keeping extensions."""
    sep = "" if base.endswith(_SEPARATOR_TAIL) else "_"
    pairs: list[tuple[str, str]] = []
    for i, src in enumerate(paths):
        ext = "" if os.path.isdir(src) else os.path.splitext(src)[1]
        new_name = f"{base}{sep}{start + i:0{digits}d}{ext}"
        pairs.append((src, os.path.join(os.path.dirname(src), new_name)))
    return pairs


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
    """Ask for a base name + start number + digits, with live preview."""

    _PREVIEW_LIMIT = 8

    def __init__(self, paths: list[str], parent=None):
        super().__init__(parent)
        self._paths = paths
        self.setWindowTitle(f"批次重新命名（{len(paths)} 個項目）")
        self.setMinimumWidth(460)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self.setStyleSheet(
            "QSpinBox { background-color: #3c3c3c; color: #cccccc;"
            "  border: 1px solid #3e3e3e; padding: 2px 6px; }"
            "QPlainTextEdit { background-color: #252526; color: #cccccc;"
            "  border: 1px solid #3e3e3e; }"
        )

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("新名稱（序號自動加在後面）："))
        first_base = os.path.splitext(os.path.basename(paths[0]))[0]
        self._name_edit = QLineEdit(first_base)
        layout.addWidget(self._name_edit)

        row = QHBoxLayout()
        row.addWidget(QLabel("起始序號："))
        self._start_spin = QSpinBox()
        self._start_spin.setRange(0, 999999)
        self._start_spin.setValue(1)
        row.addWidget(self._start_spin)
        row.addSpacing(12)
        row.addWidget(QLabel("序號位數："))
        self._digits_spin = QSpinBox()
        self._digits_spin.setRange(1, 6)
        self._digits_spin.setValue(max(2, len(str(len(paths)))))
        row.addWidget(self._digits_spin)
        row.addStretch()
        layout.addLayout(row)

        layout.addWidget(QLabel("預覽："))
        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setMaximumHeight(150)
        layout.addWidget(self._preview)

        self._hint = QLabel("")
        self._hint.setStyleSheet("color: #d9534f;")
        layout.addWidget(self._hint)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        self._name_edit.textChanged.connect(self._update_preview)
        self._start_spin.valueChanged.connect(self._update_preview)
        self._digits_spin.valueChanged.connect(self._update_preview)

        self._name_edit.setFocus()
        self._name_edit.selectAll()
        self._update_preview()

    def rename_pairs(self) -> list[tuple[str, str]]:
        return build_rename_pairs(
            self._paths,
            self._name_edit.text().strip(),
            self._start_spin.value(),
            self._digits_spin.value(),
        )

    def _validate(self) -> str:
        """Return an error message, or empty string if the name is usable."""
        base = self._name_edit.text().strip()
        if not base:
            return "請輸入新名稱"
        bad = sorted(set(base) & _INVALID_CHARS)
        if bad:
            return "名稱不可包含字元：" + " ".join(bad)
        return ""

    def _update_preview(self):
        error = self._validate()
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not error)
        self._hint.setText(error)
        if error:
            self._preview.setPlainText("")
            return
        names = [os.path.basename(dst) for _, dst in self.rename_pairs()]
        if len(names) > self._PREVIEW_LIMIT:
            names = names[: self._PREVIEW_LIMIT - 1] + ["⋮", names[-1]]
        self._preview.setPlainText("\n".join(names))

    def accept(self):
        # Block target names that collide with files outside this batch
        pairs = self.rename_pairs()
        sources = {os.path.normcase(os.path.normpath(s)) for s, _ in pairs}
        conflicts = [
            os.path.basename(dst) for _, dst in pairs
            if os.path.exists(dst)
            and os.path.normcase(os.path.normpath(dst)) not in sources
        ]
        if conflicts:
            QMessageBox.warning(
                self,
                "批次重新命名",
                "以下名稱與現有檔案衝突，請改用其他名稱或序號：\n"
                + "\n".join(conflicts[:8]),
            )
            return
        super().accept()
