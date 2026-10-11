"""Dark theme stylesheet similar to Q-Dir."""

DARK_THEME = """
QMainWindow {
    background-color: #1e1e1e;
}

QSplitter {
    background-color: #1e1e1e;
}

QSplitter::handle {
    background-color: #3e3e3e;
}

QSplitter::handle:horizontal {
    width: 3px;
}

QSplitter::handle:vertical {
    height: 3px;
}

QTreeView {
    background-color: #252526;
    color: #cccccc;
    border: 1px solid #3e3e3e;
    font-size: 13px;
    outline: none;
}

QTreeView::item {
    padding: 3px 4px;
}

QTreeView::item:hover {
    background-color: #2a2d2e;
}

QTreeView::item:selected {
    background-color: #264f78;
    color: #ffffff;
}

QTreeView::branch:has-siblings:!adjoins-item {
    border-image: none;
}

QTreeView::branch:has-siblings:adjoins-item {
    border-image: none;
}

QTreeView::branch:!has-children:!has-siblings:adjoins-item {
    border-image: none;
}

QTreeView::branch:has-children:!has-siblings:closed,
QTreeView::branch:closed:has-children:has-siblings {
    image: none;
}

QTreeView::branch:open:has-children:!has-siblings,
QTreeView::branch:open:has-children:has-siblings {
    image: none;
}

QHeaderView {
    background-color: #252526;
    color: #cccccc;
    border: none;
    font-size: 12px;
}

QHeaderView::section {
    background-color: #2d2d2d;
    color: #cccccc;
    border: 1px solid #3e3e3e;
    padding: 4px 8px;
}

QHeaderView::section:hover {
    background-color: #3e3e3e;
}

QLineEdit {
    background-color: #3c3c3c;
    color: #cccccc;
    border: 1px solid #3e3e3e;
    padding: 4px 8px;
    font-size: 13px;
    selection-background-color: #264f78;
}

QLineEdit:focus {
    border: 1px solid #007acc;
}

QPushButton {
    background-color: #3c3c3c;
    color: #cccccc;
    border: 1px solid #3e3e3e;
    padding: 4px 12px;
    font-size: 12px;
    min-width: 28px;
}

QPushButton:hover {
    background-color: #505050;
}

QPushButton:pressed {
    background-color: #264f78;
}

QLabel {
    color: #cccccc;
    font-size: 12px;
}

QMenu {
    background-color: #2d2d2d;
    color: #cccccc;
    border: 1px solid #454545;
    padding: 4px 0px;
    font-size: 13px;
}

QMenu::item {
    padding: 6px 30px 6px 20px;
}

QMenu::item:selected {
    background-color: #264f78;
}

QMenu::separator {
    height: 1px;
    background-color: #454545;
    margin: 4px 10px;
}

QScrollBar:vertical {
    background-color: #1e1e1e;
    width: 12px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background-color: #424242;
    min-height: 20px;
    border-radius: 3px;
    margin: 2px;
}

QScrollBar::handle:vertical:hover {
    background-color: #555555;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    background-color: #1e1e1e;
    height: 12px;
    margin: 0;
}

QScrollBar::handle:horizontal {
    background-color: #424242;
    min-width: 20px;
    border-radius: 3px;
    margin: 2px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #555555;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

QStatusBar {
    background-color: #007acc;
    color: #ffffff;
    font-size: 12px;
}
"""
