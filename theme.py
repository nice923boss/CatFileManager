"""Dark / light stylesheets built from one template (Q-Dir-like look).

Widgets that used to carry inline colours now use object names
(``#panelHeader``, ``#breadcrumb`` …) so both themes style them from here.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette

PALETTES = {
    "dark": {
        "bg": "#1e1e1e",
        "panel": "#252526",
        "header": "#2d2d2d",
        "input": "#3c3c3c",
        "border": "#3e3e3e",
        "text": "#cccccc",
        "text_dim": "#888888",
        "accent": "#007acc",
        "link": "#3794ff",
        "select": "#264f78",
        "select_text": "#ffffff",
        "hover": "#2a2d2e",
        "btn_hover": "#505050",
        "menu_border": "#454545",
        "scroll": "#424242",
        "scroll_hover": "#555555",
        "active_header": "#264f78",
        "active_header_text": "#ffffff",
        "fav": "#e8b84b",
        "error": "#d9534f",
        # Name colours by file category (A11) and for broken links (G05)
        "image": "#4ec9b0",
        "video": "#c586c0",
        "archive": "#ce9178",
        "exec": "#dcdcaa",
        "broken": "#f14c4c",
    },
    "light": {
        "bg": "#f3f3f3",
        "panel": "#ffffff",
        "header": "#e6e6e6",
        "input": "#ffffff",
        "border": "#c8c8c8",
        "text": "#1e1e1e",
        "text_dim": "#6e6e6e",
        "accent": "#007acc",
        "link": "#005a9e",
        "select": "#cce4f7",
        "select_text": "#000000",
        "hover": "#e5f3ff",
        "btn_hover": "#dcdcdc",
        "menu_border": "#c8c8c8",
        "scroll": "#c1c1c1",
        "scroll_hover": "#a8a8a8",
        "active_header": "#007acc",
        "active_header_text": "#ffffff",
        "fav": "#b07800",
        "error": "#c72e2e",
        "image": "#16825d",
        "video": "#8f3f9e",
        "archive": "#a3501f",
        "exec": "#7a6500",
        "broken": "#c72e2e",
    },
}

_TEMPLATE = """
QMainWindow, QDialog {{ background-color: {bg}; }}
QWidget {{ color: {text}; }}
QSplitter {{ background-color: {bg}; }}
QSplitter::handle {{ background-color: {border}; }}
QSplitter::handle:horizontal {{ width: 3px; }}
QSplitter::handle:vertical {{ height: 3px; }}

QTreeView, QListView, QListWidget, QTableWidget {{
    background-color: {panel};
    color: {text};
    border: 1px solid {border};
    font-size: {font_size}px;
    {font_family}
    outline: none;
}}
QTreeView::item {{ padding: 3px 4px; }}
QTreeView::item:hover, QListView::item:hover {{ background-color: {hover}; }}
QTreeView::item:selected, QListView::item:selected, QListWidget::item:selected {{
    background-color: {select};
    color: {select_text};
}}
QTreeView::branch:has-siblings:!adjoins-item,
QTreeView::branch:has-siblings:adjoins-item,
QTreeView::branch:!has-children:!has-siblings:adjoins-item {{ border-image: none; }}
QTreeView::branch:has-children:!has-siblings:closed,
QTreeView::branch:closed:has-children:has-siblings,
QTreeView::branch:open:has-children:!has-siblings,
QTreeView::branch:open:has-children:has-siblings {{ image: none; }}

QHeaderView {{ background-color: {panel}; color: {text}; border: none; font-size: 12px; }}
QHeaderView::section {{
    background-color: {header};
    color: {text};
    border: 1px solid {border};
    padding: 4px 8px;
}}
QHeaderView::section:hover {{ background-color: {border}; }}

QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QKeySequenceEdit {{
    background-color: {input};
    color: {text};
    border: 1px solid {border};
    padding: 3px 6px;
    font-size: 13px;
    selection-background-color: {select};
    selection-color: {select_text};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 1px solid {accent}; }}
QComboBox QAbstractItemView {{
    background-color: {input};
    color: {text};
    selection-background-color: {select};
    selection-color: {select_text};
}}

QPushButton {{
    background-color: {input};
    color: {text};
    border: 1px solid {border};
    padding: 4px 12px;
    font-size: 12px;
    min-width: 28px;
}}
QPushButton:hover {{ background-color: {btn_hover}; }}
QPushButton:pressed {{ background-color: {select}; }}
QPushButton:disabled {{ color: {text_dim}; }}

QLabel {{ color: {text}; font-size: 12px; }}
QCheckBox, QRadioButton {{ color: {text}; }}
QGroupBox {{ color: {text}; border: 1px solid {border}; margin-top: 10px; padding-top: 6px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; }}
QTabWidget::pane {{ border: 1px solid {border}; }}
QTabBar::tab {{ background: {header}; color: {text}; padding: 6px 14px; border: 1px solid {border}; }}
QTabBar::tab:selected {{ background: {select}; color: {select_text}; }}

QMenuBar {{ background-color: {header}; color: {text}; }}
QMenuBar::item:selected {{ background-color: {select}; color: {select_text}; }}
QMenu {{
    background-color: {header};
    color: {text};
    border: 1px solid {menu_border};
    padding: 4px 0px;
    font-size: 13px;
}}
QMenu::item {{ padding: 6px 30px 6px 20px; }}
QMenu::item:selected {{ background-color: {select}; color: {select_text}; }}
QMenu::item:disabled {{ color: {text_dim}; }}
QMenu::separator {{ height: 1px; background-color: {menu_border}; margin: 4px 10px; }}

QScrollBar:vertical {{ background-color: {bg}; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{
    background-color: {scroll}; min-height: 20px; border-radius: 3px; margin: 2px;
}}
QScrollBar::handle:vertical:hover {{ background-color: {scroll_hover}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background-color: {bg}; height: 12px; margin: 0; }}
QScrollBar::handle:horizontal {{
    background-color: {scroll}; min-width: 20px; border-radius: 3px; margin: 2px;
}}
QScrollBar::handle:horizontal:hover {{ background-color: {scroll_hover}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

QStatusBar {{ background-color: {accent}; color: #ffffff; font-size: 12px; }}
QStatusBar QLabel {{ color: #ffffff; }}
QToolTip {{ background-color: {header}; color: {text}; border: 1px solid {menu_border}; }}

/* --- Named widgets (formerly inline styles) --- */
QLabel#panelHeader {{
    background-color: {header}; color: {text_dim};
    padding: 4px; font-size: 12px; font-weight: bold;
}}
QLabel#panelHeader[active="true"] {{
    background-color: {active_header}; color: {active_header_text};
}}
QLabel#sectionHeader {{
    background-color: {header}; color: {text};
    padding: 6px 4px; font-size: 13px; font-weight: bold;
}}
QLabel#favHeader {{
    background-color: {header}; color: {fav};
    padding: 6px 4px; font-size: 13px; font-weight: bold;
}}
QLabel#recycleLabel {{
    background-color: {panel}; color: {text}; padding: 8px 4px; font-size: 13px;
}}
QListWidget#favorites {{ font-size: {fav_size}px; }}
QListWidget#favorites::item {{ padding: 4px 2px; }}
QWidget#breadcrumb {{ background-color: {input}; border: 1px solid {border}; }}
QScrollArea#crumbScroll, QWidget#crumbContainer {{ background: transparent; border: none; }}
QLabel#crumbSep {{ color: {text_dim}; padding: 0 2px; font-size: 13px; }}
QPushButton#crumbBtn {{
    color: {text}; background: transparent; padding: 2px 4px; font-size: 12px; border: none;
}}
QPushButton#crumbBtn:hover {{ background-color: {btn_hover}; border-radius: 3px; }}
QLineEdit#breadcrumbEdit {{
    background-color: {panel}; color: {text}; border: 1px solid {accent};
    font-size: 11px; padding: 1px 4px;
}}
QLineEdit#breadcrumbEdit[error="true"] {{ border: 1px solid {error}; }}
QWidget#searchBar {{ background-color: {header}; border: 1px solid {accent}; }}
QLineEdit[error="true"] {{ border: 1px solid {error}; }}
QPushButton#historyItem {{
    text-align: left; border: none; background: transparent; padding: 3px 8px; min-width: 160px;
}}
QPushButton#historyItem:hover {{ background-color: {select}; color: {select_text}; }}
QLabel#searchCount {{ color: {text_dim}; }}
QLabel#errorHint {{ color: {error}; }}
QLabel#dimText {{ color: {text_dim}; }}

/* Quick preview lightbox: dark backdrop in both themes */
QWidget#quickPreview QLabel#previewTitle {{ color: #f0f0f0; font-size: 14px; font-weight: bold; }}
QWidget#quickPreview QLabel#previewDim {{ color: #a0a0a0; font-size: 12px; }}
QPushButton#previewClose {{
    color: #f0f0f0; background: transparent; border: none; font-size: 16px; padding: 2px 8px;
}}
QPushButton#previewClose:hover {{ background-color: rgba(255, 255, 255, 40); border-radius: 3px; }}
QPdfView#previewPdf {{ background: transparent; border: none; }}
QTextBrowser#previewText {{
    background-color: {panel}; color: {text}; border: none; font-size: {font_size}px;
}}
QPlainTextEdit#previewCode {{
    background-color: {panel}; color: {text}; border: none; padding: 12px;
    font-family: Consolas, "Cascadia Mono", monospace; font-size: {font_size}px;
}}
QWidget#quickPreview QLabel#previewNote {{ color: #a0a0a0; font-size: 96px; }}
QPushButton#previewPlay {{
    color: #f0f0f0; background: transparent; border: none; font-size: 14px; padding: 2px 8px;
}}
QPushButton#previewPlay:hover {{ background-color: rgba(255, 255, 255, 40); border-radius: 3px; }}
QSlider#previewSeek::groove:horizontal {{
    height: 4px; background: rgba(255, 255, 255, 60); border-radius: 2px;
}}
QSlider#previewSeek::sub-page:horizontal {{ background: {accent}; border-radius: 2px; }}
QSlider#previewSeek::handle:horizontal {{
    background: #f0f0f0; width: 12px; margin: -4px 0; border-radius: 6px;
}}
"""


def resolve_theme(name: str) -> str:
    """Map "system" to the current Windows colour scheme."""
    if name == "system":
        scheme = QGuiApplication.styleHints().colorScheme()
        return "light" if scheme == Qt.ColorScheme.Light else "dark"
    return name if name in PALETTES else "dark"


def build_stylesheet(theme: str, font_family: str = "", font_size: int = 13) -> str:
    pal = PALETTES[resolve_theme(theme)]
    family = f'font-family: "{font_family}";' if font_family else ""
    return _TEMPLATE.format(**pal, font_size=font_size, font_family=family, fav_size=font_size + 1)


def build_palette(theme: str) -> QPalette:
    """Base QPalette so Fusion-drawn parts (checkbox marks, dialogs) match the theme."""
    pal = PALETTES[resolve_theme(theme)]
    qp = QPalette()
    roles = {
        QPalette.ColorRole.Window: pal["bg"],
        QPalette.ColorRole.WindowText: pal["text"],
        QPalette.ColorRole.Base: pal["panel"],
        QPalette.ColorRole.AlternateBase: pal["header"],
        QPalette.ColorRole.Text: pal["text"],
        QPalette.ColorRole.Button: pal["input"],
        QPalette.ColorRole.ButtonText: pal["text"],
        QPalette.ColorRole.Highlight: pal["select"],
        QPalette.ColorRole.HighlightedText: pal["select_text"],
        QPalette.ColorRole.ToolTipBase: pal["header"],
        QPalette.ColorRole.ToolTipText: pal["text"],
        QPalette.ColorRole.PlaceholderText: pal["text_dim"],
        QPalette.ColorRole.Link: pal["link"],
        QPalette.ColorRole.LinkVisited: pal["link"],
    }
    for role, color in roles.items():
        qp.setColor(role, QColor(color))
    return qp


def colors(theme: str) -> dict[str, str]:
    return PALETTES[resolve_theme(theme)]
