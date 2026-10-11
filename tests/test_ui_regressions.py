"""Regressions found while hand-testing the packaged v1.1.0 build."""

from PySide6.QtWidgets import QDialog, QPushButton

from panel_widgets import BreadcrumbBar
from panels import FilePanel
from theme import build_stylesheet


def test_long_breadcrumb_does_not_widen_panel(qapp):
    bar = BreadcrumbBar()
    bar.setStyleSheet(build_stylesheet("dark"))  # QPushButton min-width rule applies
    deep = "C:\\" + "\\".join(f"很長的資料夾名稱_{i:02d}" for i in range(20))
    bar.set_path(deep)
    assert bar.minimumSizeHint().width() < 400

    bar.resize(400, 28)
    bar.show()
    qapp.processEvents()
    hbar = bar._crumb_scroll.horizontalScrollBar()
    assert hbar.maximum() > 0
    assert hbar.value() == hbar.maximum()  # current folder (rightmost) stays visible
    for btn in bar.findChildren(QPushButton):
        assert btn.width() >= btn.sizeHint().width(), btn.text()  # names never squeezed
    bar.close()


def _panel_with_pending_rename(tmp_path, monkeypatch, selected):
    target = tmp_path / "a.txt"
    target.write_text("x")
    panel = FilePanel(0, None)
    calls: list[str] = []
    monkeypatch.setattr(panel, "_rename", calls.append)
    monkeypatch.setattr(panel, "_get_selected_paths", lambda: selected or [str(target)])
    panel._rename_pending_path = str(target)
    return panel, calls, str(target)


def test_pending_rename_fires_for_unchanged_selection(qapp, tmp_path, monkeypatch):
    panel, calls, target = _panel_with_pending_rename(tmp_path, monkeypatch, None)
    panel._on_rename_timer()
    assert calls == [target]


def test_pending_rename_skipped_after_selection_moves(qapp, tmp_path, monkeypatch):
    other = [str(tmp_path / "b.txt")]
    panel, calls, _ = _panel_with_pending_rename(tmp_path, monkeypatch, other)
    panel._on_rename_timer()
    assert calls == []


def test_pending_rename_skipped_while_dialog_open(qapp, tmp_path, monkeypatch):
    # e.g. Delete pressed right after the click: the confirmation is modal
    panel, calls, _ = _panel_with_pending_rename(tmp_path, monkeypatch, None)
    dlg = QDialog()
    dlg.setModal(True)
    dlg.show()
    qapp.processEvents()
    try:
        panel._on_rename_timer()
    finally:
        dlg.close()
    assert calls == []


def test_shortcut_action_cancels_pending_rename(qapp, tmp_path, monkeypatch):
    panel, _, _ = _panel_with_pending_rename(tmp_path, monkeypatch, None)
    panel._rename_timer.start()
    panel.run_action("refresh")
    assert not panel._rename_timer.isActive()
    assert panel._rename_pending_path is None
