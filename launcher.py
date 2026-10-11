"""Wrapper: redirect stdout/stderr BEFORE any import."""
import sys
import os
import traceback
import runpy

_LOG_DIR = os.path.join(os.path.expanduser("~"), ".catfm")
os.makedirs(_LOG_DIR, exist_ok=True)
_log = open(
    os.path.join(_LOG_DIR, "app.log"),
    "a", buffering=1, encoding="utf-8",
)

if sys.stdout is None:
    sys.stdout = _log
if sys.stderr is None:
    sys.stderr = _log

try:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    runpy.run_path("app.py", run_name="__main__")
except SystemExit as e:
    _log.write(f"[launcher] SystemExit: {e}\n")
except Exception:
    traceback.print_exc(file=_log)
finally:
    _log.flush()
