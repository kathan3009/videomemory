"""Build TTS-narrated test fixtures.

Each fixture is a tiny MP4 with a still image + speech, so whisper has
something to transcribe. We use `say` on macOS or `espeak-ng` on Linux —
both ship on developer machines / CI runners with one install line.

Idempotent: skips fixtures already on disk.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
DATA = HERE / "data"
DATA.mkdir(parents=True, exist_ok=True)


def has_tts() -> bool:
    return bool(shutil.which("say") or shutil.which("espeak-ng") or shutil.which("espeak"))


def _ffmpeg() -> str:
    f = shutil.which("ffmpeg")
    if not f:
        raise RuntimeError("ffmpeg not installed")
    return f


def _run(args: list[str]) -> None:
    proc = subprocess.run(args, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(args)}\n{proc.stderr.decode(errors='replace')[:400]}"
        )


def _tts_to_wav(text: str, dst: Path, rate: int = 16000) -> None:
    """Synth `text` into a mono WAV at `dst` using whatever TTS we have."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if platform.system() == "Darwin" and shutil.which("say"):
        # `say` outputs AIFF; convert to WAV via ffmpeg.
        with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as tf:
            aiff = Path(tf.name)
        try:
            _run(["say", "-r", "190", "-o", str(aiff), text])
            _run([_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
                  "-i", str(aiff), "-ac", "1", "-ar", str(rate), str(dst)])
        finally:
            aiff.unlink(missing_ok=True)
        return
    for cmd in ("espeak-ng", "espeak"):
        if shutil.which(cmd):
            _run([cmd, "-w", str(dst), "-s", "170", text])
            # Ensure correct sample rate
            tmp = dst.with_suffix(".tmp.wav")
            _run([_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
                  "-i", str(dst), "-ac", "1", "-ar", str(rate), str(tmp)])
            tmp.replace(dst)
            return
    raise RuntimeError("no TTS tool available (need `say` on macOS or `espeak-ng` on Linux)")


def _concat_wavs(wavs: list[Path], dst: Path) -> None:
    """Concatenate WAVs head-to-tail using ffmpeg concat demuxer."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        for w in wavs:
            f.write(f"file '{w.resolve()}'\n")
        listfile = f.name
    try:
        _run([_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
              "-f", "concat", "-safe", "0", "-i", listfile,
              "-c", "copy", str(dst)])
    finally:
        Path(listfile).unlink(missing_ok=True)


def _font(size: int) -> ImageFont.FreeTypeFont:
    for c in (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(c).exists():
            return ImageFont.truetype(c, size)
    return ImageFont.load_default()


def _slide_png(text: str, bg: tuple[int, int, int], dst: Path) -> None:
    img = Image.new("RGB", (720, 404), bg)
    d = ImageDraw.Draw(img)
    f = _font(44)
    bbox = d.textbbox((0, 0), text, font=f)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((720 - w) // 2, (404 - h) // 2), text, fill=(255, 255, 255), font=f)
    img.save(dst, "PNG")


@dataclass
class Slide:
    text: str        # spoken
    label: str       # shown on screen
    bg: tuple[int, int, int]


def _slide_to_mp4(slide: Slide, dst: Path) -> None:
    """Generate one (audio + image) segment as an MP4."""
    png = dst.with_suffix(".png")
    _slide_png(slide.label, slide.bg, png)
    wav = dst.with_suffix(".wav")
    _tts_to_wav(slide.text, wav)
    _run([
        _ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-i", str(png),
        "-i", str(wav),
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "stillimage",
        "-c:a", "aac", "-b:a", "96k",
        "-pix_fmt", "yuv420p",
        "-shortest", "-vf", "scale=720:404",
        str(dst),
    ])


def _build(slides: list[Slide], out: Path) -> None:
    if out.exists():
        return
    parts_dir = DATA / f"_{out.stem}_parts"
    parts_dir.mkdir(exist_ok=True)
    parts: list[Path] = []
    for i, sl in enumerate(slides):
        p = parts_dir / f"p{i}.mp4"
        _slide_to_mp4(sl, p)
        parts.append(p)
    # Concat
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        for c in parts:
            f.write(f"file '{c.resolve()}'\n")
        listfile = f.name
    try:
        _run([_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
              "-f", "concat", "-safe", "0", "-i", listfile,
              "-c", "copy", str(out)])
    finally:
        Path(listfile).unlink(missing_ok=True)


def build_tutorial() -> Path:
    """A 3-segment tutorial: Tailwind → OAuth → Docker."""
    out = DATA / "tutorial.mp4"
    _build([
        Slide(
            text="First, we install Tailwind CSS by running n p m install tailwind c s s and configuring postcss.",
            label="Tailwind CSS",
            bg=(20, 50, 110),
        ),
        Slide(
            text="Next, we set up OAuth two point zero authentication using the J W T token flow.",
            label="OAuth 2.0",
            bg=(20, 90, 60),
        ),
        Slide(
            text="Finally, we deploy with Docker compose to production using a multi stage build.",
            label="Docker Compose",
            bg=(110, 60, 20),
        ),
    ], out)
    return out


def build_science() -> Path:
    """A 2-segment science clip: Krebs cycle → photosynthesis."""
    out = DATA / "science.mp4"
    _build([
        Slide(
            text="The Krebs cycle, also called the citric acid cycle, generates A T P through oxidative phosphorylation in the mitochondria.",
            label="Krebs Cycle",
            bg=(40, 40, 80),
        ),
        Slide(
            text="Photosynthesis converts carbon dioxide and water into glucose using sunlight in the chloroplasts of plant cells.",
            label="Photosynthesis",
            bg=(40, 80, 40),
        ),
    ], out)
    return out


def build_silent() -> Path:
    """A 30s SILENT video with 3 distinctly-coloured visual scenes (no narration).

    Used to verify that `frames(...)` still works when transcript-based skip()
    would fall flat (mimics a visual-comedy YouTube short like 'How Animals Eat').
    """
    out = DATA / "silent.mp4"
    if out.exists():
        return out
    parts_dir = DATA / "_silent_parts"
    parts_dir.mkdir(exist_ok=True)
    colors = [(180, 60, 60), (60, 180, 60), (60, 60, 180)]
    labels = ["RED PANEL", "GREEN PANEL", "BLUE PANEL"]
    parts: list[Path] = []
    for i, (color, label) in enumerate(zip(colors, labels, strict=True)):
        png = parts_dir / f"p{i}.png"
        _slide_png(label, color, png)
        mp4 = parts_dir / f"p{i}.mp4"
        _run([
            _ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
            "-loop", "1", "-t", "10",
            "-i", str(png),
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "stillimage",
            "-pix_fmt", "yuv420p",
            "-vf", "scale=720:404",
            str(mp4),
        ])
        parts.append(mp4)
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        for p in parts:
            f.write(f"file '{p.resolve()}'\n")
        listfile = f.name
    try:
        _run([
            _ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", listfile,
            "-c", "copy", str(out),
        ])
    finally:
        Path(listfile).unlink(missing_ok=True)
    return out


def build_all() -> dict[str, Path]:
    if not has_tts():
        raise RuntimeError("no TTS tool available — install `espeak-ng` on Linux")
    return {
        "tutorial": build_tutorial(),
        "science": build_science(),
        "silent": build_silent(),
    }


if __name__ == "__main__":
    if not has_tts():
        print("no TTS available; install `say` (macOS) or `espeak-ng` (Linux)")
        raise SystemExit(1)
    built = build_all()
    for name, p in built.items():
        size_kb = p.stat().st_size // 1024
        print(f"{name}: {p} ({size_kb} KiB)")
