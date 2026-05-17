"""Pre-pull all models so the first `videomemory ingest` doesn't pay download latency.

Idempotent. Skips already-cached models. Run inside the Docker builder stage and
also recommended as a manual step on a fresh checkout.
"""

from __future__ import annotations

import sys


def main() -> int:
    print("Pre-downloading VideoMemory models...")
    try:
        from sentence_transformers import SentenceTransformer

        print("  bge-small-en-v1.5 ...", flush=True)
        SentenceTransformer("BAAI/bge-small-en-v1.5", device="cpu")
    except Exception as exc:
        print(f"    [skip] {exc}")

    try:
        import open_clip

        print("  CLIP ViT-B-32 (openai) ...", flush=True)
        open_clip.create_model_and_transforms("ViT-B-32", pretrained="openai")
        open_clip.get_tokenizer("ViT-B-32")
    except Exception as exc:
        print(f"    [skip] {exc}")

    try:
        from faster_whisper import WhisperModel

        print("  faster-whisper small ...", flush=True)
        WhisperModel("small", device="cpu", compute_type="int8")
    except Exception as exc:
        print(f"    [skip] {exc}")

    try:
        from rapidocr_onnxruntime import RapidOCR

        print("  rapidocr-onnxruntime ...", flush=True)
        RapidOCR()
    except Exception as exc:
        print(f"    [skip] {exc}")

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
