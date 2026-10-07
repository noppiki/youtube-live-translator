#!/usr/bin/env python3
"""Chrome Native Messaging host for starting the local engine."""

from __future__ import annotations

import json
import os
import platform
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import BinaryIO, Mapping


LABEL = "com.noppiki.youtube-live-translator"
HOST = "127.0.0.1"
PORT = 8765
MAX_MESSAGE_SIZE = 1024 * 1024
WINDOWS_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def app_dir(environ: Mapping[str, str] | None = None, home: Path | None = None) -> Path:
    """Resolve the same mutable app directory as the local server."""

    env = environ if environ is not None else os.environ
    configured = str(env.get("YTLT_APP_DIR", "")).strip()
    if configured:
        return Path(configured).expanduser()
    base_home = home or Path.home()
    if platform.system() == "Windows":
        local_app_data = str(env.get("LOCALAPPDATA", "")).strip()
        return Path(local_app_data) / "YouTubeLiveTranslator" if local_app_data else base_home / "AppData/Local/YouTubeLiveTranslator"
    return base_home / "Library/Application Support/YouTubeLiveTranslator"


APP_DIR = app_dir()
PLIST = Path.home() / "Library/LaunchAgents/com.noppiki.youtube-live-translator.plist"


def is_running() -> bool:
    """Check whether the local HTTP listener accepts a TCP connection."""

    try:
        with socket.create_connection((HOST, PORT), timeout=0.25):
            return True
    except OSError:
        return False


def launchctl(*args: str) -> subprocess.CompletedProcess[bytes]:
    """Run launchctl while keeping Native Messaging stdout clean."""

    return subprocess.run(
        ["/bin/launchctl", *args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _windows_python() -> Path:
    configured = str(os.environ.get("YTLT_PYTHON", "")).strip()
    if configured:
        return Path(configured)
    return APP_DIR / ".venv/Scripts/python.exe"


def _windows_server() -> Path:
    return APP_DIR / "server.py"


def _windows_translation_server() -> Path:
    return APP_DIR / "llama-cpp/llama-server.exe"


def _windows_translation_model() -> Path | None:
    configured = str(os.environ.get("YTLT_TRANSLATION_MODEL", "")).strip()
    if configured and Path(configured).is_file():
        return Path(configured)
    model_dir = APP_DIR / "models/gemma-4-E4B-it-qat-q4_0-gguf"
    candidates = sorted(model_dir.glob("*.gguf"))
    return candidates[0] if candidates else None


def _windows_startup_configured() -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, "YouTubeLiveTranslator")
            return bool(value)
    except (ImportError, FileNotFoundError, OSError):
        return False


def _windows_installed() -> bool:
    return _windows_server().is_file() and _windows_python().is_file()


def _windows_environment() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("YTLT_APP_DIR", str(APP_DIR))
    env.setdefault("YTLT_TRANSLATION_URL", "http://127.0.0.1:8766")
    model = _windows_translation_model()
    if model:
        env.setdefault("YTLT_TRANSLATION_MODEL", str(model))
    return env


def ensure_started_macos() -> dict[str, object]:
    """Ensure the existing macOS LaunchAgent is bootstrapped and running."""

    if not PLIST.exists():
        return {"ok": False, "installed": False, "running": False, "error": "Local engine is not installed."}

    uid = os.getuid()
    domain = f"gui/{uid}"
    service = f"{domain}/{LABEL}"

    if launchctl("print", service).returncode != 0:
        launchctl("bootstrap", domain, str(PLIST))

    result = launchctl("kickstart", "-k", service)
    if result.returncode != 0:
        return {
            "ok": False,
            "installed": True,
            "running": is_running(),
            "error": "launchctl kickstart failed.",
        }

    return _wait_for_server(installed=True)


def ensure_started_windows() -> dict[str, object]:
    """Start the isolated Windows Python server and wait for its socket."""

    if not _windows_installed():
        return {
            "ok": False,
            "installed": False,
            "running": False,
            "error": "Local engine is not installed. Re-run install-windows.ps1.",
        }
    if is_running():
        return {
            "ok": True,
            "installed": True,
            "running": True,
            "startupConfigured": _windows_startup_configured(),
        }

    python = _windows_python()
    creation_flags = (
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
        | getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    )
    log_dir = APP_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    try:
        translation_server = _windows_translation_server()
        translation_model = _windows_translation_model()
        if translation_server.is_file() and translation_model and not _port_is_open(8766):
            llama_out = open(log_dir / "llama.log", "a", encoding="utf-8")
            llama_err = open(log_dir / "llama.err.log", "a", encoding="utf-8")
            subprocess.Popen(
                [
                    str(translation_server),
                    "-m",
                    str(translation_model),
                    "--host",
                    HOST,
                    "--port",
                    "8766",
                ],
                cwd=str(translation_server.parent),
                env=_windows_environment(),
                stdin=subprocess.DEVNULL,
                stdout=llama_out,
                stderr=llama_err,
                creationflags=creation_flags,
                close_fds=True,
            )
            llama_out.close()
            llama_err.close()

        server_env = _windows_environment()
        server_env["PYTHONFAULTHANDLER"] = "1"
        server_out = open(log_dir / "server.log", "a", encoding="utf-8")
        server_err = open(log_dir / "server.err.log", "a", encoding="utf-8")
        subprocess.Popen(
            [str(python), "-X", "faulthandler", "-u", str(_windows_server())],
            cwd=str(APP_DIR),
            env=server_env,
            stdin=subprocess.DEVNULL,
            stdout=server_out,
            stderr=server_err,
            creationflags=creation_flags,
            close_fds=True,
        )
        server_out.close()
        server_err.close()
    except OSError as exc:
        return {"ok": False, "installed": True, "running": False, "error": str(exc)}

    result = _wait_for_server(installed=True)
    result["startupConfigured"] = _windows_startup_configured()
    return result


def _wait_for_server(installed: bool) -> dict[str, object]:
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        if is_running():
            return {"ok": True, "installed": installed, "running": True}
        time.sleep(0.2)
    return {
        "ok": False,
        "installed": installed,
        "running": False,
        "error": "Local engine did not become ready in time.",
    }


def _port_is_open(port: int) -> bool:
    try:
        with socket.create_connection((HOST, port), timeout=0.25):
            return True
    except OSError:
        return False


def encode_message(message: object) -> bytes:
    """Encode a Chrome Native Messaging message for tests and stdout."""

    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_MESSAGE_SIZE:
        raise ValueError("Message too large")
    return struct.pack("<I", len(payload)) + payload


def decode_message(raw: bytes) -> object:
    """Decode one complete Chrome Native Messaging message."""

    if len(raw) < 4:
        raise ValueError("Incomplete message")
    length = struct.unpack("<I", raw[:4])[0]
    if length > MAX_MESSAGE_SIZE:
        raise ValueError("Message too large")
    if len(raw) != length + 4:
        raise ValueError("Incomplete message")
    return json.loads(raw[4:].decode("utf-8"))


def read_message(stream: BinaryIO | None = None) -> object | None:
    """Read one length-prefixed message from a binary stream."""

    source = stream or sys.stdin.buffer
    raw_length = source.read(4)
    if not raw_length:
        return None
    if len(raw_length) != 4:
        raise ValueError("Incomplete message")
    length = struct.unpack("<I", raw_length)[0]
    if length > MAX_MESSAGE_SIZE:
        raise ValueError("Message too large")
    payload = source.read(length)
    if len(payload) != length:
        raise ValueError("Incomplete message")
    return json.loads(payload.decode("utf-8"))


def write_message(message: object, stream: BinaryIO | None = None) -> None:
    """Write one Native Messaging response without contaminating stdout."""

    target = stream or sys.stdout.buffer
    target.write(encode_message(message))
    target.flush()


def main() -> None:
    try:
        message = read_message() or {}
        action = message.get("action", "status") if isinstance(message, dict) else "status"

        if action == "status":
            if platform.system() == "Windows":
                write_message({
                    "ok": True,
                    "platform": "windows",
                    "installed": _windows_installed(),
                    "running": is_running(),
                    "startupConfigured": _windows_startup_configured(),
                    "appDir": str(APP_DIR),
                })
            else:
                write_message({
                    "ok": True,
                    "installed": PLIST.exists(),
                    "running": is_running(),
                })
        elif action == "start":
            write_message(ensure_started_windows() if platform.system() == "Windows" else ensure_started_macos())
        else:
            write_message({"ok": False, "error": f"Unknown action: {action}"})
    except Exception as exc:
        write_message({"ok": False, "error": str(exc)})


if __name__ == "__main__":
    main()
