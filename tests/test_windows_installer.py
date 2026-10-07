from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-windows.ps1"


class WindowsInstallerTests(unittest.TestCase):
    def setUp(self):
        self.text = INSTALLER.read_text(encoding="utf-8")

    def test_script_exists_and_is_parameterized(self):
        self.assertTrue(INSTALLER.exists())
        self.assertRegex(self.text, r"param\s*\(")
        self.assertIn("[string]$ExtensionId", self.text)
        self.assertIn("[switch]$DryRun", self.text)

    def test_required_steps_are_present(self):
        required = [
            "uv",
            ".venv",
            "aiohttp",
            "numpy",
            "torch",
            "transformers",
            "Qwen/Qwen3-ASR-0.6B-hf",
            "llama-server",
            "gemma-4-E4B_q4_0-it.gguf",
            "YouTubeLiveTranslator",
            "NativeMessagingHosts",
            "com.noppiki.youtube_live_translator",
            "/health",
            "8765",
        ]
        missing = [item for item in required if item not in self.text]
        self.assertEqual(missing, [])

    def test_accelerator_fallback_order(self):
        cuda = self.text.find('Install-Llama "cuda"')
        vulkan = self.text.find('Install-Llama "vulkan"')
        cpu = self.text.find('Install-Llama "cpu"')
        self.assertTrue(0 <= cuda < vulkan < cpu)

    def test_extension_id_is_validated(self):
        self.assertRegex(self.text, r"\[a-p\]\{32\}")

    def test_dry_run_exits_before_network(self):
        self.assertIn("if ($DryRun)", self.text)
        self.assertLess(self.text.find("if ($DryRun)"), self.text.find("Invoke-WebRequest"))
