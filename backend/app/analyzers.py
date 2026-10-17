"""Analyzers the worker can run: real (ml.pipeline), demo (fake violations), or any
`package.module:function` with the signature of ml.pipeline.analyze (used by tests)."""
import importlib
import time
from typing import Callable

from ml import catalog
from ml.video import probe

from .results import frame_at

Analyzer = Callable[[str, Callable[[float], None] | None], dict]

_DEMO = [
    ("cash_unattended", 0.82,
     "Кассир отошёл от рабочего места, на столе остались наличные без присмотра."),
    ("safe_left_open", 0.71,
     "Дверца сейфа открыта, рядом с сейфом никого нет."),
]


def demo(video_path: str, progress: Callable[[float], None] | None = None) -> dict:
    """Realistic fake violation result for frontend development."""
    started = time.time()
    report = progress or (lambda p: None)
    duration = probe(video_path).duration
    for i in range(1, 9):
        time.sleep(0.5)
        report(i / 10)
    picks = _DEMO if duration >= 12 else _DEMO[:1]
    violations = []
    for k, (type_id, conf, observation) in enumerate(picks, start=1):
        t = round(duration * k / (len(picks) + 1), 2)
        rule = catalog.citation(type_id)
        desc = observation
        if rule:
            desc += f' Возможное нарушение: {rule["document"]}, {rule["clause"]}.'
        violations.append({
            "type": catalog.type_name(type_id),
            "type_id": type_id,
            "timecode_sec": t,
            "confidence": conf,
            "description": desc,
            "rule": rule,
            "evidence_frames": [frame_at(video_path, x, duration)
                                for x in (t, min(t + 2.0, duration))],
        })
    report(1.0)
    return {"verdict": "violation", "violations": violations,
            "processing_sec": round(time.time() - started, 2)}


def load(spec: str) -> Analyzer:
    """Import the analyzer once; the real one may load models here (ml.pipeline.warmup)."""
    if spec == "demo":
        return demo
    if spec == "real":
        from ml import pipeline
        if hasattr(pipeline, "warmup"):
            pipeline.warmup()
        return pipeline.analyze
    module, _, name = spec.partition(":")
    if not name:
        raise ValueError(f"ANALYZER must be real, demo or module:function, got {spec!r}")
    return getattr(importlib.import_module(module), name)
