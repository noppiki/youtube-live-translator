from __future__ import annotations

import importlib
import io
import json
import os
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native-host"


class NativeHostTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(NATIVE))
        self._env = os.environ.copy()
        sys.modules.pop("launcher", None)
        self.launcher = importlib.import_module("launcher")

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        sys.modules.pop("launcher", None)

    def test_message_framing_roundtrip(self):
        message = {"action": "status", "ok": True}
        buf = io.BytesIO()
        self.launcher.write_message(message, buf)
        raw = buf.getvalue()
        length = struct.unpack("=I", raw[:4])[0]
        self.assertEqual(length, len(raw) - 4)
        self.assertEqual(json.loads(raw[4:]), message)
        buf.seek(0)
        self.assertEqual(self.launcher.read_message(buf), message)

    def test_oversized_message_is_rejected(self):
        buf = io.BytesIO(struct.pack("=I", 1024 * 1024 + 1) + b"x")
        with self.assertRaises(ValueError):
            self.launcher.read_message(buf)

    def test_macos_status_uses_plist(self):
        os.environ["YTLT_OS"] = "macos"
        sys.modules.pop("launcher", None)
        launcher = importlib.import_module("launcher")
        payload = launcher.handle({"action": "status"})
        self.assertTrue(payload["ok"])
        self.assertIn("installed", payload)
        self.assertIn("running", payload)
        self.assertEqual(payload["installed"], launcher.plist_path().exists())

    def test_windows_status_uses_app_dir_not_plist(self):
        os.environ["YTLT_OS"] = "windows"
        os.environ["YTLT_APP_DIR"] = "/tmp/ytlt-missing"
        sys.modules.pop("launcher", None)
        launcher = importlib.import_module("launcher")
        payload = launcher.handle({"action": "status"})
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["installed"])
        self.assertFalse(payload["running"])
        self.assertIn("taskRegistered", payload)
