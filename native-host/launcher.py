#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

LABEL = "com.noppiki.youtube-live-translator"
TASK_NAME = "YouTubeLiveTranslator"
HOST = "127.0.0.1"
PORT = int(os.environ.get("YTLT_PORT", "8765"))


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
        return Path.home() / "Library/Application Support/YouTubeLiveTranslator"
    if os_name == "windows":
        root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData/Local")
        return Path(root) / "YouTubeLiveTranslator"
    return Path.home() / ".local/share/YouTubeLiveTranslator"


def plist_path() -> Path:
    return Path.home() / "Library/LaunchAgents/com.noppiki.youtube-live-translator.plist"


def server_path() -> Path:
    return app_dir() / "server.py"


def is_running(timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=timeout):
            return True
    except OSError:
        return False


def launchctl(*args):
    return subprocess.run(
        ["/bin/launchctl", *args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _hidden_flags() -> int:
    if sys.platform != "win32":
        return 0
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def task_registered() -> bool:
    if detect_os() != "windows":
        return False
    if shutil.which("schtasks") is None:
        return False
    result = subprocess.run(
        ["schtasks", "/Query", "/TN", TASK_NAME],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        creationflags=_hidden_flags(),
    )
    return result.returncode == 0


def windows_python() -> Path | None:
    venv = app_dir() / ".venv"
    for name in ("pythonw.exe", "python.exe"):
        candidate = venv / "Scripts" / name
        if candidate.exists():
            return candidate
    return None


def start_windows_process() -> None:
    python = windows_python()
    server = server_path()
    if python is None or not server.exists():
        raise RuntimeError("Local engine is not installed.")
    logs = app_dir() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    with open(logs / "server.log", "ab") as stdout, open(logs / "server.err.log", "ab") as stderr:
        subprocess.Popen(
            [str(python), str(server)],
            stdout=stdout,
            stderr=stderr,
            cwd=str(app_dir()),
            creationflags=_hidden_flags() | getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )


def ensure_started_macos():
    plist = plist_path()
    if not plist.exists():
        return {"ok": False, "installed": False, "running": False, "error": "Local engine is not installed."}

    uid = os.getuid()
    domain = f"gui/{uid}"
    service = f"{domain}/{LABEL}"

    if launchctl("print", service).returncode != 0:
        launchctl("bootstrap", domain, str(plist))

    result = launchctl("kickstart", "-k", service)
    if result.returncode != 0:
        return {
            "ok": False,
            "installed": True,
            "running": is_running(),
            "error": "launchctl kickstart failed.",
        }

    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        if is_running():
            return {"ok": True, "installed": True, "running": True}
        time.sleep(0.2)

    return {
        "ok": False,
        "installed": True,
        "running": False,
        "error": "Local engine did not become ready in time.",
    }


def ensure_started_windows():
    installed = server_path().exists()
    if not installed:
        return {"ok": False, "installed": False, "running": False, "error": "Local engine is not installed."}

    if is_running():
        return {"ok": True, "installed": True, "running": True, "taskRegistered": task_registered()}

    if task_registered():
        subprocess.run(
            ["schtasks", "/Run", "/TN", TASK_NAME],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=_hidden_flags(),
        )
    else:
        try:
            start_windows_process()
        except Exception as exc:
            return {
                "ok": False,
                "installed": True,
                "running": False,
                "taskRegistered": False,
                "error": str(exc),
            }

    deadline = time.monotonic() + 12.0
    while time.monotonic() < deadline:
        if is_running():
            return {"ok": True, "installed": True, "running": True, "taskRegistered": task_registered()}
        time.sleep(0.2)

    return {
        "ok": False,
        "installed": True,
        "running": False,
        "taskRegistered": task_registered(),
        "error": "Local engine did not become ready in time.",
    }


def status_payload():
    os_name = detect_os()
    if os_name == "macos":
        return {
            "ok": True,
            "installed": plist_path().exists(),
            "running": is_running(),
        }
    if os_name == "windows":
        return {
            "ok": True,
            "installed": server_path().exists(),
            "running": is_running(),
            "taskRegistered": task_registered(),
        }
    return {
        "ok": True,
        "installed": server_path().exists(),
        "running": is_running(),
    }


def ensure_started():
    os_name = detect_os()
    if os_name == "macos":
        return ensure_started_macos()
    if os_name == "windows":
        return ensure_started_windows()
    return {
        "ok": False,
        "installed": server_path().exists(),
        "running": is_running(),
        "error": "Linux is not supported in this release.",
    }


def read_message(stream=None):
    source = sys.stdin.buffer if stream is None else stream
    raw = source.read(4)
    if len(raw) != 4:
        return None
    length = struct.unpack("=I", raw)[0]
    if length > 1024 * 1024:
        raise ValueError("Message too large")
    payload = source.read(length)
    if len(payload) != length:
        raise ValueError("Incomplete message")
    return json.loads(payload.decode("utf-8"))


def write_message(message, stream=None):
    dest = sys.stdout.buffer if stream is None else stream
    payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
    dest.write(struct.pack("=I", len(payload)))
    dest.write(payload)
    dest.flush()


def handle(message):
    action = (message or {}).get("action", "status")
    if action == "status":
        return status_payload()
    if action == "start":
        return ensure_started()
    return {"ok": False, "error": f"Unknown action: {action}"}


def main():
    try:
        write_message(handle(read_message() or {}))
    except Exception as exc:
        write_message({"ok": False, "error": str(exc)})


if __name__ == "__main__":
    main()
