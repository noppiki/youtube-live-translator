from pathlib import Path


SERVER_SOURCE = (Path(__file__).parents[1] / "local-server/server.py").read_text()


def test_server_does_not_import_mlx_at_module_load():
    assert "from mlx_qwen3_asr import" not in SERVER_SOURCE
    assert "from mlx_lm import" not in SERVER_SOURCE


def test_server_keeps_public_routes_and_health_metadata_keys():
    assert 'app.router.add_get("/health", health)' in SERVER_SOURCE
    assert 'app.router.add_get("/models", models)' in SERVER_SOURCE
    assert 'app.router.add_post("/models/install", install_model)' in SERVER_SOURCE
    assert 'app.router.add_post("/translate", translate)' in SERVER_SOURCE
    assert 'app.router.add_get("/stream", stream)' in SERVER_SOURCE
    for key in ('"os"', '"asrBackend"', '"translationBackend"', '"accelerator"', '"diarizationAvailable"'):
        assert key in (Path(__file__).parents[1] / "local-server/backends/runtime.py").read_text()
