from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np


@dataclass
class StreamingState:
    text: str = ""
    stable_text: str = ""
    language: str | None = None
    chunk_size_sec: float = 1.0
    max_context_sec: float = 30.0
    context: str = ""
    language_hint: str | None = None
    buffer: Any = field(default=None)


class AsrSession(Protocol):
    def init_streaming(
        self,
        chunk_size_sec: float = 1.0,
        max_context_sec: float = 30.0,
        context: str = "",
        language: str | None = None,
    ) -> Any: ...

    def feed_audio(self, pcm: np.ndarray, state: Any) -> Any: ...

    def finish_streaming(self, state: Any) -> Any: ...


class AsrBackend(Protocol):
    def create_session(self, model_id: str) -> AsrSession: ...
