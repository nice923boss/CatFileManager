"""Settings manager — persist window state and panel paths to JSON."""

import json
import os

SETTINGS_DIR = os.path.join(os.path.expanduser("~"), ".quad-file-manager")
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")

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
    "splitter_main": [],
    "splitter_vertical": [],
    "splitter_top": [],
    "splitter_bottom": [],
    "active_panel": 0,
    "favorites": [],
}


def load_settings() -> dict:
    if not os.path.exists(SETTINGS_FILE):
        return dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = dict(DEFAULT_SETTINGS)
        merged.update(data)
        if "panels" not in merged or not isinstance(merged["panels"], dict):
            merged["panels"] = dict(DEFAULT_SETTINGS["panels"])
        return merged
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_SETTINGS)


def save_settings(settings: dict) -> None:
    try:
        os.makedirs(SETTINGS_DIR, exist_ok=True)
        tmp_file = SETTINGS_FILE + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        # Atomic rename to prevent corruption on crash
        if os.path.exists(SETTINGS_FILE):
            os.replace(tmp_file, SETTINGS_FILE)
        else:
            os.rename(tmp_file, SETTINGS_FILE)
    except OSError:
        # Silently ignore save failures (disk full, permissions, etc.)
        pass
