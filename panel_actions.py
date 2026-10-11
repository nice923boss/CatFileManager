"""File operations and external-app launching for FilePanel (mixin).

Covers Open-With / Send-To / HandBrake launching, copy/move via the queue,
drag-drop handling, delete, zip/extract, rename, new file/folder, shortcut
creation, copy-path and hash. Mixed into :class:`FilePanel`; all methods rely
on host-panel attributes (``self.model``, ``self.tree``, ``self._workers``,
``self.status_message`` …) resolved via the final MRO.
"""

import os
import shlex
import subprocess
import tarfile
import zipfile

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMessageBox,
    QVBoxLayout,
)

from batch_rename import BatchRenameDialog, execute_batch_rename
from copy_engine import remove_path, unique_name
from file_dialogs import FileProgressDialog, HashDialog
from file_operations import ZipCompressWorker, delete_to_trash
from panel_widgets import _RenameLineEdit, drop_operation
from shell_utils import _resolve_lnk_target
from undo import trash_records, undo_stack

# ERROR_CANCELLED: the user dismissed a UAC / SmartScreen elevation prompt.
# This is a benign cancellation, not a launch failure.
_ERROR_CANCELLED = 1223


def _format_launch_error(exc: Exception) -> str:
    """Map a subprocess/shell launch failure to a user-facing message.

    WinError 1223 means the user cancelled an elevation prompt, so it is
    reported as a cancellation rather than an error.
    """
    if isinstance(exc, OSError) and getattr(exc, "winerror", None) == _ERROR_CANCELLED:
        return "已取消"
    return f"開啟失敗：{exc}"


def _split_command(cmd: str) -> list[str]:
    """Tokenise a Windows shell command, stripping surrounding quotes.

    ``shlex.split(..., posix=False)`` keeps the quotes around each token, so a
    registry command like ``"C:\\App\\a.exe" "%1"`` would yield an argv[0] that
    still contains literal quotes — an invalid executable path. Strip a single
    pair of wrapping double quotes from every token so the path is usable.
    """
    parts = shlex.split(cmd, posix=False)
    return [p[1:-1] if len(p) >= 2 and p[0] == '"' and p[-1] == '"' else p for p in parts]


class FilePanelActionsMixin:
    """File operations + external-app launching for FilePanel."""

    # --- File Operations (no shell=True) ---

    def _open_cmd(self, path: str):
        try:
            subprocess.Popen(["cmd", "/K", "cd", "/d", os.path.normpath(path)])
        except Exception as e:
            self.status_message.emit(_format_launch_error(e))

    def _open_powershell(self, path: str):
        try:
            subprocess.Popen(
                ["powershell.exe", "-NoExit"],
                cwd=os.path.normpath(path),
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        except Exception as e:
            self.status_message.emit(_format_launch_error(e))

    def _open_terminal(self, path: str):
        try:
            subprocess.Popen(["wt.exe", "-d", os.path.normpath(path)])
        except FileNotFoundError:
            self.status_message.emit("找不到 Windows Terminal（wt.exe），可從 Microsoft Store 安裝")
        except Exception as e:
            self.status_message.emit(_format_launch_error(e))

    def _open_with(self, cmd_template: str, file_path: str):
        try:
            normalized = os.path.normpath(file_path)
            # Tokenise the template first, then substitute the placeholder into
            # the already-split arguments. This keeps a file path that contains
            # spaces as a single argument regardless of how the template quotes
            # it, and yields a clean (unquoted) executable path in argv[0].
            parts = _split_command(cmd_template)
            if any("%1" in p or "%L" in p for p in parts):
                parts = [p.replace("%1", normalized).replace("%L", normalized) for p in parts]
            else:
                parts.append(normalized)
            subprocess.Popen(parts)
        except Exception as e:
            self.status_message.emit(_format_launch_error(e))

    def _open_with_dialog(self, file_path: str):
        try:
            subprocess.Popen(
                [
                    "rundll32.exe",
                    "shell32.dll,OpenAs_RunDLL",
                    os.path.normpath(file_path),
                ]
            )
        except Exception as e:
            self.status_message.emit(_format_launch_error(e))

    _HANDBRAKE_EXE = r"C:\Program Files\HandBrake\HandBrake.exe"

    @staticmethod
    def _find_handbrake_hwnd() -> int:
        """Find an existing HandBrake main window handle, or 0."""
        import ctypes
        from ctypes import wintypes

        WNDENUMPROC = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HWND,
            wintypes.LPARAM,
        )
        found: list[int] = []

        def _cb(hwnd: int, _lp: int) -> bool:
            if not ctypes.windll.user32.IsWindowVisible(hwnd):
                return True
            buf = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
            if "HandBrake" in buf.value:
                found.append(hwnd)
                return False  # stop enumeration
            return True

        ctypes.windll.user32.EnumWindows(WNDENUMPROC(_cb), 0)
        return found[0] if found else 0

    @staticmethod
    def _drop_file_to_hwnd(hwnd: int, file_path: str) -> None:
        """Send WM_DROPFILES to *hwnd* so it receives *file_path*."""
        import ctypes
        import struct

        WM_DROPFILES = 0x0233
        GMEM_MOVEABLE = 0x0002
        GMEM_ZEROINIT = 0x0040

        path_bytes = (file_path + "\0\0").encode("utf-16-le")
        # DROPFILES header: DWORD pFiles, POINT pt(x,y), BOOL fNC, BOOL fWide
        header = struct.pack("IiiII", 20, 0, 0, 0, 1)
        data = header + path_bytes

        h_global = ctypes.windll.kernel32.GlobalAlloc(
            GMEM_MOVEABLE | GMEM_ZEROINIT,
            len(data),
        )
        ptr = ctypes.windll.kernel32.GlobalLock(h_global)
        ctypes.memmove(ptr, data, len(data))
        ctypes.windll.kernel32.GlobalUnlock(h_global)

        ctypes.windll.user32.SetForegroundWindow(hwnd)
        ctypes.windll.user32.PostMessageW(hwnd, WM_DROPFILES, h_global, 0)

    def _open_with_handbrake(self, file_path: str):
        try:
            import ctypes

            normalized = os.path.normpath(file_path)
            hwnd = self._find_handbrake_hwnd()
            if hwnd:
                self._drop_file_to_hwnd(hwnd, normalized)
            else:
                ctypes.windll.shell32.ShellExecuteW(
                    None,
                    "open",
                    self._HANDBRAKE_EXE,
                    f'"{normalized}"',
                    None,
                    1,
                )
        except Exception as e:
            self.status_message.emit(f"開啟 HandBrake 失敗：{e}")

    def _run_as_admin(self, file_path: str):
        try:
            import ctypes

            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", os.path.normpath(file_path), None, None, 1
            )
        except Exception as e:
            self.status_message.emit(f"管理員開啟失敗：{e}")

    def _send_to(self, shortcut_path: str, file_paths: list[str]):
        try:
            normalized = [os.path.normpath(p) for p in file_paths]
            if shortcut_path.lower().endswith(".lnk"):
                target = _resolve_lnk_target(shortcut_path)
                cmd = [target] + normalized
            else:
                cmd = [shortcut_path] + normalized
            subprocess.Popen(cmd)
        except Exception as e:
            self.status_message.emit(f"傳送失敗：{e}")

    def _remove_worker(self, worker: QThread):
        if worker in self._workers:
            self._workers.remove(worker)

    def _queue_transfer(self, op: str, sources: list[str], destination: str) -> None:
        """Hand copy/move to the shared queue; progress shows in the queue window."""
        if not destination or not os.path.isdir(destination):
            self.status_message.emit("目標資料夾不存在")
            return
        dest = os.path.normcase(os.path.normpath(destination))
        valid: list[str] = []
        for raw in sources:
            norm = os.path.normpath(raw)
            if not os.path.lexists(norm):
                continue
            if op == "move" and os.path.normcase(os.path.dirname(norm)) == dest:
                continue  # moving into the folder it is already in does nothing
            if os.path.isdir(norm) and not os.path.islink(norm):
                src = os.path.normcase(norm)
                if dest == src or dest.startswith(src + os.sep):
                    self.status_message.emit(
                        f"無法將「{os.path.basename(norm)}」放入其自身或子資料夾"
                    )
                    return
            valid.append(norm)
        if not valid:
            return

        def _on_done(result) -> None:
            self._refresh_all_panels()
            self.status_message.emit(result.message)

        verify = bool(self.prefs.get("verify_after_copy", False))
        self.queue.enqueue(op, valid, os.path.normpath(destination), verify, _on_done)
        verb = "複製" if op == "copy" else "移動"
        self.status_message.emit(f"已加入佇列：{verb} {len(valid)} 個項目")

    def _copy_to(self, sources: list[str], destination: str):
        self._queue_transfer("copy", sources, destination)

    def _move_to(self, sources: list[str], destination: str):
        self._queue_transfer("move", sources, destination)

    def _on_files_dropped(self, paths: list[str], modifiers, target_dir: str) -> None:
        """Files dropped onto this panel (from another panel or Explorer).

        Explorer convention (C06): Ctrl copies, Shift moves, otherwise a drop on
        the same drive moves and a drop on another drive copies.
        """
        self.activated.emit(self.panel_id)
        dest = os.path.normpath(target_dir) if target_dir else self.current_path()
        valid = [os.path.normpath(p) for p in paths if p]
        if not valid:
            return
        if drop_operation(valid, dest, modifiers) == "copy":
            self._copy_to(valid, dest)
        else:
            self._move_to(valid, dest)

    def _refresh_all_panels(self):
        self._refresh()
        for panel in self.other_panels:
            panel._refresh()

    def _delete(self, paths: list[str]):
        count = len(paths)
        reply = QMessageBox.question(
            self,
            "確認刪除",
            f"確定要將 {count} 個項目移至資源回收筒嗎？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            ok, msg = delete_to_trash(paths)
            gone = [p for p in paths if not os.path.lexists(p)]
            undo_stack.push(f"刪除 {len(gone)} 個項目", trash_records(gone))
            self._refresh_all_panels()
            self.status_message.emit(msg if ok else f"刪除失敗：{msg}")

    def _delete_permanent(self, paths: list[str]) -> None:
        """C08: Shift+Delete skips the recycle bin, after an explicit warning."""
        names = "、".join(os.path.basename(p) for p in paths[:3])
        if len(paths) > 3:
            names += f" 等 {len(paths)} 個項目"
        reply = QMessageBox.warning(
            self,
            "永久刪除",
            f"確定要永久刪除 {names} 嗎？\n\n不會放入資源回收筒，刪除後無法復原。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        errors: list[str] = []
        for p in paths:
            try:
                remove_path(p)
            except OSError as e:
                errors.append(f"{os.path.basename(p)}: {e}")
        self._refresh_all_panels()
        done = len(paths) - len(errors)
        if errors:
            self.status_message.emit(
                f"已永久刪除 {done} 個，失敗 {len(errors)} 個：{'; '.join(errors[:3])}"
            )
        else:
            self.status_message.emit(f"已永久刪除 {done} 個項目")

    def _compress_to_zip(self, paths: list[str]) -> None:
        if not paths:
            return
        parent_dir = os.path.dirname(paths[0])
        if len(paths) == 1:
            default_name = os.path.splitext(os.path.basename(paths[0]))[0] + ".zip"
        else:
            default_name = os.path.basename(parent_dir) + ".zip"

        zip_name, ok = QInputDialog.getText(self, "壓縮成 ZIP", "ZIP 檔名：", text=default_name)
        if not ok or not zip_name.strip():
            return
        zip_name = zip_name.strip()
        if not zip_name.lower().endswith(".zip"):
            zip_name += ".zip"
        zip_path = os.path.join(parent_dir, zip_name)

        if os.path.exists(zip_path):
            reply = QMessageBox.question(
                self,
                "檔案已存在",
                f"{zip_name} 已存在，要覆蓋嗎？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        worker = ZipCompressWorker(paths, zip_path)
        dialog = FileProgressDialog("zip", 1, parent=self)

        worker.progress.connect(dialog.update_progress)
        dialog._cancel_btn.clicked.connect(worker.cancel)

        def _on_done(msg: str) -> None:
            self.status_message.emit(msg)
            self._remove_worker(worker)
            self._refresh()
            dialog.accept()

        def _on_error(msg: str) -> None:
            self.status_message.emit(msg)
            self._remove_worker(worker)
            self._refresh()
            dialog.accept()

        worker.finished.connect(_on_done)
        worker.error.connect(_on_error)

        self._workers.append(worker)
        worker.start()
        dialog.exec()

    @staticmethod
    def _strip_archive_ext(name: str) -> str:
        """Strip compound archive extensions like .tar.gz, .tar.bz2, etc."""
        lower = name.lower()
        for compound in (".tar.gz", ".tar.bz2", ".tar.xz"):
            if lower.endswith(compound):
                return name[: -len(compound)]
        return os.path.splitext(name)[0]

    @staticmethod
    def _cleanup_empty_dir(path: str) -> None:
        """Remove directory if it exists and is empty."""
        try:
            if os.path.isdir(path) and not os.listdir(path):
                os.rmdir(path)
        except OSError:
            pass

    def _extract_archive(self, paths: list[str]) -> None:
        if not paths:
            return
        extracted = 0
        errors: list[str] = []
        _TAR_EXTS = (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".gz", ".bz2", ".xz")
        for arc in paths:
            arc = os.path.normpath(arc)
            parent = os.path.dirname(arc)
            folder_name = self._strip_archive_ext(os.path.basename(arc))
            dest = os.path.join(parent, folder_name)
            # Avoid collision
            if os.path.exists(dest):
                counter = 1
                while os.path.exists(dest):
                    dest = os.path.join(parent, f"{folder_name} ({counter})")
                    counter += 1
            lower_arc = arc.lower()
            ext = os.path.splitext(arc)[1].lower()
            try:
                if ext == ".zip":
                    with zipfile.ZipFile(arc, "r") as zf:
                        zf.extractall(dest)
                elif any(lower_arc.endswith(e) for e in _TAR_EXTS):
                    with tarfile.open(arc, "r:*") as tf:
                        # "data" filter blocks ../ paths, absolute paths and device files
                        tf.extractall(dest, filter="data")
                else:
                    # 7z, rar, etc. — use 7z CLI directly
                    subprocess.run(
                        ["7z", "x", arc, f"-o{dest}", "-y"],
                        check=True,
                        capture_output=True,
                    )
                extracted += 1
            except zipfile.BadZipFile:
                self._cleanup_empty_dir(dest)
                errors.append(f"{os.path.basename(arc)}: 不是有效的 ZIP 檔")
            except tarfile.TarError as e:
                self._cleanup_empty_dir(dest)
                errors.append(f"{os.path.basename(arc)}: {e}")
            except FileNotFoundError:
                self._cleanup_empty_dir(dest)
                errors.append(f"{os.path.basename(arc)}: 不支援此格式（需安裝 7-Zip）")
            except subprocess.CalledProcessError as e:
                self._cleanup_empty_dir(dest)
                errors.append(f"{os.path.basename(arc)}: {e}")
            except Exception as e:
                self._cleanup_empty_dir(dest)
                errors.append(f"{os.path.basename(arc)}: {e}")

        self._refresh()
        if errors:
            self.status_message.emit(
                f"解壓縮完成 {extracted} 個，失敗 {len(errors)} 個：{'; '.join(errors[:3])}"
            )
        else:
            self.status_message.emit(f"解壓縮完成：{extracted} 個壓縮檔")

    def _rename(self, path: str):
        old_name = os.path.basename(path)
        is_lnk = old_name.lower().endswith(".lnk")
        display_name = old_name[:-4] if is_lnk else old_name

        dlg = QDialog(self)
        dlg.setWindowTitle("重新命名")
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("新名稱："))
        line_edit = _RenameLineEdit(display_name)
        layout.addWidget(line_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        dlg.setMinimumWidth(350)

        # Select filename without extension
        dot_idx = display_name.rfind(".")
        if dot_idx > 0:
            line_edit.setSelection(0, dot_idx)
        else:
            line_edit.selectAll()

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_name = line_edit.text().strip()
        if new_name and new_name != display_name:
            if is_lnk and not new_name.lower().endswith(".lnk"):
                new_name = new_name + ".lnk"
            new_path = os.path.join(os.path.dirname(path), new_name)
            try:
                os.rename(os.path.normpath(path), os.path.normpath(new_path))
                undo_stack.push(
                    f"重新命名 {old_name}",
                    [("renamed", os.path.normpath(path), os.path.normpath(new_path))],
                )
                self._refresh()
                display = new_name[:-4] if new_name.lower().endswith(".lnk") else new_name
                self.status_message.emit(f"已重新命名為：{display}")
            except OSError as e:
                self.status_message.emit(f"重新命名失敗：{e}")

    def _batch_rename(self):
        # Number files following the current visual (sorted) order
        paths = [p for p in self._get_selected_paths() if os.path.lexists(p)]
        if len(paths) < 2:
            return
        dlg = BatchRenameDialog(paths, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        pairs = dlg.rename_pairs()
        success, errors = execute_batch_rename(pairs)
        self._push_batch_rename_undo(pairs)
        self._refresh()
        if errors:
            self.status_message.emit(
                f"批次重新命名完成 {success} 個，失敗 {len(errors)} 個：{'; '.join(errors[:3])}"
            )
        else:
            self.status_message.emit(f"已批次重新命名 {success} 個項目")

    def _push_batch_rename_undo(self, pairs: list[tuple[str, str]]) -> None:
        # Undo renames back one by one; that only works when no new name is
        # also an old name in the same batch (e.g. shifted sequence numbers).
        # Case-only renames ("a" -> "A") match their own old name; that's fine.
        nc = os.path.normcase
        olds = {nc(s) for s, _ in pairs}
        if any(nc(d) in olds and nc(d) != nc(s) for s, d in pairs):
            return
        records = [
            ("renamed", s, d)
            for s, d in pairs
            if os.path.lexists(d) and (nc(s) == nc(d) or not os.path.lexists(s))
        ]
        undo_stack.push(f"批次重新命名 {len(records)} 個項目", records)

    def _new_folder(self, parent_dir: str):
        name, ok = QInputDialog.getText(self, "新增資料夾", "資料夾名稱：", text="新資料夾")
        if ok and name:
            new_path = os.path.join(parent_dir, name)
            try:
                os.makedirs(new_path, exist_ok=False)
                undo_stack.push(f"新增資料夾 {name}", [("created", new_path)])
                self._refresh()
                self.status_message.emit(f"已建立資料夾：{name}")
            except OSError as e:
                self.status_message.emit(f"建立失敗：{e}")

    def _new_textfile(self, parent_dir: str):
        name, ok = QInputDialog.getText(self, "新增記事本", "檔案名稱：", text="新檔案.txt")
        if ok and name:
            if not os.path.splitext(name)[1]:
                name += ".txt"
            new_path = os.path.join(parent_dir, name)
            try:
                if os.path.exists(new_path):
                    self.status_message.emit(f"檔案已存在：{name}")
                    return
                with open(new_path, "w", encoding="utf-8"):
                    pass
                undo_stack.push(f"新增檔案 {name}", [("created", new_path)])
                self._refresh()
                self.status_message.emit(f"已建立檔案：{name}")
                subprocess.Popen(["notepad.exe", new_path])
            except OSError as e:
                self.status_message.emit(f"建立失敗：{e}")

    def _create_shortcut(self, target_path: str) -> None:
        """Create a .lnk shortcut for the given file or folder."""
        try:
            import win32com.client

            parent_dir = os.path.dirname(target_path)
            base_name = os.path.splitext(os.path.basename(target_path))[0]
            lnk_path = os.path.join(parent_dir, f"{base_name} - 捷徑.lnk")
            counter = 1
            while os.path.exists(lnk_path):
                counter += 1
                lnk_path = os.path.join(parent_dir, f"{base_name} - 捷徑-{counter}.lnk")
            shell = win32com.client.Dispatch("WScript.Shell")
            shortcut = shell.CreateShortCut(lnk_path)
            shortcut.Targetpath = target_path
            shortcut.WorkingDirectory = parent_dir
            shortcut.save()
            self.status_message.emit(f"已建立捷徑：{os.path.basename(lnk_path)}")
        except Exception as e:
            QMessageBox.warning(self, "錯誤", f"建立捷徑失敗：{e}")

    def _create_link(self, target: str, kind: str) -> None:
        """C12: create a junction or symbolic link to `target` in a chosen folder."""
        start = next(
            (p.current_path() for p in self.other_panels if p.isVisible() and p.current_path()),
            os.path.dirname(target),
        )
        title = (
            "建立 Junction：選擇放置位置" if kind == "junction" else "建立符號連結：選擇放置位置"
        )
        folder = QFileDialog.getExistingDirectory(self, title, start)
        if not folder:
            return
        link = unique_name(os.path.join(os.path.normpath(folder), os.path.basename(target)))
        try:
            if kind == "junction":
                import _winapi

                _winapi.CreateJunction(os.path.normpath(target), link)
            else:
                os.symlink(target, link, target_is_directory=os.path.isdir(target))
        except OSError as e:
            if kind == "symlink" and getattr(e, "winerror", None) == 1314:
                QMessageBox.warning(
                    self,
                    "建立符號連結失敗",
                    "建立符號連結需要系統管理員權限，或在 Windows 設定開啟「開發人員模式」。\n"
                    "資料夾可改用 Junction，不需要特殊權限。",
                )
            else:
                QMessageBox.warning(self, "建立連結失敗", str(e))
            return
        undo_stack.push(f"建立連結 {os.path.basename(link)}", [("created", link)])
        self._refresh_all_panels()
        self.status_message.emit(f"已建立連結：{link}")

    def _copy_path(self, paths: list[str]):
        text = "\n".join(paths)
        QApplication.clipboard().setText(text)
        self.status_message.emit(f"已複製 {len(paths)} 個路徑")

    def _copy_text_variant(self, paths: list[str], variant: str) -> None:
        """C11: file name only, forward-slash path or quoted path."""
        formats = {
            "name": os.path.basename,
            "slash": lambda p: os.path.normpath(p).replace("\\", "/"),
            "quoted": lambda p: f'"{os.path.normpath(p)}"',
        }
        QApplication.clipboard().setText("\n".join(formats[variant](p) for p in paths))
        self.status_message.emit(f"已複製 {len(paths)} 筆到剪貼簿")

    def _calculate_hash(self, paths: list[str]) -> None:
        files = [p for p in paths if os.path.isfile(p)]
        if not files:
            QMessageBox.information(self, "計算哈希值", "未選擇任何檔案。")
            return
        dialog = HashDialog(files, parent=self)
        dialog.show()
