import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parents[1] / "local-server"))

from backends.translation import build_translation_messages, clean_translation


def test_translation_prompt_preserves_context_and_glossary():
    messages = build_translation_messages(
        "The CUDA build is ready.",
        ["Previous sentence"],
        ["CUDA", "NVIDIA"],
        "en",
        "ja",
    )

    assert messages[0]["role"] == "system"
    assert "CURRENT:\nThe CUDA build is ready." in messages[1]["content"]
    assert "- CUDA" in messages[1]["content"]
    assert "Previous sentence" in messages[1]["content"]


def test_clean_translation_removes_chat_labels():
    assert clean_translation("A: これは翻訳です。") == "これは翻訳です。"
    assert clean_translation("  これは翻訳です。  ") == "これは翻訳です。"
