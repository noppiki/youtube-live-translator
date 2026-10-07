from __future__ import annotations

import importlib
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_SERVER = ROOT / "local-server"


class HealthTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(LOCAL_SERVER))
        self._env = os.environ.copy()
        os.environ["YTLT_OS"] = "windows"
        os.environ["YTLT_APP_DIR"] = "/tmp/ytlt-health"
        os.environ["YTLT_ACCELERATOR"] = "cpu"
        for name in ("server", "runtime", "paths", "backends", "backends.fluid", "backends.translate_llamacpp"):
            sys.modules.pop(name, None)
            if name == "backends":
                for key in list(sys.modules):
                    if key.startswith("backends"):
                        sys.modules.pop(key, None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)

    def _server(self):
        return importlib.import_module("server")

    def test_health_payload_includes_backend_fields(self):
        server = self._server()
        payload = server._health_payload()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["service"], "youtube-live-translator-local")
        self.assertEqual(payload["os"], "windows")
        self.assertEqual(payload["asrBackend"], "torch")
        self.assertEqual(payload["translationBackend"], "llamacpp")
        self.assertEqual(payload["accelerator"], "cpu")
        self.assertFalse(payload["diarizationAvailable"])
        self.assertEqual(payload["models"]["balanced"]["id"], "Qwen/Qwen3-ASR-0.6B-hf")
        self.assertFalse(payload["fluidAudio"]["available"])
        self.assertFalse(payload["fluidAudio"]["diarization"])
        self.assertIn("CPU only", payload["performanceWarning"] or "")

    def test_health_http_returns_200(self):
        from aiohttp.test_utils import TestClient, TestServer

        server = self._server()

        async def run():
            async with TestClient(TestServer(server.app)) as client:
                response = await client.get("/health")
                self.assertEqual(response.status, 200)
                data = await response.json()
                self.assertTrue(data["ok"])
                self.assertEqual(data["os"], "windows")
                self.assertEqual(data["asrBackend"], "torch")

        import asyncio

        asyncio.run(run())
