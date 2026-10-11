"""Windows shell + registry helpers (file properties, .lnk, Open-With, Send-To)."""

import ctypes
import ctypes.wintypes
import os
import winreg


class _SHELLEXECUTEINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.DWORD),
        ("fMask", ctypes.c_ulong),
        ("hwnd", ctypes.wintypes.HWND),
        ("lpVerb", ctypes.wintypes.LPCWSTR),
        ("lpFile", ctypes.wintypes.LPCWSTR),
        ("lpParameters", ctypes.wintypes.LPCWSTR),
        ("lpDirectory", ctypes.wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", ctypes.wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", ctypes.wintypes.LPCWSTR),
        ("hkeyClass", ctypes.wintypes.HKEY),
        ("dwHotKey", ctypes.wintypes.DWORD),
        ("hIconOrMonitor", ctypes.wintypes.HANDLE),
        ("hProcess", ctypes.wintypes.HANDLE),
    ]


def _show_file_properties(file_path: str) -> None:
    """Open the Windows file properties dialog for the given path."""
    sei = _SHELLEXECUTEINFO()
    sei.cbSize = ctypes.sizeof(sei)
    sei.fMask = 0x0000000C  # SEE_MASK_INVOKEIDLIST
    sei.lpVerb = "properties"
    sei.lpFile = file_path
    sei.nShow = 1
    ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei))


def _resolve_lnk_target(lnk_path: str) -> str:
    """Resolve a .lnk shortcut to its target path."""
    try:
        import win32com.client

        shell = win32com.client.Dispatch("WScript.Shell")
        sc = shell.CreateShortCut(lnk_path)
        return sc.TargetPath or lnk_path
    except Exception:
        return lnk_path


def _get_send_to_items() -> list[tuple[str, str]]:
    send_to = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "SendTo")
    items = []
    if not os.path.isdir(send_to):
        return items
    for name in sorted(os.listdir(send_to)):
        full = os.path.join(send_to, name)
        display = os.path.splitext(name)[0]
        items.append((display, full))
    return items


def _get_open_with_apps(ext: str) -> list[tuple[str, str]]:
    apps = []
    if not ext:
        return apps
    try:
        key_path = f"Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\FileExts\\{ext}\\OpenWithProgids"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            i = 0
            while True:
                try:
                    prog_id, _, _ = winreg.EnumValue(key, i)
                    if prog_id:
                        app_name = _progid_to_name(prog_id)
                        app_cmd = _progid_to_command(prog_id)
                        if app_cmd:
                            apps.append((app_name or prog_id, app_cmd))
                    i += 1
                except OSError:
                    break
    except OSError:
        pass
    try:
        key_path = (
            f"Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\FileExts\\{ext}\\OpenWithList"
        )
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            i = 0
            while True:
                try:
                    _, val, _ = winreg.EnumValue(key, i)
                    if isinstance(val, str) and val.endswith(".exe"):
                        display = os.path.splitext(val)[0]
                        apps.append((display, val))
                    i += 1
                except OSError:
                    break
    except OSError:
        pass
    seen = set()
    unique = []
    for name, cmd in apps:
        if name not in seen:
            seen.add(name)
            unique.append((name, cmd))
    return unique


def _progid_to_name(prog_id: str) -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, prog_id) as key:
            val, _ = winreg.QueryValueEx(key, "")
            return val if val else prog_id
    except OSError:
        return prog_id


def _progid_to_command(prog_id: str) -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, f"{prog_id}\\shell\\open\\command") as key:
            val, _ = winreg.QueryValueEx(key, "")
            return val
    except OSError:
        return ""


def _prune_mrulist(key, removed_names: list[str]) -> None:
    """Drop *removed_names* letters from an OpenWithList MRUList ordering value."""
    try:
        mru, _ = winreg.QueryValueEx(key, "MRUList")
    except OSError:
        return
    if not isinstance(mru, str):
        return
    new_mru = "".join(ch for ch in mru if ch not in removed_names)
    if new_mru != mru:
        try:
            if new_mru:
                winreg.SetValueEx(key, "MRUList", 0, winreg.REG_SZ, new_mru)
            else:
                # Last entry removed: drop MRUList rather than leave it empty.
                winreg.DeleteValue(key, "MRUList")
        except OSError:
            pass


def _remove_open_with_app(ext: str, app_name: str) -> bool:
    """Delete every Open-With registry entry for *ext* shown as *app_name*.

    Mirrors the listing logic in `_get_open_with_apps`: removes matching values
    from this extension's OpenWithProgids and OpenWithList keys under HKCU and
    prunes the OpenWithList MRUList ordering. Only the given extension is
    touched; other file types keep their lists. Returns True if anything was
    deleted.
    """
    if not ext or not app_name:
        return False
    base = f"Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\FileExts\\{ext}"
    removed = False

    # OpenWithProgids: each value's NAME is a ProgID; display comes from it.
    progids_path = f"{base}\\OpenWithProgids"
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            progids_path,
            0,
            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
        ) as key:
            targets = []
            i = 0
            while True:
                try:
                    prog_id, _, _ = winreg.EnumValue(key, i)
                except OSError:
                    break
                if prog_id and _progid_to_name(prog_id) == app_name:
                    targets.append(prog_id)
                i += 1
            for prog_id in targets:
                try:
                    winreg.DeleteValue(key, prog_id)
                    removed = True
                except OSError:
                    pass
    except OSError:
        pass

    # OpenWithList: value DATA is the exe name; value NAME is an MRU letter.
    list_path = f"{base}\\OpenWithList"
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            list_path,
            0,
            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
        ) as key:
            targets = []
            i = 0
            while True:
                try:
                    val_name, data, _ = winreg.EnumValue(key, i)
                except OSError:
                    break
                if (
                    val_name != "MRUList"
                    and isinstance(data, str)
                    and data.endswith(".exe")
                    and os.path.splitext(data)[0] == app_name
                ):
                    targets.append(val_name)
                i += 1
            for val_name in targets:
                try:
                    winreg.DeleteValue(key, val_name)
                    removed = True
                except OSError:
                    pass
            if targets:
                _prune_mrulist(key, targets)
    except OSError:
        pass

    return removed
