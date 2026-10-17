"""The object every detector returns."""
from dataclasses import KW_ONLY, dataclass, field


@dataclass
class Event:
    type_id: str                  # key in rules.json
    t_start: float                # onset of the visible violation -> timecode_sec
    _: KW_ONLY                    # everything below must be passed by name
    t_end: float | None = None
    confidence: float = 0.5
    # Plain-language facts actually observed, e.g. "кассир вышел из помещения,
    # на столе остались наличные". Goes into the description verbatim.
    observation: str = ""
    # Extra moments worth showing as evidence (onset is always included).
    evidence_times: list[float] = field(default_factory=list)
    # Optional boxes to draw: {t_sec: [(x1, y1, x2, y2, label), ...]} in pixels.
    boxes: dict[float, list[tuple]] = field(default_factory=dict)
