#!/usr/bin/env python3
import json
import os
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

LABEL = "com.noppiki.youtube-live-translator"
PLIST = Path.home() / "Library/LaunchAgents/com.noppiki.youtube-live-translator.plist"
HOST = "127.0.0.1"
PORT = 8765


def is_running():
    try:
        with socket.create_connection((HOST, PORT), timeout=0.25):
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


def ensure_started():
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


def read_message():
    raw = sys.stdin.buffer.read(4)
    if len(raw) != 4:
        return None
    length = struct.unpack("=I", raw)[0]
    if length > 1024 * 1024:
        raise ValueError("Message too large")
    payload = sys.stdin.buffer.read(length)
    if len(payload) != length:
        raise ValueError("Incomplete message")
    return json.loads(payload.decode("utf-8"))


def write_message(message):
    payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("=I", len(payload)))
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()


def main():
    try:
        message = read_message() or {}
        action = message.get("action", "status")

        if action == "status":
            write_message({
                "ok": True,
                "installed": PLIST.exists(),
                "running": is_running(),
            })
        elif action == "start":
            write_message(ensure_started())
        else:
            write_message({"ok": False, "error": f"Unknown action: {action}"})
    except Exception as exc:
        write_message({"ok": False, "error": str(exc)})


if __name__ == "__main__":
    main()
