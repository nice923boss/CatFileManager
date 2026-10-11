"""Copy / move engine (C01 conflicts, C03 speed, C05 pause, C15 verify, J07 long paths).

Files are copied in 1 MB chunks into ``<name>.catfm-part`` and renamed into
place when complete, so:
  * pause simply blocks between chunks (the transfer resumes where it stopped);
  * cancel deletes the partial file and never damages an existing target;
  * the source hash is computed while reading, verification only re-reads the copy.

Links found *inside* a copied folder are recreated as links (copying their
contents could loop forever, e.g. "Application Data" junctions). A link the
user selected directly is followed and its contents are copied, like Explorer.
"""

import _winapi
import hashlib
import logging
import os
import shutil
import threading
import time
from collections import deque
from typing import NamedTuple

from PySide6.QtCore import QThread, Signal

from long_path import lp, unlp

log = logging.getLogger(__name__)

CHUNK = 1024 * 1024
PART_SUFFIX = ".catfm-part"

OVERWRITE = "overwrite"
SKIP = "skip"
RENAME = "rename"


class Progress(NamedTuple):
    bytes_done: int
    bytes_total: int
    files_done: int
    files_total: int
    name: str
    speed: float  # bytes per second over the last few seconds of active time
    eta: float  # seconds, -1 when unknown


class TransferResult(NamedTuple):
    op: str
    message: str
    errors: list[str]
    # Undo records: ("created", path) or ("moved", original, new)
    records: list[tuple]
    undo_complete: bool  # False when an overwrite/merge happened (cannot be fully undone)
    cancelled: bool


class _Step(NamedTuple):
    kind: str  # "dir" | "file" | "link"
    src: str
    rel: str  # path relative to the top-level target ("" = the target itself)
    size: int


def unique_name(path: str) -> str:
    """'a.txt' -> 'a (1).txt' (first name that does not exist)."""
    folder, name = os.path.split(path)
    base, ext = os.path.splitext(name)
    n = 1
    while True:
        candidate = os.path.join(folder, f"{base} ({n}){ext}")
        if not os.path.lexists(lp(candidate)):
            return candidate
        n += 1


def same_drive(a: str, b: str) -> bool:
    da = os.path.splitdrive(os.path.abspath(a))[0].lower()
    db = os.path.splitdrive(os.path.abspath(b))[0].lower()
    return bool(da) and da == db


def _is_link_entry(entry: os.DirEntry) -> bool:
    return entry.is_symlink() or entry.is_junction()


def _is_link(path: str) -> bool:
    return os.path.islink(lp(path)) or os.path.isjunction(lp(path))


def _recreate_link(src: str, dst: str) -> None:
    target = unlp(os.readlink(lp(src)))
    if os.path.isjunction(lp(src)):
        _winapi.CreateJunction(target, lp(dst))
    else:
        os.symlink(target, lp(dst), target_is_directory=os.path.isdir(lp(src)))


def remove_path(path: str) -> None:
    """Delete a file, a folder tree, or just a link (never its target)."""
    p = lp(path)
    if _is_link(path):
        if os.path.isdir(p):
            os.rmdir(p)
        else:
            os.remove(p)
    elif os.path.isdir(p):
        shutil.rmtree(p)
    else:
        os.remove(p)


def _plan_tree(src: str) -> list[_Step]:
    """Every folder/file/link under `src`, with paths relative to it."""
    steps = [_Step("dir", src, "", 0)]
    stack = [(src, "")]
    while stack:
        s_dir, d_dir = stack.pop()
        with os.scandir(lp(s_dir)) as it:
            for entry in it:
                s = os.path.join(s_dir, entry.name)
                d = os.path.join(d_dir, entry.name) if d_dir else entry.name
                if _is_link_entry(entry):
                    steps.append(_Step("link", s, d, 0))
                elif entry.is_dir(follow_symlinks=False):
                    steps.append(_Step("dir", s, d, 0))
                    stack.append((s, d))
                else:
                    steps.append(_Step("file", s, d, entry.stat(follow_symlinks=False).st_size))
    return steps


def _file_count(steps: list[_Step]) -> int:
    return sum(1 for s in steps if s.kind != "dir")


class _Cancelled(Exception):
    pass


class TransferWorker(QThread):
    progress = Signal(object)  # Progress
    conflict = Signal(str, str, bool, bool)  # src, dst, src_is_dir, dst_is_dir
    done = Signal(object)  # TransferResult

    def __init__(self, op: str, sources: list[str], destination: str, verify: bool = False):
        super().__init__()
        self.op = op  # "copy" | "move"
        self.sources = [os.path.normpath(s) for s in sources]
        self.destination = os.path.normpath(destination)
        self.verify = verify
        self._cancel = False
        self._running = threading.Event()
        self._running.set()
        self._answer = threading.Event()
        self._choice = SKIP
        self._apply_all: str | None = None
        self._bytes_total = 0
        self._bytes_done = 0
        self._files_total = 0
        self._files_done = 0
        self._samples: deque[tuple[float, int]] = deque()
        self._active_time = 0.0
        self._last_tick = 0.0
        self._last_emit = 0.0

    # --- control (called from the GUI thread) ---
    def pause(self) -> None:
        self._running.clear()

    def resume(self) -> None:
        self._running.set()

    def is_paused(self) -> bool:
        return not self._running.is_set()

    def cancel(self) -> None:
        self._cancel = True
        self._running.set()
        self._answer.set()

    def resolve_conflict(self, choice: str, apply_all: bool) -> None:
        self._choice = choice
        if apply_all:
            self._apply_all = choice
        self._answer.set()

    # --- worker ---
    def _check(self) -> None:
        if not self._running.is_set():
            self._running.wait()
            self._last_tick = time.monotonic()  # paused time is not "active"
        if self._cancel:
            raise _Cancelled

    def _ask(self, src: str, dst: str) -> str:
        if self._apply_all:
            return self._apply_all
        self._answer.clear()
        self.conflict.emit(
            src, dst, os.path.isdir(lp(src)), os.path.isdir(lp(dst)) and not _is_link(dst)
        )
        self._answer.wait()
        if self._cancel:
            raise _Cancelled
        return self._choice

    def _emit(self, name: str, force: bool = False) -> None:
        now = time.monotonic()
        self._active_time += now - self._last_tick
        self._last_tick = now
        if not force and now - self._last_emit < 0.1:
            return
        self._last_emit = now
        self._samples.append((self._active_time, self._bytes_done))
        while len(self._samples) > 2 and self._active_time - self._samples[0][0] > 3:
            self._samples.popleft()
        t0, b0 = self._samples[0]
        dt = self._active_time - t0
        speed = (self._bytes_done - b0) / dt if dt > 0.2 else 0.0
        remaining = self._bytes_total - self._bytes_done
        eta = remaining / speed if speed > 0 else -1.0
        self.progress.emit(
            Progress(
                self._bytes_done,
                self._bytes_total,
                self._files_done,
                self._files_total,
                name,
                speed,
                eta,
            )
        )

    def _copy_file(self, src: str, dst: str) -> None:
        part = dst + PART_SUFFIX
        name = os.path.basename(src)
        hasher = hashlib.sha256() if self.verify else None
        try:
            with open(lp(src), "rb") as fi, open(lp(part), "wb") as fo:
                while True:
                    self._check()
                    chunk = fi.read(CHUNK)
                    if not chunk:
                        break
                    fo.write(chunk)
                    if hasher:
                        hasher.update(chunk)
                    self._bytes_done += len(chunk)
                    self._emit(name)
            shutil.copystat(lp(src), lp(part))
            self._verify(src, part, hasher)
            os.replace(lp(part), lp(dst))
        except BaseException:
            try:
                os.remove(lp(part))
            except OSError:
                pass
            raise
        self._files_done += 1

    def _verify(self, src: str, part: str, hasher) -> None:
        if os.path.getsize(lp(src)) != os.path.getsize(lp(part)):
            raise OSError("驗證失敗：檔案大小不一致")
        if hasher is None:
            return
        check = hashlib.sha256()
        with open(lp(part), "rb") as f:
            while chunk := f.read(CHUNK):
                self._check()
                check.update(chunk)
        if check.digest() != hasher.digest():
            raise OSError("驗證失敗：SHA-256 不一致")

    def _run_steps(self, steps: list[_Step], root: str, errors: list[str]) -> bool:
        ok = True
        for step in steps:
            self._check()
            dst = os.path.join(root, step.rel) if step.rel else root
            try:
                if step.kind == "dir":
                    os.makedirs(lp(dst), exist_ok=True)
                elif step.kind == "link":
                    if os.path.lexists(lp(dst)):
                        remove_path(dst)
                    _recreate_link(step.src, dst)
                    self._files_done += 1
                else:
                    self._copy_file(step.src, dst)
            except _Cancelled:
                raise
            except OSError as e:
                ok = False
                errors.append(f"{os.path.basename(step.src)}：{e.strerror or e}")
                log.warning("Copy failed %s -> %s: %s", step.src, dst, e)
        return ok

    def _resolve_target(self, src: str) -> tuple[str, bool] | None:
        """(dst, merging) for one top-level source, or None to skip it."""
        dst = os.path.join(self.destination, os.path.basename(src))
        if os.path.normcase(os.path.dirname(src)) == os.path.normcase(self.destination):
            # Same folder: copying makes a numbered duplicate, moving is a no-op.
            return (unique_name(dst), False) if self.op == "copy" else None
        if not os.path.lexists(lp(dst)):
            return dst, False
        choice = self._ask(src, dst)
        if choice == SKIP:
            return None
        if choice == RENAME:
            return unique_name(dst), False
        src_dir = os.path.isdir(lp(src))
        dst_dir = os.path.isdir(lp(dst)) and not _is_link(dst)
        if src_dir != dst_dir:
            raise OSError("檔案與資料夾同名，無法覆蓋")
        return dst, True

    def run(self) -> None:
        errors: list[str] = []
        records: list[tuple] = []
        undo_complete = True
        cancelled = False
        self._last_tick = time.monotonic()
        try:
            dest_norm = os.path.normcase(self.destination) + os.sep
            work: list[tuple[str, list[_Step] | None]] = []
            for src in self.sources:
                if dest_norm.startswith(os.path.normcase(src) + os.sep):
                    errors.append(f"{os.path.basename(src)}：無法放進自己的子資料夾")
                    continue
                work.append((src, None))

            # Plan sizes up front so the progress bar shows real totals.
            self._emit("正在計算大小…", force=True)
            sized: list[tuple[str, list[_Step] | None]] = []
            for src, _ in work:
                self._check()
                fast_move = self.op == "move" and same_drive(src, self.destination)
                if fast_move:
                    sized.append((src, None))
                    self._files_total += 1
                    continue
                try:
                    if os.path.isdir(lp(src)):
                        steps = _plan_tree(src)
                    else:
                        steps = [_Step("file", src, "", os.path.getsize(lp(src)))]
                except OSError as e:
                    errors.append(f"{os.path.basename(src)}：{e.strerror or e}")
                    continue
                self._bytes_total += sum(s.size for s in steps)
                self._files_total += _file_count(steps)
                sized.append((src, steps))

            for src, steps in sized:
                self._check()
                try:
                    target = self._resolve_target(src)
                except OSError as e:
                    errors.append(f"{os.path.basename(src)}：{e}")
                    continue
                if target is None:  # skipped: count it as done so progress reaches 100 %
                    self._files_done += 1 if steps is None else _file_count(steps)
                    self._bytes_done += 0 if steps is None else sum(s.size for s in steps)
                    continue
                dst, merging = target
                if merging:
                    undo_complete = False
                if steps is None:
                    self._move_same_drive(src, dst, merging, records, errors)
                    continue
                if self._run_steps(steps, dst, errors):
                    if self.op == "move":
                        remove_path(src)
                        if not merging:
                            records.append(("moved", src, dst))
                    elif not merging:
                        records.append(("created", dst))
                self._emit(os.path.basename(src), force=True)
        except _Cancelled:
            cancelled = True
        except Exception as e:  # keep the queue alive, report instead of crashing
            log.exception("Transfer crashed")
            errors.append(str(e))

        self.done.emit(
            TransferResult(
                self.op,
                self._message(cancelled, errors),
                errors,
                records,
                undo_complete,
                cancelled,
            )
        )

    def _move_same_drive(self, src, dst, merging, records, errors) -> None:
        try:
            if merging:
                # Merge folder: move each child, overwrite files that collide.
                if os.path.isdir(lp(src)):
                    for name in os.listdir(lp(src)):
                        s, d = os.path.join(src, name), os.path.join(dst, name)
                        if os.path.lexists(lp(d)):
                            if os.path.isdir(lp(s)) and os.path.isdir(lp(d)) and not _is_link(d):
                                self._move_same_drive(s, d, True, records, errors)
                                continue
                            remove_path(d)
                        os.rename(lp(s), lp(d))
                    os.rmdir(lp(src))
                else:
                    os.replace(lp(src), lp(dst))
            else:
                os.rename(lp(src), lp(dst))
                records.append(("moved", src, dst))
            self._files_done += 1
            self._emit(os.path.basename(src), force=True)
        except OSError as e:
            errors.append(f"{os.path.basename(src)}：{e.strerror or e}")

    def _message(self, cancelled: bool, errors: list[str]) -> str:
        op_name = "複製" if self.op == "copy" else "移動"
        done = f"{self._files_done} / {self._files_total}"
        if cancelled:
            return f"{op_name}已取消（完成 {done} 個檔案）"
        if errors:
            return f"{op_name}完成 {done}，失敗 {len(errors)} 個：{'；'.join(errors[:3])}"
        return f"{op_name}完成：{self._files_total} 個檔案"
