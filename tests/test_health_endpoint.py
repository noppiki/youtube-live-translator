import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


sys.path.insert(0, str(Path(__file__).parents[1] / "local-server"))
server = pytest.importorskip("server")
from backends.runtime import runtime_metadata


def test_health_payload_reports_mocked_windows_capabilities(monkeypatch):
    monkeypatch.setattr(server, "RUNTIME", runtime_metadata("Windows", {"YTLT_ACCELERATOR": "cpu"}))
    monkeypatch.setattr(
        server,
        "ASR_BACKEND",
        SimpleNamespace(
            loaded_models=[],
            models={"balanced": {"id": "Qwen/Qwen3-ASR-0.6B-hf", "label": "test"}},
        ),
    )
    monkeypatch.setattr(
        server,
        "TRANSLATION_BACKEND",
        SimpleNamespace(loaded=False, name="llamacpp", url="http://127.0.0.1:8766"),
    )

    payload = server.build_health_payload()

    assert payload["ok"] is True
    assert payload["os"] == "windows"
    assert payload["asrBackend"] == "torch"
    assert payload["translationBackend"] == "llamacpp"
    assert payload["accelerator"] == "cpu"
    assert payload["diarizationAvailable"] is False
    assert payload["fluidAudio"]["available"] is False
