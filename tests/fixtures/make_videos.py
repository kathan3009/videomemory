"""Synthesize the test-fixture videos used by the integration tests.

Pillow renders slide PNGs (text + background colour), ffmpeg stitches them
into MP4 clips, ffmpeg's concat demuxer joins clips into final fixtures.
This avoids needing ffmpeg with `drawtext` support (Homebrew's lean build
lacks libfreetype).

Outputs land under tests/fixtures/data/ (gitignored).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
DATA = HERE / "data"
DATA.mkdir(parents=True, exist_ok=True)


def _ffmpeg() -> str:
    f = shutil.which("ffmpeg")
    if not f:
        raise RuntimeError("ffmpeg not installed")
    return f


def _run(args: list[str]) -> None:
    proc = subprocess.run(args, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed: {' '.join(args)}\n{proc.stderr.decode(errors='replace')[:600]}"
        )


def _font(size: int) -> ImageFont.FreeTypeFont:
    candidates = (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for f in candidates:
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def _render_slide(text: str, bg: tuple[int, int, int], fg: tuple[int, int, int], path: Path, size: tuple[int, int] = (720, 404)) -> None:
    img = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(img)
    # Choose a font size that fits
    font_size = 48 if len(text) < 24 else 36
    if len(text) > 38:
        font_size = 28
    font = _font(font_size)
    # Wrap by hand: split if very long
    words = text.split()
    lines: list[str] = []
    current = ""
    for w in words:
        candidate = (current + " " + w).strip()
        bbox = d.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] > size[0] - 80 and current:
            lines.append(current)
            current = w
        else:
            current = candidate
    if current:
        lines.append(current)
    total_h = sum(d.textbbox((0, 0), ln, font=font)[3] - d.textbbox((0, 0), ln, font=font)[1] + 8 for ln in lines)
    y = (size[1] - total_h) // 2
    for ln in lines:
        bbox = d.textbbox((0, 0), ln, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        x = (size[0] - w) // 2
        d.text((x, y), ln, fill=fg, font=font)
        y += h + 8
    img.save(path, "PNG")


@dataclass
class Slide:
    text: str
    bg: tuple[int, int, int]
    fg: tuple[int, int, int] = (255, 255, 255)
    duration: int = 10


def _slide_clip(slide: Slide, out: Path) -> None:
    """Render the slide PNG, then make a duration-long MP4 from it."""
    png = out.with_suffix(".png")
    _render_slide(slide.text, slide.bg, slide.fg, png)
    _run([
        _ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-t", str(slide.duration),
        "-i", str(png),
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-vf", "scale=720:404,format=yuv420p",
        str(out),
    ])


def _concat(parts: list[Path], out: Path) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        for c in parts:
            f.write(f"file '{c.resolve()}'\n")
        list_file = f.name
    try:
        _run([
            _ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0",
            "-i", list_file,
            "-c", "copy",
            str(out),
        ])
    finally:
        Path(list_file).unlink(missing_ok=True)


def _build_video(slides: list[Slide], out: Path, tag: str) -> None:
    if out.exists():
        return
    tmp = DATA / f"_{tag}_parts"
    tmp.mkdir(exist_ok=True)
    parts: list[Path] = []
    for i, sl in enumerate(slides):
        p = tmp / f"p{i}.mp4"
        _slide_clip(sl, p)
        parts.append(p)
    _concat(parts, out)


def _build_temporal(out: Path) -> None:
    _build_video(
        [
            Slide("Scene 1: empty room", (40, 40, 40), (240, 240, 240)),
            Slide("Scene 2: person enters and sits down", (30, 80, 30), (240, 255, 240)),
            Slide("Scene 3: person is now presenting on stage", (80, 30, 30), (255, 240, 240)),
        ],
        out,
        "temporal",
    )


def _build_tech_talk(out: Path) -> None:
    _build_video(
        [
            Slide("Kubernetes Networking", (14, 42, 71), (255, 255, 255)),
            Slide("OAuth 2.0 Flows", (34, 68, 34), (255, 255, 255)),
            Slide("Docker Compose", (68, 68, 17), (255, 255, 255)),
        ],
        out,
        "tech",
    )


def _build_whiteboard(out: Path) -> None:
    _build_video(
        [
            Slide("LAPTOP SCREEN", (17, 17, 17), (0, 255, 255), duration=8),
            Slide("WHITEBOARD", (240, 240, 240), (10, 10, 10), duration=8),
            Slide("ARCHITECTURE DIAGRAM", (220, 220, 255), (10, 10, 10), duration=8),
        ],
        out,
        "wb",
    )


def _build_long(out: Path, duration_s: int = 600) -> None:
    if out.exists():
        return
    tech = DATA / "tech_talk.mp4"
    if not tech.exists():
        _build_tech_talk(tech)
    loops = max(1, duration_s // 30)
    _run([
        _ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
        "-stream_loop", str(loops - 1),
        "-i", str(tech),
        "-c", "copy",
        str(out),
    ])


def build_all() -> dict[str, Path]:
    paths = {
        "temporal": DATA / "temporal.mp4",
        "tech_talk": DATA / "tech_talk.mp4",
        "whiteboard": DATA / "whiteboard.mp4",
    }
    _build_temporal(paths["temporal"])
    _build_tech_talk(paths["tech_talk"])
    _build_whiteboard(paths["whiteboard"])
    return paths


def build_long_if_requested() -> Path:
    p = DATA / "long.mp4"
    _build_long(p, duration_s=600)
    return p


if __name__ == "__main__":
    built = build_all()
    for name, p in built.items():
        print(f"{name}: {p} ({os.path.getsize(p) / 1024:.1f} KiB)")
    if os.environ.get("VIDEOMEMORY_BUILD_LONG"):
        long = build_long_if_requested()
        print(f"long: {long} ({os.path.getsize(long) / 1024 / 1024:.1f} MiB)")
