from __future__ import annotations

from typing import Any


class MlxQwenAsr:
    def create_session(self, model_id: str) -> Any:
        from mlx_qwen3_asr import Session

        return Session(model=model_id)
