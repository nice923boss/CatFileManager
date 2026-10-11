"""Tests for external-app launching error handling in FilePanel.

Reproduces and guards against the two log-spamming failures:

  * WinError 267 (NotADirectoryError) — a subprocess launched with a ``cwd``
    that points at a file (or invalid directory). The launchers must catch it
    and report via ``status_message`` instead of letting it reach the log.
  * WinError 1223 (ERROR_CANCELLED) — the user dismissed a UAC / elevation
    prompt. This is a benign cancellation and must read as "已取消".

It also pins the registry-command path assembly so argv[0] no longer keeps the
literal quotes that ``shlex.split(..., posix=False)`` leaves behind.
"""

import os
import shlex
import subprocess
import sys

import pytest

# Make the project root importable when pytest is run from anywhere.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from panel_actions import (  # noqa: E402
    FilePanelActionsMixin,
    _format_launch_error,
    _split_command,
)


class _StubSignal:
    """Stand-in for a Qt ``Signal`` that records emitted messages."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def emit(self, msg: str) -> None:
        self.messages.append(msg)


class _StubHost(FilePanelActionsMixin):
    """Minimal host exposing only what the launcher methods touch."""

    def __init__(self) -> None:
        self.status_message = _StubSignal()


def _os_error(winerror: int, msg: str = "boom") -> OSError:
    """Build an OSError carrying a Windows error code, portably."""
    exc = OSError(msg)
    exc.winerror = winerror
    return exc


# --- _format_launch_error -------------------------------------------------


def test_format_launch_error_treats_1223_as_cancel():
    assert _format_launch_error(_os_error(1223)) == "已取消"


def test_format_launch_error_reports_267_as_failure():
    msg = _format_launch_error(_os_error(267, "目錄名稱無效"))
    assert msg.startswith("開啟失敗：")
    assert "目錄名稱無效" in msg


def test_format_launch_error_handles_non_oserror():
    assert _format_launch_error(ValueError("bad quote")).startswith("開啟失敗：")


# --- _split_command (registry path assembly) ------------------------------


def test_shlex_posix_false_retains_quotes_root_cause():
    # Document the defect: posix=False keeps the wrapping quotes, so argv[0]
    # would be an invalid path that still contains '"'.
    raw = shlex.split(r'"C:\App\a.exe" "%1"', posix=False)
    assert raw[0] == r'"C:\App\a.exe"'


def test_split_command_strips_wrapping_quotes():
    parts = _split_command(r'"C:\App\a.exe" "%1"')
    assert parts == [r"C:\App\a.exe", "%1"]
    assert all('"' not in p for p in parts)


# --- _open_with builds a clean argv ---------------------------------------


def test_open_with_quoted_template_builds_clean_argv(monkeypatch):
    captured: list[list[str]] = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, *a, **k: captured.append(args))

    host = _StubHost()
    host._open_with(r'"C:\App\a.exe" "%1"', r"C:\Users\My File.txt")

    assert captured, "Popen was not called"
    argv = captured[0]
    assert argv[0] == r"C:\App\a.exe"  # no literal quotes
    assert argv[1] == os.path.normpath(r"C:\Users\My File.txt")  # spaces intact, one arg
    assert host.status_message.messages == []


def test_open_with_template_without_placeholder_appends_file(monkeypatch):
    captured: list[list[str]] = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, *a, **k: captured.append(args))

    host = _StubHost()
    host._open_with("notepad.exe", r"C:\x.txt")

    assert captured[0] == ["notepad.exe", os.path.normpath(r"C:\x.txt")]


# --- launchers swallow failures instead of raising ------------------------


@pytest.mark.parametrize("winerror,expected", [(267, "開啟失敗："), (1223, "已取消")])
def test_open_with_dialog_reports_instead_of_raising(monkeypatch, winerror, expected):
    def _boom(*a, **k):
        raise _os_error(winerror, "目錄名稱無效")

    monkeypatch.setattr(subprocess, "Popen", _boom)
    host = _StubHost()

    host._open_with_dialog(r"C:\some\file.txt")  # must not raise

    assert host.status_message.messages
    assert host.status_message.messages[0].startswith(expected)


def test_open_cmd_reports_instead_of_raising(monkeypatch):
    def _boom(*a, **k):
        raise _os_error(267, "目錄名稱無效")

    monkeypatch.setattr(subprocess, "Popen", _boom)
    host = _StubHost()

    host._open_cmd(r"C:\some\dir")  # must not raise

    assert host.status_message.messages[0].startswith("開啟失敗：")


def test_open_with_user_cancel_reports_cancelled(monkeypatch):
    def _boom(*a, **k):
        raise _os_error(1223)

    monkeypatch.setattr(subprocess, "Popen", _boom)
    host = _StubHost()

    host._open_with("notepad.exe", r"C:\x.txt")

    assert host.status_message.messages == ["已取消"]


# --- root-cause reproduction (real subprocess) ----------------------------


@pytest.mark.skipif(os.name != "nt", reason="WinError 267 is Windows-specific")
def test_winerror267_root_cause_is_file_as_cwd(tmp_path):
    """A cwd pointing at a file is the actual source of WinError 267."""
    not_a_dir = tmp_path / "installer.exe"
    not_a_dir.write_bytes(b"")

    with pytest.raises(NotADirectoryError) as excinfo:
        subprocess.Popen(["cmd", "/c", "exit"], cwd=str(not_a_dir))

    assert excinfo.value.winerror == 267
