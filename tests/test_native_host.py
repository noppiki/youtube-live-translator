import importlib.util
from io import BytesIO
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "native-host/launcher.py"
SPEC = importlib.util.spec_from_file_location("ytlt_launcher", MODULE_PATH)
assert SPEC and SPEC.loader
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


def test_native_message_round_trip_preserves_unicode():
    message = {"action": "status", "label": "ローカルAI"}

    encoded = launcher.encode_message(message)

    assert launcher.decode_message(encoded) == message
    assert int.from_bytes(encoded[:4], "little") == len(encoded) - 4


def test_native_message_reader_and_writer_use_one_frame():
    request = launcher.encode_message({"action": "start"})
    output = BytesIO()

    assert launcher.read_message(BytesIO(request)) == {"action": "start"}
    launcher.write_message({"ok": True}, output)

    assert launcher.decode_message(output.getvalue()) == {"ok": True}


def test_native_message_rejects_oversized_payload():
    try:
        launcher.decode_message((launcher.MAX_MESSAGE_SIZE + 1).to_bytes(4, "little"))
    except ValueError as error:
        assert str(error) == "Message too large"
    else:
        raise AssertionError("oversized native message was accepted")


def test_windows_native_host_preserves_crash_logs():
    source = (Path(__file__).parents[1] / "native-host/launcher.py").read_text(encoding="utf-8")
    assert 'log_dir = APP_DIR / "logs"' in source
    assert 'server_env["PYTHONFAULTHANDLER"] = "1"' in source
    assert '[str(python), "-X", "faulthandler", "-u", str(_windows_server())]' in source
    assert 'server.err.log' in source
    assert 'stderr=subprocess.DEVNULL' not in source.split('def start_windows',1)[-1] if 'def start_windows' in source else True
