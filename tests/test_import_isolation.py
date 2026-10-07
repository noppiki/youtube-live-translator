from __future__ import annotations

import ast
import importlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "local-server" / "server.py"
LOCAL_SERVER = ROOT / "local-server"

BLOCKED = {"mlx", "mlx_lm", "mlx_qwen3_asr", "torch", "transformers"}


def _top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


class ImportIsolationTests(unittest.TestCase):
    def test_server_has_no_mlx_or_torch_toplevel_imports(self):
        names = _top_level_imports(SERVER)
        self.assertFalse(names & BLOCKED)

    def test_backend_package_has_no_mlx_or_torch_toplevel_imports(self):
        names = _top_level_imports(LOCAL_SERVER / "backends" / "__init__.py")
        self.assertFalse(names & BLOCKED)

    def test_server_import_does_not_load_mlx_or_torch(self):
        sys.path.insert(0, str(LOCAL_SERVER))
        for name in list(sys.modules):
            if name == "server" or name.startswith("backends") or name in {"paths", "runtime"}:
                del sys.modules[name]
        before = set(sys.modules)
        importlib.import_module("server")
        loaded = set(sys.modules) - before
        offenders = {name for name in loaded if name.split(".")[0] in BLOCKED}
        self.assertEqual(offenders, set())
