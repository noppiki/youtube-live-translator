#!/usr/bin/env python3
import asyncio
import base64
import collections
import json
import os
import time
import traceback
import platform
import secrets
import struct
import uuid
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

# Voice enrollment (speaker identification) state.
# Enrolled speakers live in a small JSON store under the app dir; embeddings
# are computed by the fluid-bridge process on macOS (WeSpeaker via FluidAudio).
SPEAKERS_PATH = APP_DIR / "speakers.json"
SPEAKER_MATCH_MAX_DISTANCE = float(
    os.environ.get("YTLT_SPEAKER_MATCH_DISTANCE", "0.55")
)
SPEAKER_BUFFER_SECONDS = 40.0
# Seconds of buffered speaker audio at which identification is (re)attempted.
SPEAKER_IDENTIFY_STEPS = (4.0, 12.0, 25.0)
PCM16_BYTES_PER_SECOND = 16000 * 2
# Popup enrollment accepts clips up to 60s; 60s PCM16 + base64 + JSON
# overhead stays well under this cap.
ENROLL_MAX_AUDIO_SECONDS = 60
ENROLL_MAX_BODY_BYTES = 8 * 1024 * 1024
# Matches exactly 60s of PCM16 (with a small slack), so an oversized clip is
# rejected before decoding instead of being silently trimmed.
ENROLL_MAX_AUDIO_BASE64 = int(
    ENROLL_MAX_AUDIO_SECONDS * PCM16_BYTES_PER_SECOND * 4 / 3
) + 256
# Speaker endpoints authenticate via SPEAKER_TOKEN handed out through Native
# Messaging; the host manifest's allowed_origins decides which extensions may
# reach it. YTLT_EXTENSION_ID adds an explicit trusted ID (e.g. dev installs).
PINNED_EXTENSION_ID = os.environ.get("YTLT_EXTENSION_ID") or ""
NATIVE_MANIFEST_NAME = "com.noppiki.youtube_live_translator.json"

# Per-process credential for the speaker API. The extension obtains it via
# Native Messaging (launcher.py), which Chrome only exposes to extensions
# listed in the host manifest's allowed_origins — so unlike the forgeable
# Origin header it actually authenticates the caller. Same-user processes can
# read APP_DIR anyway; this boundary is about other extensions and web pages.
SPEAKER_TOKEN = secrets.token_hex(32)
SPEAKER_TOKEN_FILE = APP_DIR / "speaker.token"


def _write_speaker_token() -> None:
    try:
        SPEAKER_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SPEAKER_TOKEN_FILE.with_suffix(".tmp")
        tmp.write_text(SPEAKER_TOKEN)
        tmp.chmod(0o600)
        tmp.replace(SPEAKER_TOKEN_FILE)
    except Exception:
        pass


_write_speaker_token()

EMBEDDING_HELPER = None
EMBEDDING_HELPER_LOCK = asyncio.Lock()
# Refreshed while a fluid streaming session is configured so the REST API can
# enroll a detected live speaker and push names to the overlay.
LIVE_STREAM = {"fluid": None, "audio": {}, "identified": {}, "ws": None}


def load_speakers() -> list:
    try:
        data = json.loads(SPEAKERS_PATH.read_text("utf-8"))
        speakers = data.get("speakers")
        return speakers if isinstance(speakers, list) else []
    except Exception:
        return []


def save_speakers(speakers: list) -> None:
    SPEAKERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SPEAKERS_PATH.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({"speakers": speakers}, ensure_ascii=False), "utf-8"
    )
    tmp.replace(SPEAKERS_PATH)


def match_speaker_name(embedding, speakers=None):
    """Return (speaker, cosine_distance) for the closest enrolled voice."""

    if speakers is None:
        speakers = load_speakers()
    query = np.asarray(embedding, dtype=np.float32)
    norm = float(np.linalg.norm(query))
    if not np.isfinite(norm) or norm <= 0:
        return None
    query /= norm

    best = None
    for speaker in speakers:
        candidate = np.asarray(speaker.get("embedding"), dtype=np.float32)
        if candidate.shape != query.shape:
            continue
        candidate_norm = float(np.linalg.norm(candidate))
        if not np.isfinite(candidate_norm) or candidate_norm <= 0:
            continue
        distance = 1.0 - float(np.dot(query, candidate / candidate_norm))
        if best is None or distance < best[1]:
            best = (speaker, distance)

    if best and best[1] <= SPEAKER_MATCH_MAX_DISTANCE:
        return best
    return None


async def embedding_provider() -> "FluidProcess":
    """Dedicated lightweight bridge process for voice embeddings.

    Extraction runs outside the streaming bridge so a one-time model download
    never stalls live ASR/diarization.
    """

    global EMBEDDING_HELPER
    async with EMBEDDING_HELPER_LOCK:
        helper = EMBEDDING_HELPER
        if helper and helper.proc and helper.proc.returncode is None:
            return helper
        helper = FluidProcess(diarization=False, embedding_only=True)
        await helper.start()
        EMBEDDING_HELPER = helper
        return helper


def _allowed_origin(request: web.Request) -> bool:
    origin = request.headers.get("Origin")
    return origin is None or origin.startswith("chrome-extension://")


def _native_manifest_paths():
    home = Path.home()
    return [
        APP_DIR / "native" / NATIVE_MANIFEST_NAME,
        home / "Library/Application Support/Google/Chrome/NativeMessagingHosts" / NATIVE_MANIFEST_NAME,
        home / ".config/google-chrome/NativeMessagingHosts" / NATIVE_MANIFEST_NAME,
        home / ".config/chromium/NativeMessagingHosts" / NATIVE_MANIFEST_NAME,
        home / ".config/microsoft-edge/NativeMessagingHosts" / NATIVE_MANIFEST_NAME,
    ]


def _trusted_extension_ids() -> set:
    ids = set()
    if PINNED_EXTENSION_ID:
        ids.add(PINNED_EXTENSION_ID)
    for path in _native_manifest_paths():
        try:
            manifest = json.loads(path.read_text("utf-8"))
        except Exception:
            continue
        for origin in manifest.get("allowed_origins") or []:
            if isinstance(origin, str) and origin.startswith("chrome-extension://"):
                ids.add(origin.rstrip("/")[len("chrome-extension://") :])
    return ids


def _is_extension_origin(request: web.Request) -> bool:
    """Fallback gate for installs with no Native Messaging registration."""

    prefix = "chrome-extension://"
    origin = request.headers.get("Origin") or ""
    if not origin.startswith(prefix):
        return False
    trusted = _trusted_extension_ids()
    if not trusted:
        # Native Messaging was never registered (e.g. dev box): any extension
        # origin may call — still excludes non-extension local clients.
        return True
    return origin[len(prefix) :].rstrip("/") in trusted


def _speaker_api_authorized(request: web.Request) -> bool:
    """The token is the credential once Native Messaging is registered; the
    extension-only Origin check only remains for unregistered dev installs."""

    token = (request.headers.get("X-YTLT-Token") or "").strip()
    if token and secrets.compare_digest(token, SPEAKER_TOKEN):
        return True
    if _trusted_extension_ids():
        return False
    return _is_extension_origin(request)


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
    def __init__(self, diarization: bool, embedding_only: bool = False):
        self.diarization = diarization
        self.embedding_only = embedding_only
        self.proc = None
        self.queue = asyncio.Queue()
        self.ready = asyncio.Event()
        self.reader_task = None
        self.stderr_task = None
        self.embedding_requests = {}
        self._next_request_id = 0
        self.embedding_ready = asyncio.Event()
        self.embedding_error = None

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

        config = json.dumps(
            {
                "diarization": self.diarization,
                "embeddingOnly": self.embedding_only,
            }
        ).encode("utf-8")
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
                kind = message.get("type")
                if kind == "ready":
                    self.ready.set()
                    continue
                if kind in ("embedding", "embeddingError"):
                    request_id = message.get("requestId")
                    if request_id is not None:
                        future = self.embedding_requests.pop(int(request_id), None)
                        if future and not future.done():
                            if kind == "embedding":
                                future.set_result(message.get("embedding") or [])
                            else:
                                future.set_exception(
                                    RuntimeError(
                                        message.get("message")
                                        or "Embedding extraction failed"
                                    )
                                )
                    else:
                        # Embedding errors without a request id belong to a
                        # prepare (model download) call.
                        self.embedding_error = message.get("message")
                        self.embedding_ready.set()
                    continue
                if kind == "embeddingReady":
                    self.embedding_ready.set()
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

    async def prepare_embedding(self, timeout=900):
        """Pre-download the speaker-embedding model in the bridge."""

        if not self.proc or self.proc.returncode is not None:
            raise RuntimeError("FluidAudio bridge is not running.")
        self.proc.stdin.write(self._frame(4))
        await self.proc.stdin.drain()
        await asyncio.wait_for(self.embedding_ready.wait(), timeout=timeout)
        if self.embedding_error:
            raise RuntimeError(self.embedding_error)

    async def request_embedding(self, pcm16: bytes, timeout=120):
        """Compute a speaker embedding for 16kHz mono PCM16 audio."""

        if not self.proc or self.proc.returncode is not None:
            raise RuntimeError("FluidAudio bridge is not running.")
        self._next_request_id += 1
        request_id = self._next_request_id
        future = asyncio.get_running_loop().create_future()
        self.embedding_requests[request_id] = future
        try:
            payload = struct.pack("<I", request_id) + bytes(pcm16)
            self.proc.stdin.write(self._frame(3, payload))
            await self.proc.stdin.drain()
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self.embedding_requests.pop(request_id, None)

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

        for future in self.embedding_requests.values():
            if not future.done():
                future.set_exception(RuntimeError("FluidAudio bridge closed."))
        self.embedding_requests.clear()


def build_health_payload() -> dict[str, object]:
    """Build the health payload without performing model inference."""

    return {
        "ok": True,
        "service": "youtube-live-translator-local",
        "version": "0.6.0",
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
            if data.get("voiceprint"):
                await fluid.prepare_embedding(timeout=900)
            return web.json_response(
                {
                    "ok": True,
                    "engine": "fluid",
                    "diarization": bool(data.get("diarization", False)),
                    "voiceprint": bool(data.get("voiceprint")),
                }
            )
        finally:
            await fluid.close()

    model_id = data.get("model")
    if model_id not in {v["id"] for v in MODELS.values()}:
        raise web.HTTPBadRequest(text="Unknown model")
    await get_session(model_id)
    return web.json_response({"ok": True, "engine": "qwen", "model": model_id})


async def list_speakers(request: web.Request):
    if not _speaker_api_authorized(request):
        raise web.HTTPForbidden()

    identified = LIVE_STREAM.get("identified")
    if identified is None:
        identified = {}
    seconds_of = LIVE_STREAM.get("seconds_of")
    indices = LIVE_STREAM.get("indices")
    live = {}
    if callable(seconds_of) and callable(indices):
        for index in indices():
            seconds = seconds_of(index)
            if seconds >= 1.0:
                live[str(index)] = {
                    "seconds": round(seconds, 1),
                    "identified": index in identified,
                }
    return web.json_response(
        {
            "ok": True,
            "speakers": [
                {
                    "id": speaker.get("id"),
                    "name": speaker.get("name"),
                    "createdAt": speaker.get("createdAt"),
                }
                for speaker in load_speakers()
            ],
            "live": live,
            "matching": {
                "available": RUNTIME.diarization_available,
                "maxDistance": SPEAKER_MATCH_MAX_DISTANCE,
            },
        }
    )


async def enroll_speaker(request: web.Request):
    if not _speaker_api_authorized(request):
        raise web.HTTPForbidden()
    if not RUNTIME.diarization_available:
        raise web.HTTPBadRequest(
            text="声紋登録は macOS の FluidAudio 環境でのみ利用できます。"
        )

    data = await request.json()
    name = str(data.get("name") or "").strip()[:80]
    if not name:
        raise web.HTTPBadRequest(text="名前を入力してください。")

    pcm = b""
    live_index = data.get("speakerIndex")
    if live_index is not None:
        pcm_for = LIVE_STREAM.get("pcm_for")
        pcm = pcm_for(int(live_index)) if callable(pcm_for) else b""
        if not pcm:
            raise web.HTTPBadRequest(
                text="その話者の音声がまだ十分に録れていません。"
            )
    else:
        encoded = data.get("audioBase64")
        if not encoded:
            raise web.HTTPBadRequest(text="音声データがありません。")
        if len(encoded) > ENROLL_MAX_AUDIO_BASE64:
            raise web.HTTPBadRequest(
                text=f"音声は{ENROLL_MAX_AUDIO_SECONDS}秒以内にしてください。"
            )
        try:
            pcm = base64.b64decode(encoded)
        except Exception:
            raise web.HTTPBadRequest(text="音声データの形式が不正です。")

    if len(pcm) < PCM16_BYTES_PER_SECOND:
        raise web.HTTPBadRequest(text="1秒以上の音声が必要です。")
    pcm = pcm[-ENROLL_MAX_AUDIO_SECONDS * PCM16_BYTES_PER_SECOND :]

    try:
        helper = await embedding_provider()
        embedding = await helper.request_embedding(pcm, timeout=600)
    except Exception as exc:
        raise web.HTTPBadGateway(
            text=f"声紋モデルで埋め込みを作成できませんでした: {exc}"
        )

    speakers = load_speakers()
    existing = next((s for s in speakers if s.get("name") == name), None)
    if existing is not None:
        existing["embedding"] = [float(v) for v in embedding]
        existing["createdAt"] = time.time()
        speaker_id = existing["id"]
    else:
        speaker_id = uuid.uuid4().hex[:12]
        speakers.append(
            {
                "id": speaker_id,
                "name": name,
                "embedding": [float(v) for v in embedding],
                "createdAt": time.time(),
            }
        )
    save_speakers(speakers)

    # Re-identify currently buffered live speakers with the new enrollment.
    identified = LIVE_STREAM.get("identified")
    if identified is None:
        identified = {}
    stream_ws = LIVE_STREAM.get("ws")

    async def push_speaker_name(index: int, speaker_name: str, distance: float):
        if stream_ws and not stream_ws.closed:
            await stream_ws.send_json(
                {
                    "type": "speakerName",
                    "speaker": index,
                    "name": speaker_name,
                    "confidence": 0.99 if speaker_name else 0.0,
                    "distance": round(distance, 3),
                    "source": "voice-enrollment",
                }
            )

    pcm_for = LIVE_STREAM.get("pcm_for")
    indices_fn = LIVE_STREAM.get("indices")
    if live_index is not None:
        identified[int(live_index)] = {"id": speaker_id, "name": name}
        await push_speaker_name(int(live_index), name, 0.0)
    if callable(pcm_for) and callable(indices_fn):
        for index in indices_fn():
            buffered = pcm_for(index)
            if index in identified or len(buffered) < 2 * PCM16_BYTES_PER_SECOND:
                continue
            try:
                candidate = await helper.request_embedding(buffered, timeout=600)
            except Exception:
                continue
            match = match_speaker_name(candidate, speakers)
            if match:
                speaker, distance = match
                identified[index] = {
                    "id": speaker.get("id"),
                    "name": speaker["name"],
                }
                await push_speaker_name(index, speaker["name"], distance)

    return web.json_response(
        {"ok": True, "speaker": {"id": speaker_id, "name": name}}
    )


async def delete_speaker(request: web.Request):
    if not _speaker_api_authorized(request):
        raise web.HTTPForbidden()

    speaker_id = request.match_info["speaker_id"]
    speakers = load_speakers()
    remaining = [s for s in speakers if s.get("id") != speaker_id]
    if len(remaining) == len(speakers):
        raise web.HTTPNotFound(text="登録済みの話者が見つかりません。")
    save_speakers(remaining)

    # Invalidate live labels produced from the deleted voice so the
    # overlay falls back to the generic speaker name and re-matching
    # against the remaining voices becomes possible.
    identified = LIVE_STREAM.get("identified")
    if identified:
        attempts = LIVE_STREAM.get("attempts")
        if attempts is None:
            attempts = {}
        stream_ws = LIVE_STREAM.get("ws")
        stale = [
            index
            for index, value in identified.items()
            if isinstance(value, dict) and value.get("id") == speaker_id
        ]
        for index in stale:
            identified.pop(index, None)
            attempts.pop(index, None)
            if stream_ws and not stream_ws.closed:
                await stream_ws.send_json(
                    {
                        "type": "speakerName",
                        "speaker": index,
                        "name": "",
                        "confidence": 0.0,
                        "distance": 0.0,
                        "source": "voice-enrollment",
                    }
                )
    return web.json_response({"ok": True})


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

    # Voice-identification state for the current fluid session.
    # Sortformer reports speaker changes *after* the fact (changeAtMs is the
    # true boundary), so we keep a timestamped audio log plus the reported
    # timeline and attribute samples to speakers only on demand.
    audio_chunks = collections.deque()  # (end_ms, pcm16 bytes)
    audio_elapsed_ms = [0.0]
    # Bytes attributed to each speaker that have already expired out of
    # audio_chunks — lets sparse speakers accumulate toward the threshold
    # across turns separated by >SPEAKER_BUFFER_SECONDS of silence.
    expired_speaker_bytes = collections.Counter()
    speaker_timeline = []  # sorted [(changeAtMs, speaker)]
    identified_speakers = {}  # index -> {"id": enrollment id, "name": str}
    identify_attempts = {}

    def buffer_audio_chunk(pcm16: bytes):
        chunk_ms = len(pcm16) * 1000 / PCM16_BYTES_PER_SECOND
        audio_elapsed_ms[0] += chunk_ms
        audio_chunks.append((audio_elapsed_ms[0], bytes(pcm16)))
        cutoff = audio_elapsed_ms[0] - (SPEAKER_BUFFER_SECONDS + 5) * 1000
        while audio_chunks and audio_chunks[0][0] < cutoff:
            end_ms, data = audio_chunks.popleft()
            owner = speaker_at(end_ms - len(data) * 500 / PCM16_BYTES_PER_SECOND)
            if owner is not None:
                expired_speaker_bytes[owner] += len(data)

    def record_speaker_point(speaker, change_at_ms):
        if not isinstance(speaker, int) or not isinstance(change_at_ms, (int, float)):
            return
        if any(t == change_at_ms and s == speaker for t, s in speaker_timeline):
            return
        speaker_timeline.append((change_at_ms, speaker))
        speaker_timeline.sort()
        del speaker_timeline[:-64]

    def speaker_at(ms):
        current = None
        for change_at, speaker in speaker_timeline:
            if change_at <= ms:
                current = speaker
            else:
                break
        return current

    def speaker_pcm(speaker_index, max_seconds=SPEAKER_BUFFER_SECONDS):
        out = bytearray()
        for end_ms, data in audio_chunks:
            midpoint = end_ms - len(data) * 500 / PCM16_BYTES_PER_SECOND
            if speaker_at(midpoint) == speaker_index:
                out.extend(data)
        cap = int(max_seconds * PCM16_BYTES_PER_SECOND)
        if len(out) > cap:
            del out[: len(out) - cap]
        return bytes(out)

    def speaker_seconds(speaker_index):
        total = expired_speaker_bytes.get(speaker_index, 0)
        total += sum(
            len(data)
            for end_ms, data in audio_chunks
            if speaker_at(end_ms - len(data) * 500 / PCM16_BYTES_PER_SECOND)
            == speaker_index
        )
        return total / PCM16_BYTES_PER_SECOND

    def live_speaker_indices():
        return sorted({speaker for _, speaker in speaker_timeline})

    async def send_speaker_name(speaker_index: int, name: str, distance: float):
        if not ws.closed:
            await ws.send_json(
                {
                    "type": "speakerName",
                    "speaker": speaker_index,
                    "name": name,
                    "confidence": 0.99 if name else 0.0,
                    "distance": round(distance, 3),
                    "source": "voice-enrollment",
                }
            )

    async def identify_speaker(speaker_index: int):
        """Match buffered audio of a Sortformer speaker against enrolled voices."""

        if speaker_index in identified_speakers:
            return
        pcm = speaker_pcm(speaker_index)
        if len(pcm) < 2 * PCM16_BYTES_PER_SECOND:
            return
        try:
            helper = await embedding_provider()
            embedding = await helper.request_embedding(pcm)
        except Exception:
            return
        match = match_speaker_name(embedding)
        if match:
            speaker, distance = match
            identified_speakers[speaker_index] = {
                "id": speaker.get("id"),
                "name": speaker["name"],
            }
            await send_speaker_name(speaker_index, speaker["name"], distance)

    def maybe_identify(speaker_index):
        if speaker_index in identified_speakers:
            return
        buffered_sec = speaker_seconds(speaker_index)
        step = identify_attempts.get(speaker_index, 0)
        if step >= len(SPEAKER_IDENTIFY_STEPS) or buffered_sec < SPEAKER_IDENTIFY_STEPS[step]:
            return
        # Only consume an attempt when enough in-window audio exists to
        # embed — otherwise a sparse speaker burns attempts on empty turns.
        if len(speaker_pcm(speaker_index)) < 2 * PCM16_BYTES_PER_SECOND:
            return
        identify_attempts[speaker_index] = step + 1
        asyncio.create_task(identify_speaker(speaker_index))

    async def pump_fluid():
        while fluid:
            message = await fluid.queue.get()
            kind = message.get("type")
            if kind == "closed":
                break
            if kind == "debug":
                continue
            if kind == "speaker":
                record_speaker_point(message.get("speaker"), message.get("changeAtMs"))
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
            LIVE_STREAM["fluid"] = fluid
            LIVE_STREAM["pcm_for"] = speaker_pcm
            LIVE_STREAM["seconds_of"] = speaker_seconds
            LIVE_STREAM["indices"] = live_speaker_indices
            LIVE_STREAM["identified"] = identified_speakers
            LIVE_STREAM["attempts"] = identify_attempts
            LIVE_STREAM["ws"] = ws
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
                    buffer_audio_chunk(bytes(msg.data))
                    current = speaker_at(audio_elapsed_ms[0])
                    if current is not None:
                        maybe_identify(current)
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

        LIVE_STREAM["fluid"] = None
        LIVE_STREAM["pcm_for"] = None
        LIVE_STREAM["seconds_of"] = None
        LIVE_STREAM["indices"] = None
        LIVE_STREAM["identified"] = {}
        LIVE_STREAM["attempts"] = {}
        LIVE_STREAM["ws"] = None

        if fluid_pump:
            fluid_pump.cancel()

        await ws.close()

    return ws


app = web.Application(client_max_size=ENROLL_MAX_BODY_BYTES)
app.router.add_get("/health", health)
app.router.add_get("/models", models)
app.router.add_post("/models/install", install_model)
app.router.add_post("/translate", translate)
app.router.add_get("/stream", stream)
app.router.add_get("/speakers", list_speakers)
app.router.add_post("/speakers/enroll", enroll_speaker)
app.router.add_delete("/speakers/{speaker_id}", delete_speaker)

if __name__ == "__main__":
    web.run_app(app, host=HOST, port=PORT, access_log=None)
