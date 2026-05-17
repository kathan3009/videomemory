"""Artifact path layout under `<data_dir>/videos/<video_id>/`.

Layout:

    data/
        videomemory.sqlite
        videos/
            <video_id>/
                source.<ext>            # the original or downloaded video
                metadata.json
                frames/<frame_id>.jpg
                scenes.json
                transcript.json
                vision.json
                memory.json             # entities, events, edges
                chunks.json
                embeddings/             # numpy or parquet (optional cache)
                .stages/                # stage marker files for resumability
"""

from __future__ import annotations

from pathlib import Path


class ArtifactPaths:
    def __init__(self, data_dir: Path, video_id: str) -> None:
        self.data_dir = Path(data_dir)
        self.video_id = video_id
        self.root = self.data_dir / "videos" / video_id

    def ensure(self) -> None:
        for sub in ("frames", "embeddings", ".stages"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    @property
    def metadata_json(self) -> Path:
        return self.root / "metadata.json"

    @property
    def scenes_json(self) -> Path:
        return self.root / "scenes.json"

    @property
    def transcript_json(self) -> Path:
        return self.root / "transcript.json"

    @property
    def vision_json(self) -> Path:
        return self.root / "vision.json"

    @property
    def memory_json(self) -> Path:
        return self.root / "memory.json"

    @property
    def chunks_json(self) -> Path:
        return self.root / "chunks.json"

    @property
    def frames_dir(self) -> Path:
        return self.root / "frames"

    @property
    def embeddings_dir(self) -> Path:
        return self.root / "embeddings"

    def stage_marker(self, stage: str) -> Path:
        return self.root / ".stages" / f"{stage}.done"

    def source_path(self, ext: str = "mp4") -> Path:
        ext = ext.lstrip(".")
        return self.root / f"source.{ext}"

    def find_source(self) -> Path | None:
        for p in self.root.glob("source.*"):
            return p
        return None


def db_path(data_dir: Path) -> Path:
    return Path(data_dir) / "videomemory.sqlite"
