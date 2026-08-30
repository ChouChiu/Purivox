from __future__ import annotations

from importlib.resources import files
from importlib.resources.abc import Traversable


def resource_path(name: str) -> Traversable:
    return files(__package__).joinpath(name)
