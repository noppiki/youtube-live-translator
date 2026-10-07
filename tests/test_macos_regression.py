from __future__ import annotations

import ast
import importlib
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_SERVER = ROOT / "local-server"
INSTALLER = ROOT / "scripts" / "install-macos.sh"
LAUNCHER = ROOT / "native-host" / "launcher.py"


class MacOSRegressionTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(LOCAL_SERVER))
        self._env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        for name in list(sys.modules):
            if name in {"server", "runtime", "paths"} or name.startswith("backends"):
                sys.modules.pop(name, None)

    def test_installer_still_installs_mlx_and_fluid(self):
        text = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("mlx-qwen3-asr", text)
        self.assertIn("mlx-lm", text)
        self.assertIn("fluid-bridge", text)
        self.assertIn("launchctl", text)
        self.assertIn("DreamFoundries/gemma-4-E4B-it-4bit", text)
        self.assertIn("Library/Application Support/YouTubeLiveTranslator", text)
        self.assertIn("backends/", text)

    def test_launcher_keeps_launchctl_on_macos(self):
        sys.path.insert(0, str(ROOT / "native-host"))
        os.environ["YTLT_OS"] = "macos"
        sys.modules.pop("launcher", None)
        launcher = importlib.import_module("launcher")
        source = LAUNCHER.read_text(encoding="utf-8")
        self.assertIn("/bin/launchctl", source)
        self.assertTrue(str(launcher.plist_path()).endswith("com.noppiki.youtube-live-translator.plist"))
        tree = ast.parse(source)
        names = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        self.assertIn("ensure_started_macos", names)
        self.assertIn("launchctl", names)

    def test_stream_auto_uses_fluid_only_when_macos_and_english_diarization(self):
        os.environ["YTLT_OS"] = "macos"
        os.environ["YTLT_APP_DIR"] = "/tmp/ytlt-mac-regression"
        fluid = Path("/tmp/ytlt-mac-regression/bin/fluid-bridge")
        fluid.parent.mkdir(parents=True, exist_ok=True)
        fluid.write_text("ok", encoding="utf-8")
        server = importlib.import_module("server")
        self.assertEqual(server._choose_stream_backend("auto", "en", True), "fluid")
        self.assertEqual(server._choose_stream_backend("auto", "ja", True), "qwen")
        self.assertEqual(server._choose_stream_backend("qwen", "en", True), "qwen")

    def test_windows_never_selects_fluid(self):
        os.environ["YTLT_OS"] = "windows"
        os.environ["YTLT_APP_DIR"] = "/tmp/ytlt-win-regression"
        for name in list(sys.modules):
            if name in {"server", "runtime", "paths"} or name.startswith("backends"):
                sys.modules.pop(name, None)
        server = importlib.import_module("server")
        self.assertEqual(server._choose_stream_backend("fluid", "en", True), "qwen")
        self.assertEqual(server._choose_stream_backend("auto", "en", True), "qwen")

    def test_macos_health_keeps_legacy_fields(self):
        os.environ["YTLT_OS"] = "macos"
        os.environ["YTLT_APP_DIR"] = "/tmp/ytlt-mac-health"
        server = importlib.import_module("server")
        payload = server._health_payload()
        self.assertEqual(payload["os"], "macos")
        self.assertEqual(payload["asrBackend"], "mlx")
        self.assertEqual(payload["translationBackend"], "mlx")
        self.assertEqual(payload["accelerator"], "metal")
        self.assertEqual(payload["defaultModel"], "moona3k/mlx-qwen3-asr-0.6b-4bit")
        self.assertIn("fluidAudio", payload)
        self.assertIn("translation", payload)
        self.assertEqual(payload["translation"]["toJapanese"], ["en", "ko", "zh", "es", "fr", "de"])
