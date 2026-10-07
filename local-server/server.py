#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import platform
import sys
from pathlib import Path

import numpy as np
from aiohttp import web

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backends import create_asr_session, get_translation_backend
from backends.fluid import FluidProcess
from runtime import profile, resolve_model_id

HOST = "127.0.0.1"
PORT = int(os.environ.get("YTLT_PORT", "8765"))

_sessions = {}
_session_lock = asyncio.Lock()
_translation_backend = None
_translation_lock = asyncio.Lock()
_translation_inference_lock = asyncio.Lock()


def current_profile():
    return profile()


def _allowed_origin(request: web.Request) -> bool:
    origin = request.headers.get("Origin")
    return origin is None or origin.startswith("chrome-extension://")


def _is_english(language) -> bool:
    if language is None:
        return False
    value = str(language).lower()
    return value in {"en", "english", "en-us", "en-gb"}


async def get_session(model_id: str):
    resolved = resolve_model_id(model_id)
    async with _session_lock:
        session = _sessions.get(resolved)
        if session is None:
            session = await asyncio.to_thread(create_asr_session, resolved)
            _sessions[resolved] = session
        return session, resolved


async def get_translator():
    global _translation_backend
    async with _translation_lock:
        if _translation_backend is None:
            _translation_backend = get_translation_backend()
        return _translation_backend


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

    translator = await get_translator()
    async with _translation_inference_lock:
        translated = await asyncio.to_thread(
            translator.translate,
            text,
            data.get("context") or [],
            data.get("glossary") or [],
            source,
            target,
        )
    return web.json_response({
        "ok": True,
        "translated": translated,
        "model": translator.model_id,
    })


def _health_payload():
    current = current_profile()
    translator = _translation_backend
    return {
        "ok": True,
        "service": "youtube-live-translator-local",
        "version": "0.5.0",
        "platform": platform.machine(),
        "os": current.os,
        "asrBackend": current.asr_backend,
        "translationBackend": current.translation_backend,
        "accelerator": current.accelerator,
        "diarizationAvailable": current.diarization_available,
        "defaultModel": current.default_model,
        "loadedModels": list(_sessions.keys()),
        "models": current.models,
        "performanceWarning": current.performance_warning,
        "translation": {
            "model": current.translation_model,
            "loaded": bool(translator and translator.loaded),
            "toJapanese": ["en", "ko", "zh", "es", "fr", "de"],
        },
        "fluidAudio": {
            "available": current.os == "macos" and current.fluid_bridge.exists(),
            "path": str(current.fluid_bridge),
            "englishStreaming": current.os == "macos",
            "diarization": current.diarization_available,
        },
    }


async def health(request: web.Request):
    return web.json_response(_health_payload())


async def models(request: web.Request):
    current = current_profile()
    return web.json_response(
        {
            "ok": True,
            "models": current.models,
            "loaded": list(_sessions),
            "fluidAudio": {
                "available": current.os == "macos" and current.fluid_bridge.exists(),
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
    current = current_profile()

    if engine == "fluid":
        if current.os != "macos" or not current.fluid_bridge.exists():
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

    model_id = resolve_model_id(data.get("model"), current)
    await get_session(model_id)
    return web.json_response({"ok": True, "engine": "qwen", "model": model_id})


def _choose_stream_backend(requested: str, language, want_diarization: bool) -> str:
    current = current_profile()
    fluid_ready = current.os == "macos" and current.fluid_bridge.exists()
    if requested == "fluid":
        if not fluid_ready:
            return "qwen"
        return "fluid"
    if requested == "qwen":
        return "qwen"
    if want_diarization and _is_english(language) and fluid_ready:
        return "fluid"
    return "qwen"


async def stream(request: web.Request):
    if not _allowed_origin(request):
        raise web.HTTPForbidden()

    ws = web.WebSocketResponse(heartbeat=15, max_msg_size=2 * 1024 * 1024)
    await ws.prepare(request)
    current = current_profile()

    config = {
        "model": current.default_model,
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
        want_diarization = bool(config.get("diarization", False)) and current.diarization_available
        backend = _choose_stream_backend(requested, language, want_diarization)

        if backend == "fluid":
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

        model_id = resolve_model_id(config.get("model") or current.default_model, current)
        await ws.send_json({
            "type": "preparing",
            "backend": "qwen",
            "message": "Qwen3-ASRモデルを読み込んでいます…",
        })
        session, model_id = await get_session(model_id)
        kwargs = {
            "chunk_size_sec": float(config.get("chunkSizeSec", 1.0)),
            "max_context_sec": float(config.get("maxContextSec", 30.0)),
            "context": str(config.get("context") or "").strip(),
        }
        if language and str(language).lower() not in ("auto", "multi"):
            kwargs["language"] = language
        state = session.init_streaming(**kwargs)
        configured = True
        warning = None
        if bool(config.get("diarization", False)) and not current.diarization_available:
            warning = "Speaker diarization is not available on this OS yet."
        elif bool(config.get("diarization", False)):
            warning = "Speaker diarization requires the FluidAudio English backend."
        await ws.send_json(
            {
                "type": "ready",
                "backend": "qwen",
                "model": model_id,
                "language": language or "auto",
                "diarization": False,
                "warning": warning,
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
app.router.add_post("/translate", translate)
app.router.add_get("/stream", stream)


def main():
    web.run_app(app, host=HOST, port=PORT, access_log=None)


if __name__ == "__main__":
    main()
