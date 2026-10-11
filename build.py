"""K03: build the Windows release with PyInstaller.

Usage:  python build.py          -> dist/CatFileManager/CatFileManager.exe
        python build.py --zip    -> also dist/CatFileManager-v<VERSION>-win64.zip

Steps: close a running CatFileManager.exe (it locks dist/), write the exe's
version resource from version.py, run PyInstaller, optionally zip the result.
Needs:  pip install pyinstaller (plus requirements.txt).
"""

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import time

from version import VERSION

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")
APP_DIR = os.path.join(DIST, "CatFileManager")
EXE_NAME = "CatFileManager.exe"
VERSION_FILE = os.path.join(ROOT, "version_info.txt")  # read by CatFileManager.spec


def _is_running() -> bool:
    out = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {EXE_NAME}", "/NH"],
        capture_output=True,
        text=True,
    ).stdout
    return EXE_NAME.lower() in out.lower()


def close_running_app() -> bool:
    """Ask a running packaged app to close (normal close, so settings are saved)."""
    if not _is_running():
        return True
    print(f"正在關閉執行中的 {EXE_NAME}…")
    subprocess.run(["taskkill", "/IM", EXE_NAME], capture_output=True)
    for _ in range(20):
        time.sleep(0.5)
        if not _is_running():
            return True
    return False


def write_version_file() -> None:
    nums = tuple(int(p) for p in VERSION.split(".")) + (0,) * (4 - len(VERSION.split(".")))
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040404B0', [
      StringStruct('FileDescription', 'CatFileManager'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('ProductName', 'CatFileManager'),
      StringStruct('ProductVersion', '{VERSION}'),
      StringStruct('OriginalFilename', '{EXE_NAME}'),
      StringStruct('LegalCopyright', 'MIT License')])]),
    VarFileInfo([VarStruct('Translation', [1028, 1200])])
  ]
)
"""
    with open(VERSION_FILE, "w", encoding="utf-8") as f:
        f.write(text)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build CatFileManager with PyInstaller")
    parser.add_argument("--zip", action="store_true", help="also create a release zip")
    args = parser.parse_args()

    if importlib.util.find_spec("PyInstaller") is None:
        print("找不到 PyInstaller，請先執行：python -m pip install pyinstaller")
        return 1
    if not close_running_app():
        print(f"{EXE_NAME} 仍在執行（可能有檔案操作進行中），請手動關閉後再打包")
        return 1

    write_version_file()
    cmd = [sys.executable, "-m", "PyInstaller", "CatFileManager.spec", "--noconfirm", "--clean"]
    print(f"打包 v{VERSION}：", " ".join(cmd))
    try:
        result = subprocess.run(cmd, cwd=ROOT)
    finally:
        os.remove(VERSION_FILE)
    if result.returncode != 0:
        print(f"打包失敗（結束碼 {result.returncode}）")
        return result.returncode

    exe = os.path.join(APP_DIR, EXE_NAME)
    if not os.path.isfile(exe):
        print(f"打包完成但找不到 {exe}")
        return 1
    print(f"完成：{exe}")

    if args.zip:
        base = os.path.join(DIST, f"CatFileManager-v{VERSION}-win64")
        archive = shutil.make_archive(base, "zip", DIST, "CatFileManager")
        print(f"壓縮檔：{archive}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
