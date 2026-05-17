"""Pre-flight: check ffmpeg/yt-dlp/python, optionally pre-pull models, print install snippets."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Status:
    name: str
    ok: bool
    version: str | None = None
    fix: str | None = None


def _which(cmd: str) -> str | None:
    return shutil.which(cmd)


def _run_version(cmd: list[str]) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if out.returncode == 0:
            return (out.stdout or out.stderr).splitlines()[0].strip()
    except Exception:
        return None
    return None


def check() -> list[Status]:
    rows: list[Status] = []

    # Python
    rows.append(Status(name="python", ok=True, version=platform.python_version()))

    # ffmpeg
    ff = _which("ffmpeg")
    rows.append(
        Status(
            name="ffmpeg",
            ok=bool(ff),
            version=_run_version(["ffmpeg", "-version"]) if ff else None,
            fix=None if ff else _install_hint_for("ffmpeg"),
        )
    )

    # yt-dlp
    yt = _which("yt-dlp")
    rows.append(
        Status(
            name="yt-dlp",
            ok=bool(yt),
            version=_run_version(["yt-dlp", "--version"]) if yt else None,
            fix=None if yt else _install_hint_for("yt-dlp"),
        )
    )

    # uv (needed to run via stdio if installed that way)
    uv = _which("uv")
    rows.append(
        Status(
            name="uv",
            ok=bool(uv),
            version=_run_version(["uv", "--version"]) if uv else None,
            fix=None if uv else "curl -LsSf https://astral.sh/uv/install.sh | sh",
        )
    )

    return rows


def _install_hint_for(pkg: str) -> str:
    sysname = platform.system()
    if sysname == "Darwin":
        return f"brew install {pkg}"
    if sysname == "Linux":
        return f"sudo apt-get update && sudo apt-get install -y {pkg}"
    return f"install {pkg} from your package manager"


def prepull_models() -> None:
    """Download whisper + bge so the first ingest is instant."""
    from videomemory.config import embed_model, whisper_model

    # bge
    try:
        from sentence_transformers import SentenceTransformer

        SentenceTransformer(embed_model(), device="cpu")
    except Exception as exc:
        print(f"  [skip] embedding model: {exc}")
    # whisper
    try:
        from faster_whisper import WhisperModel

        WhisperModel(whisper_model(), device="cpu", compute_type="int8")
    except Exception as exc:
        print(f"  [skip] whisper model: {exc}")


def install_snippets(*, project_dir: Path | None = None, data_dir: Path | None = None) -> dict[str, str]:
    """Return ready-to-paste install snippets for each supported client."""
    project_dir = project_dir or Path(__file__).resolve().parents[2]
    data_dir = data_dir or Path(os.environ.get("VIDEOMEMORY_DATA_DIR", str(Path.home() / ".videomemory")))
    args = (
        f"uv run --project {project_dir} videomemory mcp serve "
        f"--data-dir {data_dir}"
    )
    return {
        "claude_code_local": (
            f"claude mcp add -s user videomemory -- {args}"
        ),
        "claude_code_remote": (
            "claude mcp add -s user videomemory "
            "https://example.com/mcp --transport http"
        ),
        "codex_local_json": json.dumps(
            {
                "mcpServers": {
                    "videomemory": {
                        "command": "uv",
                        "args": [
                            "run", "--project", str(project_dir),
                            "videomemory", "mcp", "serve",
                            "--data-dir", str(data_dir),
                        ],
                    }
                }
            },
            indent=2,
        ),
        "codex_remote_json": json.dumps(
            {
                "mcpServers": {
                    "videomemory": {
                        "url": "https://example.com/mcp",
                        "transport": "http",
                    }
                }
            },
            indent=2,
        ),
    }


def to_json(rows: list[Status]) -> str:
    return json.dumps([asdict(r) for r in rows], indent=2)


__all__ = ["check", "prepull_models", "install_snippets", "Status", "to_json"]
