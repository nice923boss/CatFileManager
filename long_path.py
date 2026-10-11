"""Extended-length path helper (J07).

Win32 file APIs reject paths over 260 characters unless they carry the
``\\\\?\\`` prefix. Wrap every path handed to os/shutil in the copy engine
and the directory scanner with ``lp()``; strip it with ``unlp()`` before
showing a path to the user.
"""

import os

_PREFIX = "\\\\?\\"
_UNC_PREFIX = "\\\\?\\UNC\\"


def lp(path: str) -> str:
    if not path or path.startswith(_PREFIX):
        return path
    path = os.path.abspath(path)
    if path.startswith("\\\\"):  # \\server\share\...
        return _UNC_PREFIX + path[2:]
    return _PREFIX + path


def unlp(path: str) -> str:
    if path.startswith(_UNC_PREFIX):
        return "\\\\" + path[len(_UNC_PREFIX) :]
    if path.startswith(_PREFIX):
        return path[len(_PREFIX) :]
    return path
