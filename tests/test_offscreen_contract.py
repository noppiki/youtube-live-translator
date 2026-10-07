from pathlib import Path


OFFSCREEN = Path(__file__).parents[1] / "offscreen/offscreen.js"


def test_local_stt_error_is_not_overwritten_by_close_message():
    source = OFFSCREEN.read_text(encoding="utf-8")
    assert "let localSocketError = ''" in source
    assert "localSocketError = message" in source
    assert "&& !localSocketError" in source
    assert "event.reason" in source
    assert "event.code" in source
