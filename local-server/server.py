#!/usr/bin/env python3
import asyncio
import json
import os
import platform
from pathlib import Path

import numpy as np
from aiohttp import web
from mlx_qwen3_asr import Session

HOST = "127.0.0.1"
PORT = int(os.environ.get("YTLT_PORT", "8765"))
DEFAULT_MODEL = os.environ.get(
    "YTLT_MODEL", "moona3k/mlx-qwen3-asr-0.6b-4bit"
)
MODELS = {
    "balanced": {
        "id": "moona3k/mlx-qwen3-asr-0.6b-4bit",
        "label": "Qwen3-ASR 0.6B 4-bit (推奨)",
    },
    "accuracy": {
        "id": "moona3k/mlx-qwen3-asr-1.7b-4bit",
        "label": "Qwen3-ASR 1.7B 4-bit (高精度)",
    },
}
_sessions = {}
_session_lock = asyncio.Lock()


def _allowed_origin(request: web.Request) -> bool:
    origin = request.headers.get("Origin")
    return origin is None or origin.startswith("chrome-extension://")


async def get_session(model_id: str) -> Session:
    async with _session_lock:
        session = _sessions.get(model_id)
        if session is None:
            session = await asyncio.to_thread(Session, model=model_id)
            _sessions[model_id] = session
        return session


async def health(request: web.Request):
    return web.json_response(
        {
            "ok": True,
            "service": "youtube-live-translator-local",
            "version": "0.2.0",
            "platform": platform.machine(),
            "defaultModel": DEFAULT_MODEL,
            "loadedModels": list(_sessions.keys()),
            "models": MODELS,
        }
    )


async def models(request: web.Request):
    return web.json_response({"ok": True, "models": MODELS, "loaded": list(_sessions)})


async def install_model(request: web.Request):
    if not _allowed_origin(request):
        raise web.HTTPForbidden()
    data = await request.json()
    model_id = data.get("model")
    if model_id not in {v["id"] for v in MODELS.values()}:
        raise web.HTTPBadRequest(text="Unknown model")
    await get_session(model_id)
    return web.json_response({"ok": True, "model": model_id})


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
    }
    session = None
    state = None
    audio_buffer = bytearray()
    configured = False

    async def configure(payload):
        nonlocal session, state, configured
        model_id = payload.get("model") or DEFAULT_MODEL
        if model_id not in {v["id"] for v in MODELS.values()}:
            raise ValueError("Unsupported local model")
        config.update(payload)
        session = await get_session(model_id)
        kwargs = {
            "chunk_size_sec": float(config.get("chunkSizeSec", 1.0)),
            "max_context_sec": float(config.get("maxContextSec", 30.0)),
            "context": str(config.get("context") or "").strip(),
        }
        language = config.get("language")
        if language and language not in ("auto", "multi"):
            kwargs["language"] = language
        state = session.init_streaming(**kwargs)
        configured = True
        await ws.send_json(
            {
                "type": "ready",
                "model": model_id,
                "language": language or "auto",
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
                audio_buffer.extend(msg.data)
                # PCM16 mono @ 16 kHz; process about 1 second at a time.
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
        if configured and session is not None and state is not None:
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
        await ws.close()

    return ws


async def on_startup(app):
    # Warm the balanced model so the first subtitle is fast.
    asyncio.create_task(get_session(DEFAULT_MODEL))


app = web.Application()
app.router.add_get("/health", health)
app.router.add_get("/models", models)
app.router.add_post("/models/install", install_model)
app.router.add_get("/stream", stream)
app.on_startup.append(on_startup)

if __name__ == "__main__":
    web.run_app(app, host=HOST, port=PORT, access_log=None)
