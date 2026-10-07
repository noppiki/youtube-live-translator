from __future__ import annotations

import asyncio
import json
import struct
from pathlib import Path

from runtime import profile


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
        current = profile()
        if not current.diarization_available and not current.fluid_bridge.exists():
            raise RuntimeError("FluidAudio bridge is not installed. Re-run the macOS installer.")
        if current.os != "macos":
            raise RuntimeError("FluidAudio is available on macOS only.")
        if not current.fluid_bridge.exists():
            raise RuntimeError("FluidAudio bridge is not installed. Re-run the macOS installer.")

        self.proc = await asyncio.create_subprocess_exec(
            str(current.fluid_bridge),
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


def fluid_bridge_path() -> Path:
    return profile().fluid_bridge
