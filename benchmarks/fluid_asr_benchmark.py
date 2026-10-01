#!/usr/bin/env python3
import argparse
import json
import os
import struct
import subprocess
import sys
import time
import wave
from pathlib import Path

APP_DIR = Path.home() / "Library/Application Support/YouTubeLiveTranslator"
DEFAULT_BRIDGE = APP_DIR / "bin/fluid-bridge"

def frame(kind, payload=b""):
    body = bytes([kind]) + payload
    return struct.pack("<I", len(body)) + body

def load_pcm16_wav(path):
    with wave.open(str(path), "rb") as wf:
        if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getframerate() != 16000:
            raise RuntimeError("Fluid benchmark expects 16kHz mono PCM16 WAV")
        return wf.readframes(wf.getnframes())

def run_fluid(audio, bridge):
    pcm = load_pcm16_wav(audio)
    started = time.perf_counter()
    proc = subprocess.Popen(
        [str(bridge)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    proc.stdin.write(frame(0, json.dumps({"diarization": False}).encode()))
    proc.stdin.flush()

    ready = False
    finals = []
    load_done = None

    while True:
        line = proc.stdout.readline()
        if not line:
            break
        msg = json.loads(line)
        if msg.get("type") == "ready":
            ready = True
            load_done = time.perf_counter()
            break

    if not ready:
        err = proc.stderr.read().decode(errors="replace")
        proc.kill()
        raise RuntimeError(f"FluidAudio did not become ready: {err[-1200:]}")

    chunk = 16000 * 2 // 2  # 500 ms PCM16 mono
    infer_started = time.perf_counter()
    for i in range(0, len(pcm), chunk):
        proc.stdin.write(frame(1, pcm[i:i + chunk]))
        proc.stdin.flush()

    proc.stdin.write(frame(2))
    proc.stdin.flush()
    proc.stdin.close()

    for raw in proc.stdout:
        try:
            msg = json.loads(raw)
        except Exception:
            continue
        if msg.get("type") == "utterance" and msg.get("final") and msg.get("text"):
            finals.append(str(msg["text"]).strip())

    proc.wait(timeout=10)
    ended = time.perf_counter()
    return {
        "engine": "fluid-parakeet-eou",
        "model": "Parakeet EOU 120M / FluidAudio",
        "load_s": round((load_done or infer_started) - started, 3),
        "transcribe_s": round(ended - infer_started, 3),
        "text": " ".join(finals).strip(),
        "detected_language": "English",
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("audio")
    parser.add_argument("--bridge", default=str(DEFAULT_BRIDGE))
    parser.add_argument("--output", default="fluid-asr-result.json")
    args = parser.parse_args()

    audio = Path(args.audio).expanduser().resolve()
    bridge = Path(args.bridge).expanduser()
    if not audio.exists():
        raise SystemExit(f"Audio not found: {audio}")
    if not bridge.exists():
        raise SystemExit(
            f"FluidAudio bridge not found: {bridge}\n"
            "Run the macOS installer first."
        )

    result = run_fluid(audio, bridge)
    Path(args.output).write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"load={result['load_s']}s transcribe={result['transcribe_s']}s")
    print(result["text"])
    print(f"Wrote {args.output}")

if __name__ == "__main__":
    main()
