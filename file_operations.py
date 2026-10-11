"""File operations — copy, move, delete in background threads."""

import hashlib
import os
import shutil
import zipfile

from PySide6.QtCore import QThread, Signal
from send2trash import send2trash


def _normalize(path: str) -> str:
    """Normalize path separators for Windows APIs."""
    return os.path.normpath(path)


class FileOperationWorker(QThread):
    """Runs file copy/move in a background thread."""

    finished = Signal(str)  # success message
    error = Signal(str)     # error message
    progress = Signal(int, int, str)  # (current_index, total, current_filename)

    def __init__(self, operation: str, sources: list[str], destination: str, parent=None):
        super().__init__(parent)
        self.operation = operation  # "copy" or "move"
        self.sources = [_normalize(s) for s in sources]
        self.destination = _normalize(destination)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self):
        errors: list[str] = []
        success_count = 0
        total = len(self.sources)
        for idx, src in enumerate(self.sources):
            if self._cancelled:
                break
            name = os.path.basename(src)
            self.progress.emit(idx, total, name)
            try:
                dst = os.path.join(self.destination, name)

                # Handle name collision
                if os.path.exists(dst):
                    base, ext = os.path.splitext(name)
                    counter = 1
                    while os.path.exists(dst):
                        dst = os.path.join(self.destination, f"{base} ({counter}){ext}")
                        counter += 1

                if self.operation == "copy":
                    if os.path.isdir(src):
                        shutil.copytree(src, dst)
                    else:
                        shutil.copy2(src, dst)
                elif self.operation == "move":
                    shutil.move(src, dst)
                    # Cross-drive moves (copytree+rmtree) may leave
                    # empty source dirs on OneDrive / cloud-synced folders.
                    if os.path.isdir(src) and not os.listdir(src):
                        os.rmdir(src)

                success_count += 1
            except shutil.Error as e:
                # shutil.Error contains a list of (src, dst, error) tuples
                for item in e.args[0] if e.args else []:
                    errors.append(f"{os.path.basename(item[0])}: {item[2]}")
            except OSError as e:
                errors.append(f"{os.path.basename(src)}: {e}")

        op_name = "複製" if self.operation == "copy" else "移動"
        if self._cancelled:
            self.finished.emit(
                f"{op_name}已取消（已完成 {success_count} / {total} 個）"
            )
        elif errors:
            self.error.emit(
                f"{op_name}完成 {success_count} 個，"
                f"失敗 {len(errors)} 個：{'; '.join(errors[:3])}"
            )
        else:
            self.finished.emit(f"{op_name}完成：{success_count} 個項目")


class ZipCompressWorker(QThread):
    """Compress files/directories into a ZIP archive in a background thread."""

    finished = Signal(str)  # success message
    error = Signal(str)     # error message
    progress = Signal(int, int, str)  # (current_index, total, current_filename)

    def __init__(self, sources: list[str], zip_path: str, parent=None):
        super().__init__(parent)
        self.sources = [_normalize(s) for s in sources]
        self.zip_path = _normalize(zip_path)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self):
        entries: list[tuple[str, str]] = []  # (full_path, arcname)
        for src in self.sources:
            if self._cancelled:
                break
            if os.path.isfile(src):
                entries.append((src, os.path.basename(src)))
            elif os.path.isdir(src):
                dir_name = os.path.basename(src)
                for root, _dirs, files in os.walk(src):
                    for f in files:
                        full = os.path.join(root, f)
                        arcname = os.path.join(dir_name, os.path.relpath(full, src))
                        entries.append((full, arcname))

        total = len(entries)
        zip_name = os.path.basename(self.zip_path)
        try:
            with zipfile.ZipFile(self.zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for idx, (full, arcname) in enumerate(entries):
                    if self._cancelled:
                        break
                    self.progress.emit(idx, total, os.path.basename(full))
                    zf.write(full, arcname)

            if self._cancelled:
                try:
                    os.remove(self.zip_path)
                except OSError:
                    pass
                self.finished.emit(f"\u58d3\u7e2e\u5df2\u53d6\u6d88\uff1a{zip_name}")
            else:
                self.finished.emit(f"\u58d3\u7e2e\u5b8c\u6210\uff1a{zip_name}")
        except Exception as e:
            try:
                if os.path.exists(self.zip_path):
                    os.remove(self.zip_path)
            except OSError:
                pass
            self.error.emit(f"\u58d3\u7e2e\u5931\u6557\uff1a{e}")


def delete_to_trash(paths: list[str]) -> tuple[bool, str]:
    """Delete files/folders to recycle bin. Returns (success, message)."""
    try:
        normalized = [_normalize(p) for p in paths]
        send2trash(normalized)
        return True, f"\u5df2\u522a\u9664 {len(paths)} \u500b\u9805\u76ee\u81f3\u8cc7\u6e90\u56de\u6536\u7b52"
    except Exception as e:
        return False, str(e)


class HashCalculateWorker(QThread):
    """Compute MD5 / SHA-1 / SHA-256 for files in a background thread."""

    # (file_index, total_files, filename, bytes_done, bytes_total)
    progress = Signal(int, int, str, int, int)
    # (path, {"md5": str, "sha1": str, "sha256": str})
    file_done = Signal(str, dict)
    # (path, error_message)
    file_error = Signal(str, str)
    finished_all = Signal()

    _CHUNK_SIZE = 1024 * 1024  # 1 MB

    def __init__(self, paths: list[str], parent=None):
        super().__init__(parent)
        self._paths = [_normalize(p) for p in paths if os.path.isfile(p)]
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        total_files = len(self._paths)
        for idx, path in enumerate(self._paths):
            if self._cancelled:
                break
            name = os.path.basename(path)
            try:
                size = os.path.getsize(path)
                md5 = hashlib.md5()
                sha1 = hashlib.sha1()
                sha256 = hashlib.sha256()
                done = 0
                self.progress.emit(idx, total_files, name, 0, size)
                with open(path, "rb") as f:
                    while True:
                        if self._cancelled:
                            return
                        chunk = f.read(self._CHUNK_SIZE)
                        if not chunk:
                            break
                        md5.update(chunk)
                        sha1.update(chunk)
                        sha256.update(chunk)
                        done += len(chunk)
                        self.progress.emit(idx, total_files, name, done, size)
                self.file_done.emit(
                    path,
                    {
                        "md5": md5.hexdigest(),
                        "sha1": sha1.hexdigest(),
                        "sha256": sha256.hexdigest(),
                    },
                )
            except Exception as e:
                self.file_error.emit(path, str(e))
        self.finished_all.emit()
