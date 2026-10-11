"""Background searches: subfolders by name (D01/D02), file contents (D05), Everything (D04)."""

import logging
import os
import shutil
import subprocess
import tempfile
import time
from collections import deque
from typing import NamedTuple

from PySide6.QtCore import QThread, Signal

from long_path import lp
from search_utils import make_matcher

log = logging.getLogger(__name__)

CONTENT_SIZE_LIMIT = 50 * 1024 * 1024  # skip bigger files in content search
_CHUNK = 1024 * 1024

EVERYTHING_URL = "https://www.voidtools.com/zh-tw/downloads/"


class Hit(NamedTuple):
    path: str
    is_dir: bool
    size: int
    modified: float


def find_es_exe(override: str = "") -> str:
    """Path of Everything's command-line client es.exe, or "" when not found."""
    local = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        override,
        shutil.which("es.exe") or "",
        r"C:\Program Files\Everything\es.exe",
        r"C:\Program Files (x86)\Everything\es.exe",
        os.path.join(local, r"Programs\Everything\es.exe") if local else "",
    ]
    return next((c for c in candidates if c and os.path.isfile(c)), "")


def _needles(text: str) -> list[bytes]:
    """Byte forms of `text` in the encodings text files here usually use."""
    found: list[bytes] = []
    for enc in ("utf-8", "cp950", "utf-16-le"):
        try:
            b = text.encode(enc).lower()
        except UnicodeEncodeError:
            continue
        if b and b not in found:
            found.append(b)
    return found


def file_contains(path: str, needles: list[bytes]) -> bool:
    """Case-insensitive (ASCII) byte search, chunked so big files use little memory."""
    try:
        size = os.path.getsize(lp(path))
        if size == 0 or size > CONTENT_SIZE_LIMIT:
            return False
        overlap = max(len(n) for n in needles) - 1
        with open(lp(path), "rb") as f:
            tail = b""
            while chunk := f.read(_CHUNK):
                data = tail + chunk.lower()
                if any(n in data for n in needles):
                    return True
                tail = data[-overlap:] if overlap else b""
    except OSError:
        return False
    return False


def _hit(path: str) -> Hit | None:
    try:
        st = os.stat(lp(path))
    except OSError:
        return None
    return Hit(path, os.path.isdir(lp(path)), st.st_size, st.st_mtime)


class SearchWorker(QThread):
    """Runs one search and streams hits back in batches."""

    found = Signal(list)  # list[Hit]
    scanning = Signal(str)  # folder being scanned (throttled)
    done = Signal(str, bool)  # error message ("" = ok), hit the result limit

    LIMIT = 5000
    _BATCH = 100

    def __init__(self, mode: str, root: str, text: str, regex: bool, es_path: str = ""):
        super().__init__()
        self._mode = mode
        self._root = root
        self._text = text
        self._regex = regex
        self._es_path = es_path
        self._cancelled = False
        self._count = 0
        self._batch: list[Hit] = []
        self._last_scan_emit = 0.0

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        error = ""
        try:
            if self._mode == "everything":
                error = self._run_everything()
            else:
                self._run_walk()
        except Exception as e:  # report instead of killing the thread silently
            log.exception("Search failed")
            error = str(e)
        self._flush()
        self.done.emit(error, self._count >= self.LIMIT)

    # --- helpers ---

    def _add(self, hit: Hit | None) -> None:
        if hit is None:
            return
        self._batch.append(hit)
        self._count += 1
        if len(self._batch) >= self._BATCH:
            self._flush()

    def _flush(self) -> None:
        if self._batch:
            self.found.emit(self._batch)
            self._batch = []

    def _stop(self) -> bool:
        return self._cancelled or self._count >= self.LIMIT

    def _run_walk(self) -> None:
        content = self._mode == "content"
        needles = _needles(self._text) if content else []
        matcher = None if content else make_matcher(self._text, self._regex)
        queue = deque([self._root])
        while queue and not self._stop():
            folder = queue.popleft()
            now = time.monotonic()
            if now - self._last_scan_emit > 0.2:
                self._last_scan_emit = now
                self.scanning.emit(folder)
            try:
                with os.scandir(lp(folder)) as it:
                    entries = list(it)
            except OSError:
                continue
            for entry in entries:
                if self._stop():
                    return
                path = os.path.join(folder, entry.name)
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                    is_link = entry.is_symlink() or entry.is_junction()
                except OSError:
                    continue
                if is_dir and not is_link:  # never follow links (loops, duplicates)
                    queue.append(path)
                if content:
                    if not is_dir and file_contains(path, needles):
                        self._add(_hit(path))
                elif matcher and matcher(entry.name):
                    self._add(_hit(path))

    def _run_everything(self) -> str:
        es = find_es_exe(self._es_path)
        if not es:
            return f"找不到 Everything 的 es.exe，請安裝 Everything 與 ES 命令列工具（{EVERYTHING_URL}）"
        fd, out_file = tempfile.mkstemp(suffix=".txt", prefix="catfm-es-")
        os.close(fd)
        try:
            args = [es, "-n", str(self.LIMIT), "-export-txt", out_file, "-utf8-bom"]
            args += ["-r", self._text] if self._regex else [self._text]
            proc = subprocess.run(
                args,
                capture_output=True,
                timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if proc.returncode != 0:
                return (
                    f"Everything 搜尋失敗（錯誤碼 {proc.returncode}），請確認 Everything 正在執行"
                )
            with open(out_file, encoding="utf-8-sig", errors="replace") as f:
                for line in f:
                    if self._stop():
                        break
                    path = line.strip()
                    if path:
                        self._add(_hit(path))
        except subprocess.TimeoutExpired:
            return "Everything 超過 60 秒沒有回應"
        finally:
            try:
                os.remove(out_file)
            except OSError:
                log.warning("Could not remove %s", out_file)
        return ""
