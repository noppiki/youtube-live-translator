from __future__ import annotations

import importlib
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_SERVER = ROOT / "local-server"


class RuntimeProfileTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(LOCAL_SERVER))
        self._env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        for name in ("paths", "runtime"):
            sys.modules.pop(name, None)

    def _runtime(self):
        sys.modules.pop("paths", None)
        sys.modules.pop("runtime", None)
        importlib.import_module("paths")
        return importlib.import_module("runtime")

    def test_macos_profile_keeps_mlx_and_fluid_path(self):
        os.environ["YTLT_OS"] = "macos"
        os.environ["YTLT_APP_DIR"] = "/tmp/ytlt-mac"
        os.environ.pop("YTLT_ASR_BACKEND", None)
        os.environ.pop("YTLT_TRANSLATE_BACKEND", None)
        runtime = self._runtime()
        current = runtime.profile()
        self.assertEqual(current.os, "macos")
        self.assertEqual(current.asr_backend, "mlx")
        self.assertEqual(current.translation_backend, "mlx")
        self.assertEqual(current.accelerator, "metal")
        self.assertEqual(current.models["balanced"]["id"], "moona3k/mlx-qwen3-asr-0.6b-4bit")
        self.assertEqual(current.fluid_bridge, Path("/tmp/ytlt-mac/bin/fluid-bridge"))
        self.assertFalse(current.diarization_available)

    def test_windows_profile_uses_torch_and_disables_diarization(self):
        os.environ["YTLT_OS"] = "windows"
        os.environ["YTLT_APP_DIR"] = "/tmp/ytlt-win"
        os.environ["YTLT_ACCELERATOR"] = "cpu"
        os.environ.pop("YTLT_ASR_BACKEND", None)
        os.environ.pop("YTLT_TRANSLATE_BACKEND", None)
        runtime = self._runtime()
        current = runtime.profile()
        self.assertEqual(current.os, "windows")
        self.assertEqual(current.asr_backend, "torch")
        self.assertEqual(current.translation_backend, "llamacpp")
        self.assertEqual(current.accelerator, "cpu")
        self.assertFalse(current.diarization_available)
        self.assertEqual(current.models["balanced"]["id"], "Qwen/Qwen3-ASR-0.6B-hf")
        self.assertIn("CPU only", current.performance_warning or "")

    def test_windows_accepts_mlx_model_alias(self):
        os.environ["YTLT_OS"] = "windows"
        os.environ["YTLT_APP_DIR"] = "/tmp/ytlt-win"
        runtime = self._runtime()
        self.assertEqual(
            runtime.resolve_model_id("moona3k/mlx-qwen3-asr-0.6b-4bit"),
            "Qwen/Qwen3-ASR-0.6B-hf",
        )
        self.assertEqual(
            runtime.resolve_model_id("moona3k/mlx-qwen3-asr-1.7b-4bit"),
            "Qwen/Qwen3-ASR-1.7B-hf",
        )
