"""Shared fixtures: build TTS narrated mp4s once, ingest once, share across tests."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session", autouse=True)
def _isolated_data_dir(tmp_path_factory):
    """Every test session gets its own data dir so we don't clobber user libraries."""
    d = tmp_path_factory.mktemp("vm_data")
    os.environ["VIDEOMEMORY_DATA_DIR"] = str(d)
    yield d


@pytest.fixture(scope="session")
def fixtures_built():
    from tests.fixtures.make_videos import build_all, has_tts

    if not has_tts():
        pytest.skip("no TTS available — install `say` (macOS) or `espeak-ng` (Linux)")
    return build_all()


@pytest.fixture(scope="session")
def tutorial_path(fixtures_built) -> Path:
    return fixtures_built["tutorial"]


@pytest.fixture(scope="session")
def science_path(fixtures_built) -> Path:
    return fixtures_built["science"]


@pytest.fixture(scope="session")
def tutorial_ingested(tutorial_path):
    from videomemory.ingest import ingest

    return asyncio.run(ingest(str(tutorial_path)))


@pytest.fixture(scope="session")
def science_ingested(science_path):
    from videomemory.ingest import ingest

    return asyncio.run(ingest(str(science_path)))
