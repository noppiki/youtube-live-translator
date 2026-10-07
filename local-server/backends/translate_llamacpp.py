from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

from backends.translate_base import TRANSLATION_SYSTEM, build_translation_user, strip_choice_prefix
from runtime import llama_binary, llama_model_path, profile

_proc: subprocess.Popen | None = None


def _llama_url() -> str:
    current = profile()
    return f"http://{current.llama_host}:{current.llama_port}"


def llama_reachable(timeout: float = 0.35) -> bool:
    current = profile()
    try:
        with socket.create_connection((current.llama_host, current.llama_port), timeout=timeout):
            return True
    except OSError:
        return False


def _chat_payload(messages: list[dict], max_tokens: int = 96) -> bytes:
    return json.dumps(
        {
            "model": profile().translation_model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": max_tokens,
        }
    ).encode("utf-8")


def _post_chat(messages: list[dict]) -> str:
    req = urllib.request.Request(
        f"{_llama_url()}/v1/chat/completions",
        data=_chat_payload(messages),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return strip_choice_prefix(str(message.get("content") or ""))


def _start_llama_server() -> None:
    global _proc
    if llama_reachable():
        return
    if _proc is not None and _proc.poll() is None:
        return

    binary = llama_binary()
    model = llama_model_path()
    if not binary.exists():
        raise RuntimeError(f"llama-server is not installed at {binary}")
    if not model.exists():
        raise RuntimeError(f"Gemma GGUF is not installed at {model}")

    current = profile()
    logs = current.app_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    args = [
        str(binary),
        "-m",
        str(model),
        "--host",
        current.llama_host,
        "--port",
        str(current.llama_port),
        "--ctx-size",
        os.environ.get("YTLT_LLAMA_CTX", "4096"),
    ]
    if current.accelerator == "cpu":
        args.extend(["-ngl", "0"])
    else:
        args.extend(["-ngl", os.environ.get("YTLT_LLAMA_NGL", "99")])

    stdout = open(logs / "llama-server.log", "ab")
    stderr = open(logs / "llama-server.err.log", "ab")
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    _proc = subprocess.Popen(
        args,
        stdout=stdout,
        stderr=stderr,
        cwd=str(current.app_dir),
        creationflags=creationflags,
    )

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if llama_reachable():
            return
        if _proc.poll() is not None:
            raise RuntimeError("llama-server exited before becoming ready.")
        time.sleep(0.2)
    raise RuntimeError("llama-server did not become ready in time.")


class LlamaCppTranslator:
    def __init__(self):
        self._loaded = False

    @property
    def model_id(self) -> str:
        return profile().translation_model

    @property
    def loaded(self) -> bool:
        return self._loaded or llama_reachable()

    def translate(self, text: str, context, glossary, source: str, target: str) -> str:
        _start_llama_server()
        user = build_translation_user(text, context, glossary, source, target)
        messages = [
            {"role": "system", "content": TRANSLATION_SYSTEM},
            {"role": "user", "content": user},
        ]
        result = _post_chat(messages)
        self._loaded = True
        return result
