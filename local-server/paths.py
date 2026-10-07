import os
import sys
from pathlib import Path

APP_NAME = "YouTubeLiveTranslator"


def detect_os() -> str:
    override = os.environ.get("YTLT_OS", "").strip().lower()
    if override in {"macos", "windows", "linux"}:
        return override
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    return "linux"


def app_dir() -> Path:
    override = os.environ.get("YTLT_APP_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    os_name = detect_os()
    if os_name == "macos":
        return Path.home() / "Library/Application Support" / APP_NAME
    if os_name == "windows":
        root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData/Local")
        return Path(root) / APP_NAME
    return Path.home() / ".local/share" / APP_NAME


def runtime_state_path() -> Path:
    return app_dir() / "runtime.json"
