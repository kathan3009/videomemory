"""Generic visual-understanding funnel for any video.

The pipeline spends cheap local compute to discard redundancy *before* spending
expensive Claude-vision tokens. Each stage strictly shrinks the input to the next:

    ffmpeg 1fps dump  →  dHash pixel-dedup  →  CLIP embed  →  semantic dedup
       (decode)            (trivial)           (local GPU)     (cosine>0.92)
          → query-aware top-N → MMR temporal-diversity → contact-sheet pack → CLAUDE

`build_index()` runs the left half once per video (no transcription — purely
visual, so it never pays the whisper cost). `analyze()` runs the right half per
question: retrieve the handful of query-relevant frames and pack them into a
single labeled contact sheet (≈1.5k tokens) instead of N separate full-res images
(≈25k tokens) — a ~16x token reduction at equal-or-better accuracy.

Backed by research (SeViLA: 73.8% on 4 query-selected frames; IG-VLM: a frame
grid beats prior SOTA on 9/10 video-QA benchmarks; LVNet: 12 selected ≈ 90
uniform). See clip_embed for the MobileCLIP-S2 embedder.
"""

from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path

import numpy as np

from videomemory import clip_embed
from videomemory.config import (
    hosted_mode,
    max_video_seconds,
    video_dir,
    visual_candidate_fps,
    visual_candidate_px,
    visual_dhash_threshold,
    visual_semantic_dedup,
)
from videomemory.ingest import (  # type: ignore
    _ffprobe_duration,
    _is_url,
    deep_link,
    fmt_time,
    video_id_for,
)
from videomemory.library import (
    get_video,
    has_visual_frames,
    insert_visual_frames,
    iter_visual_frames,
    mark_index_ready,
    upsert_video,
)
from videomemory.types import Video, VisualAnalysis, VisualFrame

MAX_CANDIDATES = 6000          # safety cap on 1fps candidate frames
RETRIEVE_N = 30                # candidate pool before MMR
DEFAULT_K = 9                  # frames sent to Claude (3x3 sheet)
SEPARATE_K = 6                 # frames when packing separately (IG-VLM knee ~6)
MMR_LAMBDA = 0.6               # relevance vs diversity tradeoff
SHEET_CELL_PX = 512            # per-cell long edge in the contact sheet

# Queries that need fine text → bypass the grid (it destroys small text).
_OCR_HINTS = (
    "read", "text", "says", "word", "caption", "subtitle", "code", "error",
    "number", "price", "name", "label", "sign", "document", "slide", "ui",
    "button", "menu", "spell", "written", "title", "headline", "logo", "url",
)


# ---------- perceptual hash (cheap pixel dedup) --------------------------


def _frame_sig(path: Path, size: int = 8) -> tuple[int, np.ndarray] | None:
    """(dHash, mean_rgb) signature. Mean color disambiguates flat frames whose
    texture-based dHash is degenerate (e.g. solid red vs solid blue both hash 0)."""
    try:
        from PIL import Image

        img = Image.open(path).convert("RGB")
    except Exception:
        return None
    g = np.asarray(img.convert("L").resize((size + 1, size), Image.LANCZOS), dtype=np.int16)
    diff = g[:, 1:] > g[:, :-1]
    bits = 0
    for v in diff.flatten():
        bits = (bits << 1) | int(v)
    mean = np.asarray(img.resize((16, 16), Image.LANCZOS), dtype=np.float32).reshape(-1, 3).mean(axis=0)
    return bits, mean


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


# ---------- video resolution (no transcription) -------------------------


async def _ensure_video(url: str) -> tuple[str, str, Path, float]:
    """Resolve → (video_id, source, local_path, duration). Downloads if a URL."""
    from videomemory.frames import _local_video_path  # local import avoids cycle

    p = Path(url)
    if p.exists():
        vid = video_id_for(url, p)
        local: Path | None = p
        # Record the path so frames.extract_frames can re-seek it (mirrors ingest).
        op = video_dir(vid) / "original_path.txt"
        if not op.exists():
            op.write_text(str(p.resolve()))
    else:
        vid = video_id_for(url)
        local = await _local_video_path(vid, url)
    if local is None or not local.exists():
        raise RuntimeError(f"could not obtain a local video for: {url}")

    existing = get_video(vid)
    duration = existing.duration if existing and existing.duration > 0 else await _ffprobe_duration(local)
    if hosted_mode():
        cap = max_video_seconds()
        if cap > 0 and duration > cap:
            raise ValueError(f"video exceeds the {cap} second hosted limit")
        from videomemory.control import usage_summary
        from videomemory.tenant import current_tenant

        tenant = current_tenant()
        if tenant:
            usage = usage_summary(tenant)
            remaining = max(0.0, usage["limits"]["minutes"] - usage["totals"].get("minutes", 0))
            if duration > remaining * 60:
                raise ValueError("video exceeds the remaining monthly indexed-minutes allowance")
    if existing is None:
        upsert_video(
            Video(
                video_id=vid,
                source=url,
                title=None,
                duration=duration,
                file_path=str(local) if not _is_url(url) else None,
            )
        )
    return vid, url, local, duration


# ---------- candidate extraction ----------------------------------------


_PTS_RE = re.compile(r"pts_time:([0-9.]+)")


async def _dump_candidates(local: Path, out_dir: Path, fps: float, px: int) -> list[tuple[float, Path]]:
    """Sample ~`fps` frames downscaled to `px` long edge (for embed/dedup only).

    Uses `select` (not the `fps` filter) so frame timestamps stay on the ORIGINAL
    timeline, and `showinfo` to read each frame's true `pts_time` — so the
    timestamp we store always matches what a later seek to that time will show.
    """
    if not shutil.which("ffmpeg"):
        return []
    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    step = 1.0 / fps if fps > 0 else 1.0
    scale = f"scale='if(gt(iw,ih),{px},-2)':'if(gt(iw,ih),-2,{px})'"
    select = f"select='isnan(prev_selected_t)+gte(t-prev_selected_t\\,{step})'"
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "info",
        "-i", str(local),
        "-vf", f"{select},{scale},showinfo",
        "-vsync", "vfr", "-q:v", "4",
        "-frames:v", str(MAX_CANDIDATES),
        str(out_dir / "cand_%06d.jpg"),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    times = [float(m) for m in _PTS_RE.findall(err.decode("utf-8", "replace"))]
    files = sorted(out_dir.glob("cand_*.jpg"))
    out: list[tuple[float, Path]] = [(times[i], f) for i, f in enumerate(files) if i < len(times)]
    if len(out) > MAX_CANDIDATES:
        stride = len(out) / MAX_CANDIDATES
        out = [out[int(j * stride)] for j in range(MAX_CANDIDATES)]
    return out


# ---------- index build (left half of the funnel) -----------------------


async def build_index(url: str, *, force: bool = False) -> dict:
    """Build (or reuse) the deduped CLIP visual index for a video."""
    vid, source, local, duration = await _ensure_video(url)
    model = clip_embed.model_id()
    if model is None:
        return {"video_id": vid, "duration": duration, "indexed": 0, "candidates": 0, "model": None}
    if not force and has_visual_frames(vid, model):
        _, rows = iter_visual_frames(vid)
        return {"video_id": vid, "duration": duration, "indexed": len(rows), "candidates": 0, "model": model}

    cand_dir = video_dir(vid) / "cand"
    candidates = await _dump_candidates(local, cand_dir, visual_candidate_fps(), visual_candidate_px())
    n_candidates = len(candidates)
    if not candidates:
        return {"video_id": vid, "duration": duration, "indexed": 0, "candidates": 0, "model": model}

    # Stage 1 — pixel dedup vs the last kept frame (collapses static runs).
    # A frame is a near-duplicate only if BOTH texture (dHash) AND mean color match,
    # so solid/low-texture frames aren't wrongly merged.
    dh_thr = visual_dhash_threshold()
    kept: list[tuple[float, Path, int]] = []  # (t, path, dhash)
    last_hash: int | None = None
    last_mean: np.ndarray | None = None
    for t, path in candidates:
        sig = _frame_sig(path)
        if sig is None:
            continue
        h, mean = sig
        if last_hash is not None and _hamming(h, last_hash) <= dh_thr and float(np.abs(mean - last_mean).sum()) < 30.0:
            continue
        kept.append((t, path, h))
        last_hash, last_mean = h, mean

    # Stage 2 — CLIP embed survivors (the one moderately expensive local step).
    vecs: list = []
    for start in range(0, len(kept), 32):
        batch = [path for _, path, _ in kept[start : start + 32]]
        vecs.extend(await asyncio.to_thread(clip_embed.embed_images, batch))

    # Stage 3 — semantic dedup vs all kept (cosine > threshold = same meaning).
    sem_thr = visual_semantic_dedup()
    rows: list[dict] = []
    semantic_matrix: np.ndarray | None = None
    semantic_count = 0
    for (t, _path, dhash), v in zip(kept, vecs, strict=False):
        if v is None:
            continue
        arr = np.asarray(v, dtype=np.float32)
        if semantic_matrix is None:
            semantic_matrix = np.empty((len(vecs), len(arr)), dtype=np.float32)
        if semantic_count:
            sims = semantic_matrix[:semantic_count] @ arr
            if float(sims.max()) > sem_thr:
                continue
        semantic_matrix[semantic_count] = arr
        semantic_count += 1
        rows.append({"t": t, "dhash": dhash, "vec": v})

    insert_visual_frames(vid, model, rows)
    mark_index_ready(vid, "visual")
    shutil.rmtree(cand_dir, ignore_errors=True)  # candidates were only for embedding
    return {"video_id": vid, "duration": duration, "indexed": len(rows), "candidates": n_candidates, "model": model}


# ---------- retrieval (right half: query-aware + MMR) -------------------


def _mmr(scores: np.ndarray, vecs: np.ndarray, lam: float, k: int) -> list[int]:
    """Maximal Marginal Relevance over a candidate pool → diverse top-k indices."""
    n = len(scores)
    if n == 0:
        return []
    selected: list[int] = []
    remaining = list(range(n))
    while remaining and len(selected) < k:
        best_i, best_val = remaining[0], -1e9
        for i in remaining:
            div = max((float(vecs[i] @ vecs[j]) for j in selected), default=0.0)
            val = lam * float(scores[i]) - (1.0 - lam) * div
            if val > best_val:
                best_val, best_i = val, i
        selected.append(best_i)
        remaining.remove(best_i)
    return selected


def retrieve(video_id: str, query: str, k: int) -> list[tuple[float, float]]:
    """Return up to k (timestamp, score) pairs, query-relevant and time-diverse."""
    model, rows = iter_visual_frames(video_id)
    if not rows or model != clip_embed.model_id():
        return []
    qv = clip_embed.embed_query(query)
    if qv is None:
        return []
    qa = np.asarray(qv, dtype=np.float32)
    times = np.array([t for t, _ in rows])
    mat = np.stack([v for _, v in rows])
    scores = mat @ qa

    pool = np.argsort(-scores)[: min(RETRIEVE_N, len(rows))]
    pool_vecs = mat[pool]
    pool_scores = scores[pool]
    chosen = _mmr(pool_scores, pool_vecs, MMR_LAMBDA, k)
    picks = [(float(times[pool[i]]), float(pool_scores[i])) for i in chosen]
    picks.sort(key=lambda ts: ts[0])  # present in chronological order
    return picks


# ---------- contact sheet packing ---------------------------------------


def _build_contact_sheet(video_id: str, items: list[tuple[float, Path]]) -> Path | None:
    """Tile labeled frames into one grid image. items = [(t, frame_path), ...]."""
    from videomemory.config import frame_dir

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    frames = [(t, p) for t, p in items if p and Path(p).exists()]
    if not frames:
        return None

    import math

    n = len(frames)
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    cell, label_h, pad = SHEET_CELL_PX, 26, 4
    cw, ch = cell + pad, cell + label_h + pad
    canvas = Image.new("RGB", (cols * cw + pad, rows * ch + pad), (20, 20, 20))
    draw = ImageDraw.Draw(canvas)

    for idx, (t, path) in enumerate(frames):
        r, c = divmod(idx, cols)
        x0, y0 = pad + c * cw, pad + r * ch
        try:
            im = Image.open(path).convert("RGB")
        except Exception:
            continue
        im.thumbnail((cell, cell), Image.LANCZOS)
        ox = x0 + (cell - im.width) // 2
        oy = y0 + label_h + (cell - im.height) // 2
        canvas.paste(im, (ox, oy))
        draw.text((x0 + 4, y0 + 6), f"{idx + 1} · {fmt_time(t)}", fill=(255, 255, 255))

    out = frame_dir(video_id) / f"sheet_{abs(hash(tuple(round(t, 2) for t, _ in frames))) & 0xFFFFFFFF:08x}.jpg"
    canvas.save(out, quality=85)
    return out


def _sheet_uri(video_id: str, path: Path) -> str:
    return f"videomemory://frames/{video_id}/{path.name}"


def _wants_ocr(question: str) -> bool:
    q = question.lower()
    return any(h in q for h in _OCR_HINTS)


# ---------- public entrypoint -------------------------------------------


async def analyze(url: str, question: str, *, k: int = DEFAULT_K, packing: str = "auto") -> VisualAnalysis:
    """Visually understand any video and return the query-relevant evidence.

    packing: "auto" (contact sheet, separate-frames for OCR) | "sheet" | "separate".
    """
    from videomemory.frames import _frame_uri, extract_frames, get_frames

    info = await build_index(url)
    vid, source, duration = info["video_id"], url, info["duration"]

    # Embedder unavailable → degrade to plain uniform frames so the tool still works.
    if info["model"] is None or info["indexed"] == 0:
        fr = await get_frames(url, count=min(k, SEPARATE_K))
        return VisualAnalysis(
            video_id=vid, source=source, question=question, duration=duration,
            indexed_frames=info["indexed"], candidates_scanned=info["candidates"],
            packing="separate",
            frames=[VisualFrame(timestamp_seconds=f.timestamp_seconds, timestamp_human=f.timestamp_human,
                                deep_link=f.deep_link, frame_uri=f.frame_uri, score=0.0) for f in fr],
            guidance="Visual index unavailable (install open-clip-torch for query-aware selection); "
                     "returned evenly-spaced frames instead.",
        )

    separate = packing == "separate" or (packing == "auto" and _wants_ocr(question))
    want = min(k, SEPARATE_K) if separate else k
    picks = retrieve(vid, question, want)
    if not picks:
        picks = [(duration * (i + 1) / (want + 1), 0.0) for i in range(want)]

    # Re-extract the chosen timestamps at display resolution (precise frames).
    extracted = await extract_frames(vid, source, [t for t, _ in picks])
    by_t = {round(t, 3): p for t, p in extracted}
    score_by_t = {round(t, 3): s for t, s in picks}

    frames: list[VisualFrame] = []
    sheet_items: list[tuple[float, Path]] = []
    for t, _ in picks:
        path = by_t.get(round(t, 3))
        if path is None:
            continue
        frames.append(VisualFrame(
            timestamp_seconds=t, timestamp_human=fmt_time(t),
            deep_link=deep_link(source, t), frame_uri=_frame_uri(vid, t),
            score=score_by_t.get(round(t, 3), 0.0),
        ))
        sheet_items.append((t, path))

    if separate:
        return VisualAnalysis(
            video_id=vid, source=source, question=question, duration=duration,
            indexed_frames=info["indexed"], candidates_scanned=info["candidates"],
            packing="separate", frames=frames,
            guidance="Fine-detail/OCR query: frames returned separately at full resolution. "
                     "Fetch each frame_uri and read it directly. Frames are in chronological order.",
        )

    sheet = _build_contact_sheet(vid, sheet_items)
    sheet_uri = _sheet_uri(vid, sheet) if sheet else None
    return VisualAnalysis(
        video_id=vid, source=source, question=question, duration=duration,
        indexed_frames=info["indexed"], candidates_scanned=info["candidates"],
        packing="contact_sheet" if sheet else "separate",
        sheet_uri=sheet_uri, frames=frames,
        guidance=(
            f"Fetch sheet_uri: a single {len(sheet_items)}-frame contact sheet. Cells are numbered "
            "left-to-right, top-to-bottom; each label is 'N · MM:SS' giving that frame's timestamp. "
            "Reason over the grid to answer the question, and cite frame timestamps / deep_links. "
            "If you need finer detail on one cell, fetch that frame's individual frame_uri."
        ) if sheet else "Contact sheet unavailable; frames returned separately.",
    )


__all__ = ["analyze", "build_index", "retrieve"]
