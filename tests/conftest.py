"""Shared fixtures for the integration tests.

We build synthetic videos once at the start of the test session and share an
ingest cache across tests so we don't re-run the heavy CLIP/whisper pipeline
between test functions.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make sure src/ layout and the tests/ package root are importable.
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from tests.fixtures import make_videos  # noqa: E402
from videomemory.pipeline.runner import run_ingest  # noqa: E402


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    paths = make_videos.build_all()
    return paths["tech_talk"].parent


@pytest.fixture(scope="session")
def tech_talk_path(fixtures_dir: Path) -> Path:
    return fixtures_dir / "tech_talk.mp4"


@pytest.fixture(scope="session")
def temporal_path(fixtures_dir: Path) -> Path:
    return fixtures_dir / "temporal.mp4"


@pytest.fixture(scope="session")
def whiteboard_path(fixtures_dir: Path) -> Path:
    return fixtures_dir / "whiteboard.mp4"


@pytest.fixture(scope="session")
def session_data_dir(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("vm_data")


@pytest.fixture(scope="session")
async def tech_talk_ingest(session_data_dir: Path, tech_talk_path: Path):
    job = await run_ingest(str(tech_talk_path), data_dir=session_data_dir)
    return job


@pytest.fixture(scope="session")
async def temporal_ingest(session_data_dir: Path, temporal_path: Path):
    job = await run_ingest(str(temporal_path), data_dir=session_data_dir)
    return job


@pytest.fixture(scope="session")
async def whiteboard_ingest(session_data_dir: Path, whiteboard_path: Path):
    job = await run_ingest(str(whiteboard_path), data_dir=session_data_dir)
    return job
