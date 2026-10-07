from __future__ import annotations

from typing import Protocol


TRANSLATION_SYSTEM = """You translate live-stream captions into concise, natural Japanese subtitles.
Use recent dialogue only as context. Translate CURRENT only.
Output Japanese only. Do not leave Korean, Chinese, Spanish, French, German, or other source-language words in the output unless they are proper names, product names, model names, acronyms, or glossary-preserved terms.
Preserve person names, product names, model names, acronyms, and technical terms in Latin script unless the glossary explicitly specifies a Japanese form.
Follow the glossary exactly.
Do not explain or add notes.
Prefer natural spoken Japanese over literal wording.
Never drop meaning, negation, numbers, measurement units, or currency units.
If a number has a unit in the source, keep the unit in Japanese in the translation."""


def build_translation_user(text: str, context, glossary, source: str, target: str) -> str:
    recent = "\n".join(str(x) for x in (context or [])[-3:]) or "(none)"
    glossary_text = "\n".join(f"- {x}" for x in (glossary or [])) or "(none)"
    return f"""SOURCE LANGUAGE: {source}
TARGET LANGUAGE: {target}

RECENT CONTEXT:
{recent}

GLOSSARY:
{glossary_text}

CURRENT:
{text}"""


def strip_choice_prefix(result: str) -> str:
    cleaned = result.strip()
    for prefix in ("A:", "B:", "C:", "D:"):
        if cleaned.startswith(prefix):
            return cleaned[len(prefix):].strip()
    return cleaned


class TranslationBackend(Protocol):
    model_id: str
    loaded: bool

    def translate(self, text: str, context, glossary, source: str, target: str) -> str: ...
