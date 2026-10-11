"""Undo stack for move, rename, copy and delete-to-recycle-bin (C02).

Recycle-bin restore reads the ``$I`` metadata files in ``X:\\$Recycle.Bin\\<SID>``
(they hold the original path) and renames the matching ``$R`` file back,
which is exactly what Explorer's "restore" does.
"""

import logging
import os
import shutil
import struct
import time
from typing import NamedTuple

from send2trash import send2trash

from copy_engine import same_drive
from long_path import lp

log = logging.getLogger(__name__)

_FILETIME_EPOCH = 116444736000000000  # 1601-01-01 -> 1970-01-01 in 100 ns


class UndoEntry(NamedTuple):
    label: str  # shown as "復原：<label>"
    # ("moved", original, new) | ("renamed", original, new)
    # ("created", path)        | ("trashed", original_path, deleted_at_epoch)
    records: list[tuple]


def _parse_info_file(path: str) -> tuple[str, float] | None:
    """(original path, deletion time) from a $I file (Vista/Win10 formats)."""
    try:
        with open(path, "rb") as f:
            data = f.read()
        version = struct.unpack_from("<q", data, 0)[0]
        filetime = struct.unpack_from("<q", data, 16)[0]
        if version == 2:
            length = struct.unpack_from("<i", data, 24)[0]
            original = data[28 : 28 + length * 2].decode("utf-16-le").rstrip("\0")
        else:
            original = data[24 : 24 + 520].decode("utf-16-le").split("\0", 1)[0]
        return original, (filetime - _FILETIME_EPOCH) / 1e7
    except (OSError, struct.error, UnicodeDecodeError):
        return None


def find_in_recycle_bin(original: str, deleted_after: float) -> tuple[str, str] | None:
    """($R path, $I path) of the newest bin item that was `original`, or None."""
    drive = os.path.splitdrive(os.path.abspath(original))[0]
    root = os.path.join(drive + os.sep, "$Recycle.Bin")
    want = os.path.normcase(os.path.abspath(original))
    best: tuple[float, str, str] | None = None
    try:
        sids = os.listdir(root)
    except OSError:
        return None
    for sid in sids:
        folder = os.path.join(root, sid)
        try:
            names = os.listdir(folder)
        except OSError:  # other users' bins are not readable
            continue
        for name in names:
            if not name.startswith("$I"):
                continue
            info = _parse_info_file(os.path.join(folder, name))
            if not info or os.path.normcase(info[0]) != want or info[1] < deleted_after - 2:
                continue
            if best is None or info[1] > best[0]:
                best = (info[1], os.path.join(folder, "$R" + name[2:]), os.path.join(folder, name))
    return (best[1], best[2]) if best else None


def restore_from_recycle_bin(original: str, deleted_after: float) -> None:
    found = find_in_recycle_bin(original, deleted_after)
    if not found:
        raise OSError(f"資源回收筒中找不到：{os.path.basename(original)}")
    r_path, i_path = found
    if os.path.lexists(lp(original)):
        raise OSError(f"原位置已有同名項目：{os.path.basename(original)}")
    os.makedirs(lp(os.path.dirname(original)), exist_ok=True)
    os.rename(lp(r_path), lp(original))
    try:
        os.remove(i_path)
    except OSError:
        log.warning("Could not remove recycle-bin metadata %s", i_path)


def _move_back(src: str, dst: str) -> None:
    # A case-only rename ("a.txt" -> "A.txt") finds itself at dst; that is fine.
    case_only = os.path.normcase(src) == os.path.normcase(dst)
    if os.path.lexists(lp(dst)) and not case_only:
        raise OSError(f"原位置已有同名項目：{os.path.basename(dst)}")
    if same_drive(src, dst):
        os.rename(lp(src), lp(dst))
    else:
        shutil.move(lp(src), lp(dst))


def undo_entry(entry: UndoEntry) -> list[str]:
    """Reverse one entry. Returns error messages (empty = fully undone)."""
    errors = []
    for rec in reversed(entry.records):
        try:
            kind = rec[0]
            if kind in ("moved", "renamed"):
                _move_back(rec[2], rec[1])
            elif kind == "created":
                send2trash(os.path.normpath(rec[1]))
            elif kind == "trashed":
                restore_from_recycle_bin(rec[1], rec[2])
        except OSError as e:
            errors.append(str(e))
            log.warning("Undo failed for %s: %s", rec, e)
    return errors


class UndoStack:
    LIMIT = 50

    def __init__(self):
        self._entries: list[UndoEntry] = []

    def push(self, label: str, records: list[tuple]) -> None:
        if records:
            self._entries.append(UndoEntry(label, list(records)))
            del self._entries[: -self.LIMIT]

    def peek_label(self) -> str | None:
        return self._entries[-1].label if self._entries else None

    def undo(self) -> tuple[str, list[str]] | None:
        """Undo the newest entry -> (label, errors), or None when empty."""
        if not self._entries:
            return None
        entry = self._entries.pop()
        return entry.label, undo_entry(entry)


def trash_records(paths: list[str]) -> list[tuple]:
    now = time.time()
    return [("trashed", os.path.abspath(p), now) for p in paths]


undo_stack = UndoStack()
