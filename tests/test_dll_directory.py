"""The frozen app must not hand PyInstaller's _internal DLL directory to child processes.

PyInstaller's bootloader calls SetDllDirectoryW(<_internal>); every process started
from the app inherited it and loaded the bundled VCRUNTIME140.dll ahead of System32
(locking dist/ against rebuilds).
"""

import ctypes
import subprocess
import sys

import pytest

from shell_utils import reset_inherited_dll_directory

_kernel32 = ctypes.WinDLL("kernel32")

_CHILD_PRINTS_DLL_DIRECTORY = (
    "import ctypes; b = ctypes.create_unicode_buffer(1024); "
    "ctypes.windll.kernel32.GetDllDirectoryW(1024, b); print(b.value)"
)


def _dll_directory() -> str:
    buf = ctypes.create_unicode_buffer(1024)
    _kernel32.GetDllDirectoryW(1024, buf)
    return buf.value


def _child_dll_directory() -> str:
    out = subprocess.run(
        [sys.executable, "-c", _CHILD_PRINTS_DLL_DIRECTORY], capture_output=True, text=True
    )
    return out.stdout.strip()


@pytest.fixture
def bootloader_dll_directory(tmp_path):
    """Simulate the bootloader's SetDllDirectoryW call; restore the original afterwards."""
    original = _dll_directory()
    assert _kernel32.SetDllDirectoryW(str(tmp_path))
    yield str(tmp_path)
    _kernel32.SetDllDirectoryW(original or None)


def test_frozen_app_children_do_not_inherit_dll_directory(bootloader_dll_directory, monkeypatch):
    assert _child_dll_directory() == bootloader_dll_directory  # the bug: children inherit it
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    reset_inherited_dll_directory()

    assert _dll_directory() == ""
    assert _child_dll_directory() == ""


def test_source_run_leaves_dll_directory_alone(bootloader_dll_directory, monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)

    reset_inherited_dll_directory()

    assert _dll_directory() == bootloader_dll_directory
