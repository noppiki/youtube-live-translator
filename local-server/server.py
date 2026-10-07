#!/usr/bin/env python3
import asyncio
import json
import os
import traceback
import platform
import struct
from pathlib import Path

import numpy as np
from aiohttp import web

from backends import (
    app_dir,
    create_asr_backend,
    create_translation_backend,
    runtime_metadata,
)

HOST = "127.0.0.1"
PORT = int(os.environ.get("YTLT_PORT", "8765"))
APP_DIR = app_dir()
FLUID_BRIDGE = Path(os.environ.get("YTLT_FLUID_BRIDGE", APP_DIR / "bin/fluid-bridge"))
RUNTIME = runtime_metadata(fluid_bridge=FLUID_BRIDGE)
TRANSLATION_MODEL = os.environ.get(
    "YTLT_TRANSLATION_MODEL",
    "DreamFoundries/gemma-4-E4B-it-4bit"
    if RUNTIME.translation_backend == "mlx"
    else "gemma-4-E4B-it-qat-q4_0",
)
ASR_BACKEND = create_asr_backend(RUNTIME)
TRANSLATION_BACKEND = create_translation_backend(RUNTIME, TRANSLATION_MODEL)
MODELS = ASR_BACKEND.models
DEFAULT_MODEL = os.environ.get("YTLT_MODEL", MODELS["balanced"]["id"])


def _allowed_origin(request: web.Request) -> bool:
    origin = request.headers.get("Origin")
    return origin is None or origin.startswith("chrome-extension://")


def _is_english(language) -> bool:
    if language is None:
        return False
    value = str(language).lower()
    return value in {"en", "english", "en-us", "en-gb"}


async def get_session(model_id: str):
    """Load an ASR model through the selected platform adapter."""

    return await ASR_BACKEND.get_session(model_id)


async def translate(request: web.Request):
    if not _allowed_origin(request):
        raise web.HTTPForbidden()

    data = await request.json()
    text = str(data.get("text") or "").strip()
    source = str(data.get("sourceLanguage") or "en").lower()
    target = str(data.get("targetLanguage") or "ja").lower()

    if not text:
        return web.json_response({"ok": True, "translated": ""})
    supported_sources = {"en", "english", "en-us", "en-gb", "ko", "kr", "zh", "zh-cn", "zh-tw", "es", "fr", "de"}
    if source not in supported_sources or target != "ja":
        raise web.HTTPBadRequest(text="Local smart translation supports English/Korean/Chinese/Spanish/French/German → Japanese.")

    translated = await TRANSLATION_BACKEND.translate(
        text,
        data.get("context") or [],
        data.get("glossary") or [],
        source,
        target,
    )
    return web.json_response({
        "ok": True,
        "translated": translated,
        "model": TRANSLATION_MODEL,
    })

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
        if not RUNTIME.diarization_available:
            raise RuntimeError("FluidAudio is available on macOS only in this release.")

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
                    continue
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


def build_health_payload() -> dict[str, object]:
    """Build the health payload without performing model inference."""

    return {
        "ok": True,
        "service": "youtube-live-translator-local",
        "version": "0.5.9",
        "platform": platform.machine(),
        "defaultModel": DEFAULT_MODEL,
        "loadedModels": ASR_BACKEND.loaded_models,
        "models": MODELS,
        **RUNTIME.as_dict(),
        "translation": {
            "model": TRANSLATION_MODEL,
            "loaded": TRANSLATION_BACKEND.loaded,
            "backend": RUNTIME.translation_backend,
            "endpoint": getattr(TRANSLATION_BACKEND, "url", None),
            "toJapanese": ["en", "ko", "zh", "es", "fr", "de"],
        },
        "fluidAudio": {
            "available": RUNTIME.diarization_available,
            "path": str(FLUID_BRIDGE),
            "englishStreaming": RUNTIME.os == "macos",
            "diarization": RUNTIME.diarization_available,
        },
    }


async def health(request: web.Request):
    return web.json_response(build_health_payload())


async def models(request: web.Request):
    return web.json_response(
        {
            "ok": True,
            "models": MODELS,
            "loaded": ASR_BACKEND.loaded_models,
            **RUNTIME.as_dict(),
            "fluidAudio": {
                "available": RUNTIME.diarization_available,
                "asr": "Parakeet EOU 120M / 320 ms" if RUNTIME.os == "macos" else None,
                "diarization": "Sortformer" if RUNTIME.diarization_available else None,
            },
        }
    )


async def install_model(request: web.Request):
    if not _allowed_origin(request):
        raise web.HTTPForbidden()

    data = await request.json()
    engine = data.get("engine", "qwen")

    if engine == "fluid":
        if not RUNTIME.diarization_available:
            raise web.HTTPBadRequest(text="FluidAudio is available on macOS only")
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
            backend = (
                "fluid"
                if want_diarization and _is_english(language) and RUNTIME.diarization_available
                else "qwen"
            )

        if backend == "fluid":
            if not RUNTIME.diarization_available:
                raise ValueError("FluidAudio live ASR is available on macOS only.")
            if not _is_english(language):
                raise ValueError("FluidAudio live ASR is currently enabled for English only.")
            await ws.send_json({
                "type": "preparing",
                "backend": "fluid",
                "message": "FluidAudioモデルを準備しています…",
            })
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
        await ws.send_json({
            "type": "preparing",
            "backend": "qwen",
            "message": "Qwen3-ASRモデルを読み込んでいます…",
        })
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
                "warning": "Speaker diarization is currently unavailable on Windows."
                if want_diarization and RUNTIME.os == "windows"
                else "Speaker diarization requires the FluidAudio English backend."
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
        traceback.print_exc()
        if not ws.closed:
            message = f"{type(exc).__name__}: {exc}"
            await ws.send_json({"type": "error", "message": message})

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
app.router.add_post("/translate", translate)
app.router.add_get("/stream", stream)

if __name__ == "__main__":
    web.run_app(app, host=HOST, port=PORT, access_log=None)
