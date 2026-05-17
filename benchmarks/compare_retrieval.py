"""Benchmark VideoMemory retrieval against two baselines:

1. **transcript-only**: cosine similarity between query and concatenated
   transcript per chunk (no OCR, no visual signal, no temporal anchoring).
2. **naive-frame**: returns *all* keyframes for any frame query.

Metrics: precision@5 over a small hand-labelled query set per fixture, plus
retrieval latency. Output: `benchmarks/results.md`.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from tests.fixtures.make_videos import build_all
from videomemory.embeddings.bge import cosine, embed_text, embed_texts
from videomemory.pipeline.runner import run_ingest
from videomemory.retrieval.frame_recall import recall_frames
from videomemory.retrieval.router import retrieve_chunks
from videomemory.retrieval.store_helpers import load_chunks, load_keyframe_index

QUERIES_TECH_TALK = [
    {"q": "When was OAuth discussed?", "expects_chunk_summary_contains": "oauth"},
    {"q": "Find scenes mentioning Docker", "expects_chunk_summary_contains": "docker"},
    {"q": "Kubernetes Networking topic", "expects_chunk_summary_contains": "kubernetes"},
]


def transcript_only_retrieval(video_id: str, data_dir: Path, query: str, top_k: int = 3):
    chunks = load_chunks(video_id, data_dir)
    qv = embed_text(query)
    docs = [c.transcript_excerpt or c.summary for c in chunks]
    scores = [cosine(qv, dv) for dv in embed_texts(docs)]
    ranked = sorted(zip(chunks, scores, strict=True), key=lambda x: -x[1])
    return [c for c, _ in ranked[:top_k]]


def naive_frame_retrieval(video_id: str, data_dir: Path, _query: str):
    return load_keyframe_index(video_id, data_dir)


def precision_at_k(results, expected_substring: str, k: int = 5) -> float:
    hits = 0
    for r in results[:k]:
        summ = (getattr(r, "summary", "") or "").lower()
        if expected_substring in summ:
            hits += 1
    return hits / max(min(k, len(results)), 1)


async def main() -> None:
    data_dir = Path("./bench_data")
    data_dir.mkdir(exist_ok=True)
    fixtures = build_all()
    job = await run_ingest(str(fixtures["tech_talk"]), data_dir=data_dir)

    lines: list[str] = []
    lines.append("# Retrieval benchmark — tech_talk fixture\n")
    lines.append("| query | videomemory P@1 | transcript-only P@1 | vm latency (ms) | baseline latency (ms) |")
    lines.append("|---|---:|---:|---:|---:|")

    for qq in QUERIES_TECH_TALK:
        q = qq["q"]
        expect = qq["expects_chunk_summary_contains"]

        t0 = time.perf_counter()
        vm_results = retrieve_chunks(job.video_id, q, data_dir, top_k=5)
        vm_ms = (time.perf_counter() - t0) * 1000
        vm_p1 = precision_at_k(vm_results, expect, k=1)

        t0 = time.perf_counter()
        base_results = transcript_only_retrieval(job.video_id, data_dir, q, top_k=5)
        base_ms = (time.perf_counter() - t0) * 1000
        base_p1 = precision_at_k(base_results, expect, k=1)

        lines.append(f"| {q} | {vm_p1:.2f} | {base_p1:.2f} | {vm_ms:.1f} | {base_ms:.1f} |")

    # Frame recall selectivity
    lines.append("\n## Frame recall selectivity\n")
    all_frames = naive_frame_retrieval(job.video_id, data_dir, "")
    sel = await recall_frames(job.video_id, query="Docker", limit=8, data_dir=data_dir)
    lines.append(f"- total keyframes: {len(all_frames)}")
    lines.append(f"- selective recall (`Docker`): {len(sel)} frames")
    lines.append(
        f"- compression ratio: {len(sel) / max(len(all_frames), 1):.2%} "
        "(naive baseline returns all frames)"
    )

    Path(__file__).parent.joinpath("results.md").write_text("\n".join(lines) + "\n")
    print("wrote benchmarks/results.md")


if __name__ == "__main__":
    asyncio.run(main())
