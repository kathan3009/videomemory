"""Optional object detection via ultralytics YOLOv8n."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load(model_name: str = "yolov8n.pt"):
    from ultralytics import YOLO

    return YOLO(model_name)


def detect_frame(path: Path, model_name: str = "yolov8n.pt", conf: float = 0.35) -> list[str]:
    try:
        model = _load(model_name)
        results = model(str(path), verbose=False, conf=conf)
    except Exception as exc:
        log.warning("yolo failed on %s: %s", path, exc)
        return []
    labels: set[str] = set()
    for r in results:
        names = r.names if hasattr(r, "names") else {}
        if r.boxes is None:
            continue
        for cls in r.boxes.cls.tolist():
            label = names.get(int(cls)) if isinstance(names, dict) else None
            if label:
                labels.add(label)
    return sorted(labels)


def detect_frames(paths: list[Path], model_name: str = "yolov8n.pt") -> list[list[str]]:
    return [detect_frame(p, model_name) for p in paths]
