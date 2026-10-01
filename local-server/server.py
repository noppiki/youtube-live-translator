#!/usr/bin/env python3
import asyncio
import json
import os
import platform
import struct
from pathlib import Path

import numpy as np
from aiohttp import web
from mlx_qwen3_asr import Session

HOST = "127.0.0.1"
PORT = int(os.environ.get("YTLT_PORT", "8765"))
APP_DIR = Path.home() / "Library/Application Support/YouTubeLiveTranslator"
FLUID_BRIDGE = Path(os.environ.get("YTLT_FLUID_BRIDGE", APP_DIR / "bin/fluid-bridge"))
DEFAULT_MODEL = os.environ.get("YTLT_MODEL", "moona3k/mlx-qwen3-asr-0.6b-4bit")

MODELS = {
    "balanced": {
        "id": "moona3k/mlx-qwen3-asr-0.6b-4bit",
        "label": "Qwen3-ASR 0.6B 4-bit",
    },
    "accuracy": {
        "id": "moona3k/mlx-qwen3-asr-1.7b-4bit",
        "label": "Qwen3-ASR 1.7B 4-bit",
    },
}
_sessions = {}
_session_lock = asyncio.Lock()


def _allowed_origin(request: web.Request) -> bool:
    origin = request.headers.get("Origin")
    return origin is None or origin.startswith("chrome-extension://")


def _is_english(language) -> bool:
    if language is None:
        return False
    value = str(language).lower()
    return value in {"en", "english", "en-us", "en-gb"}


async def get_session(model_id: str) -> Session:
    async with _session_lock:
        session = _sessions.get(model_id)
        if session is None:
            session = await asyncio.to_thread(Session, model=model_id)
            _sessions[model_id] = session
        return session


class FluidProcess:
    def __init__(self, diarization: bool):
        self.diarization = diarization
        self.proc = None
        self.queue = asyncio.Queue()
        self.ready = asyncio.Event()
        self.reader_task = None
        self.stderr_task = None

    @staticmethod
    def _frame(kind: int, payload: bytes = b"") -> bytes:
        body = bytes([kind]) + payload
        return struct.pack("<I", len(body)) + body

    async def start(self, timeout=600):
        if not FLUID_BRIDGE.exists():
            raise RuntimeError("FluidAudio bridge is not installed. Re-run the macOS installer.")

        self.proc = await asyncio.create_subprocess_exec(
            str(FLUID_BRIDGE),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self.reader_task = asyncio.create_task(self._read_stdout())
        self.stderr_task = asyncio.create_task(self._read_stderr())

        config = json.dumps({"diarization": self.diarization}).encode("utf-8")
        self.proc.stdin.write(self._frame(0, config))
        await self.proc.stdin.drain()

        try:
            await asyncio.wait_for(self.ready.wait(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            await self.close()
            raise RuntimeError("FluidAudio model preparation timed out.") from exc

    async def _read_stdout(self):
        try:
            while True:
                line = await self.proc.stdout.readline()
                if not line:
                    break
                try:
                    message = json.loads(line.decode("utf-8"))
                except Exception:
                    continue
                if message.get("type") == "ready":
                    self.ready.set()
                await self.queue.put(message)
        finally:
            await self.queue.put({"type": "closed"})

    async def _read_stderr(self):
        try:
            while True:
                line = await self.proc.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    await self.queue.put({"type": "debug", "message": text})
        except Exception:
            pass

    async def send_audio(self, pcm16: bytes):
        if not self.proc or self.proc.returncode is not None:
            raise RuntimeError("FluidAudio bridge is not running.")
        self.proc.stdin.write(self._frame(1, pcm16))
        await self.proc.stdin.drain()

    async def finalize(self):
        if self.proc and self.proc.returncode is None:
            self.proc.stdin.write(self._frame(2))
            await self.proc.stdin.drain()

    async def close(self):
        if not self.proc:
            return
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except Exception:
            pass

        try:
            await asyncio.wait_for(self.proc.wait(), timeout=2)
        except asyncio.TimeoutError:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=2)
            except asyncio.TimeoutError:
                self.proc.kill()
        for task in (self.reader_task, self.stderr_task):
            if task:
                task.cancel()


async def health(request: web.Request):
    return web.json_response(
        {
            "ok": True,
            "service": "youtube-live-translator-local",
            "version": "0.4.0",
            "platform": platform.machine(),
            "defaultModel": DEFAULT_MODEL,
            "loadedModels": list(_sessions.keys()),
            "models": MODELS,
            "fluidAudio": {
                "available": FLUID_BRIDGE.exists(),
                "path": str(FLUID_BRIDGE),
                "englishStreaming": True,
                "diarization": FLUID_BRIDGE.exists(),
            },
        }
    )


async def models(request: web.Request):
    return web.json_response(
        {
            "ok": True,
            "models": MODELS,
            "loaded": list(_sessions),
            "fluidAudio": {
                "available": FLUID_BRIDGE.exists(),
                "asr": "Parakeet EOU 120M / 320 ms",
                "diarization": "Sortformer",
            },
        }
    )


async def install_model(request: web.Request):
    if not _allowed_origin(request):
        raise web.HTTPForbidden()

    data = await request.json()
    engine = data.get("engine", "qwen")

    if engine == "fluid":
        if not FLUID_BRIDGE.exists():
            raise web.HTTPBadRequest(text="FluidAudio bridge is not installed")
        fluid = FluidProcess(diarization=bool(data.get("diarization", False)))
        try:
            await fluid.start(timeout=900)
            return web.json_response(
                {
                    "ok": True,
                    "engine": "fluid",
                    "diarization": bool(data.get("diarization", False)),
                }
            )
        finally:
            await fluid.close()

    model_id = data.get("model")
    if model_id not in {v["id"] for v in MODELS.values()}:
        raise web.HTTPBadRequest(text="Unknown model")
    await get_session(model_id)
    return web.json_response({"ok": True, "engine": "qwen", "model": model_id})


async def stream(request: web.Request):
    if not _allowed_origin(request):
        raise web.HTTPForbidden()

    ws = web.WebSocketResponse(heartbeat=15, max_msg_size=2 * 1024 * 1024)
    await ws.prepare(request)

    config = {
        "model": DEFAULT_MODEL,
        "language": None,
        "context": "",
        "chunkSizeSec": 1.0,
        "maxContextSec": 30.0,
        "localBackend": "auto",
        "diarization": False,
    }

    backend = None
    session = None
    state = None
    audio_buffer = bytearray()
    fluid = None
    fluid_pump = None
    configured = False

    async def pump_fluid():
        while fluid:
            message = await fluid.queue.get()
            kind = message.get("type")
            if kind == "closed":
                break
            if kind == "debug":
                continue
            if not ws.closed:
                await ws.send_json(message)

    async def configure(payload):
        nonlocal backend, session, state, fluid, fluid_pump, configured
        config.update(payload)

        requested = str(config.get("localBackend") or "auto")
        language = config.get("language")
        want_diarization = bool(config.get("diarization", False))

        if requested == "fluid":
            backend = "fluid"
        elif requested == "qwen":
            backend = "qwen"
        else:
            backend = "fluid" if _is_english(language) and FLUID_BRIDGE.exists() else "qwen"

        if backend == "fluid":
            if not _is_english(language):
                raise ValueError("FluidAudio live ASR is currently enabled for English only.")
            fluid = FluidProcess(diarization=want_diarization)
            await fluid.start()
            fluid_pump = asyncio.create_task(pump_fluid())
            configured = True
            await ws.send_json(
                {
                    "type": "ready",
                    "backend": "fluid",
                    "model": "Parakeet EOU 120M / 320ms",
                    "diarization": want_diarization,
                    "language": "en",
                }
            )
            return

        model_id = config.get("model") or DEFAULT_MODEL
        if model_id not in {v["id"] for v in MODELS.values()}:
            raise ValueError("Unsupported local model")
        session = await get_session(model_id)
        kwargs = {
            "chunk_size_sec": float(config.get("chunkSizeSec", 1.0)),
            "max_context_sec": float(config.get("maxContextSec", 30.0)),
            "context": str(config.get("context") or "").strip(),
        }
        if language and str(language).lower() not in ("auto", "multi"):
            kwargs["language"] = language
        state = session.init_streaming(**kwargs)
        configured = True
        await ws.send_json(
            {
                "type": "ready",
                "backend": "qwen",
                "model": model_id,
                "language": language or "auto",
                "diarization": False,
                "warning": "Speaker diarization requires the FluidAudio English backend."
                if want_diarization
                else None,
            }
        )

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                payload = json.loads(msg.data)
                kind = payload.get("type")

                if kind == "config":
                    await configure(payload)

                elif kind == "finalize" and configured:
                    if backend == "fluid":
                        await fluid.finalize()
                    else:
                        state = await asyncio.to_thread(session.finish_streaming, state)
                        text = (getattr(state, "text", "") or "").strip()
                        stable = (getattr(state, "stable_text", "") or "").strip()
                        await ws.send_json(
                            {
                                "type": "final",
                                "text": text or stable,
                                "language": getattr(state, "language", None),
                            }
                        )

                elif kind == "ping":
                    await ws.send_json({"type": "pong"})

            elif msg.type == web.WSMsgType.BINARY:
                if not configured:
                    await configure({})

                if backend == "fluid":
                    await fluid.send_audio(bytes(msg.data))
                    continue

                audio_buffer.extend(msg.data)
                target_bytes = 16000 * 2
                while len(audio_buffer) >= target_bytes:
                    raw = bytes(audio_buffer[:target_bytes])
                    del audio_buffer[:target_bytes]
                    pcm = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
                    state = await asyncio.to_thread(session.feed_audio, pcm, state)
                    text = (getattr(state, "text", "") or "").strip()
                    stable = (getattr(state, "stable_text", "") or "").strip()
                    if text or stable:
                        await ws.send_json(
                            {
                                "type": "partial",
                                "text": text or stable,
                                "stableText": stable,
                                "language": getattr(state, "language", None),
                            }
                        )

            elif msg.type == web.WSMsgType.ERROR:
                break

    except Exception as exc:
        if not ws.closed:
            await ws.send_json({"type": "error", "message": str(exc)})

    finally:
        if backend == "qwen" and configured and session is not None and state is not None:
            try:
                state = await asyncio.to_thread(session.finish_streaming, state)
                text = (getattr(state, "text", "") or "").strip()
                if text and not ws.closed:
                    await ws.send_json(
                        {
                            "type": "final",
                            "text": text,
                            "language": getattr(state, "language", None),
                        }
                    )
            except Exception:
                pass

        if fluid:
            try:
                await fluid.finalize()
            except Exception:
                pass
            await fluid.close()

        if fluid_pump:
            fluid_pump.cancel()

        await ws.close()

    return ws


app = web.Application()
app.router.add_get("/health", health)
app.router.add_get("/models", models)
app.router.add_post("/models/install", install_model)
app.router.add_get("/stream", stream)

if __name__ == "__main__":
    web.run_app(app, host=HOST, port=PORT, access_log=None)
