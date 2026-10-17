"""Violation detectors.

Each detector is a function `detect(ctx: Context) -> list[Event]` registered with
@register. To add a violation type: create a module here, decorate its function,
and import the module at the bottom of this file.
"""
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from ..events import Event
from ..video import VideoInfo


@dataclass
class Context:
    """Everything a detector may use. Perception results get added here as the
    pipeline grows (tracks, poses, object detections, per-frame states)."""
    info: VideoInfo
    frames: list[tuple[float, np.ndarray]]          # sampled (t_sec, BGR frame)
    extras: dict = field(default_factory=dict)      # shared perception outputs


DETECTORS: dict[str, Callable[[Context], list[Event]]] = {}


def register(name: str):
    def wrap(fn):
        DETECTORS[name] = fn
        return fn
    return wrap


# Detector modules register themselves on import.
from . import crowd, personal_items, workplace  # noqa: E402,F401
