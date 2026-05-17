"""Scene detection via PySceneDetect."""

from __future__ import annotations

from pathlib import Path

from scenedetect import ContentDetector, SceneManager, open_video


def detect_scenes(video_path: Path, threshold: float = 27.0, min_scene_len: float = 1.0) -> list[tuple[float, float]]:
    """Return list of (start_seconds, end_seconds) scenes."""
    video = open_video(str(video_path))
    sm = SceneManager()
    sm.add_detector(ContentDetector(threshold=threshold, min_scene_len=int(min_scene_len * video.frame_rate)))
    sm.detect_scenes(video, show_progress=False)
    scenes = sm.get_scene_list()
    if not scenes:
        # PySceneDetect didn't find cuts → treat the whole thing as one scene
        duration = float(video.duration.get_seconds()) if video.duration else 0.0
        if duration <= 0:
            duration = 1.0
        return [(0.0, duration)]
    return [(s.get_seconds(), e.get_seconds()) for s, e in scenes]
