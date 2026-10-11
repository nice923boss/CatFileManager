"""Settings manager — persist window state, panel paths and user preferences to JSON."""

import json
import logging
import os

SETTINGS_DIR = os.path.join(os.path.expanduser("~"), ".quad-file-manager")
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")

log = logging.getLogger(__name__)

# User-editable preferences (edited through the Settings dialog).
DEFAULT_PREFS = {
    "show_hidden": False,
    "show_extensions": True,
    "color_by_type": True,
    "theme": "dark",  # "dark" | "light" | "system"
    "font_family": "",  # "" = system default
    "font_size": 13,
    "startup_mode": "last",  # "last" | "fixed"
    "startup_paths": ["", "", "", ""],
    "layout": "4",  # "1" | "2h" | "2v" | "3" | "4"
    "verify_after_copy": False,
    "shortcuts": {},  # action id -> key sequence override
    "context_menu_hidden": [],  # context-menu item ids the user turned off
    "context_menu_order": [],  # context-menu item ids in the user's order
    "search_history": [],
    "everything_path": "",  # es.exe override; "" = auto-detect
}

DEFAULT_SETTINGS = {
    "window": {
        "x": 100,
        "y": 100,
        "width": 1400,
        "height": 800,
    },
    "panels": {
        "0": os.path.expanduser("~"),
        "1": os.path.expanduser("~"),
        "2": os.path.expanduser("~"),
        "3": os.path.expanduser("~"),
    },
    "panel_views": {},  # panel id -> {"widths": [...], "sort": [col, order], "view": "list"}
    "splitter_main": [],
    "splitter_vertical": [],
    "splitter_top": [],
    "splitter_bottom": [],
    "active_panel": 0,
    "favorites": [],
    "prefs": DEFAULT_PREFS,
}


def _defaults() -> dict:
    # Deep copy so callers can never mutate the module-level defaults.
    return json.loads(json.dumps(DEFAULT_SETTINGS))


def load_settings() -> dict:
    merged = _defaults()
    if not os.path.exists(SETTINGS_FILE):
        return merged
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.error("Cannot read settings %s: %s", SETTINGS_FILE, e)
        return merged
    prefs = {**merged["prefs"], **data.get("prefs", {})}
    merged.update(data)
    merged["prefs"] = prefs
    if not isinstance(merged.get("panels"), dict):
        merged["panels"] = _defaults()["panels"]
    return merged


def save_settings(settings: dict) -> str | None:
    """Write settings atomically. Returns None on success, else an error message."""
    try:
        os.makedirs(SETTINGS_DIR, exist_ok=True)
        tmp_file = SETTINGS_FILE + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        os.replace(tmp_file, SETTINGS_FILE)  # atomic; prevents corruption on crash
    except OSError as e:
        log.error("Cannot save settings %s: %s", SETTINGS_FILE, e)
        return str(e)
    return None
