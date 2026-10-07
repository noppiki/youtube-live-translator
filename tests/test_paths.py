from __future__ import annotations

import importlib
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_SERVER = ROOT / "local-server"


class PathResolutionTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(LOCAL_SERVER))
        self._env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        for name in ("paths", "runtime"):
            sys.modules.pop(name, None)

    def _reload(self):
        sys.modules.pop("paths", None)
        sys.modules.pop("runtime", None)
        return importlib.import_module("paths"), importlib.import_module("runtime")

    def test_env_override_wins(self):
        os.environ["YTLT_APP_DIR"] = "/tmp/ytlt-override"
        os.environ["YTLT_OS"] = "macos"
        paths, _ = self._reload()
        self.assertEqual(paths.app_dir(), Path("/tmp/ytlt-override"))

    def test_macos_default_app_dir(self):
        os.environ.pop("YTLT_APP_DIR", None)
        os.environ["YTLT_OS"] = "macos"
        paths, _ = self._reload()
        self.assertEqual(
            paths.app_dir(),
            Path.home() / "Library/Application Support/YouTubeLiveTranslator",
        )

    def test_windows_default_app_dir(self):
        os.environ.pop("YTLT_APP_DIR", None)
        os.environ["YTLT_OS"] = "windows"
        os.environ["LOCALAPPDATA"] = "/tmp/localapp"
        paths, _ = self._reload()
        self.assertEqual(paths.app_dir(), Path("/tmp/localapp/YouTubeLiveTranslator"))
