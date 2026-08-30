from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from features.neural_separation.catalog import DEFAULT_MODEL_ID


@dataclass(frozen=True, slots=True)
class NeuralJob:
    song: Path
    output_dir: Path
    model_id: str = DEFAULT_MODEL_ID
    models_dir: Path | None = None
    language: str = "zh_cn"
