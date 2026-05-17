"""Pre-pull whisper + bge so the first request on a fresh image is fast.

Idempotent. Skips models already cached.
"""

from __future__ import annotations

import sys


def main() -> int:
    print("pre-pulling videomemory models...")
    try:
        from sentence_transformers import SentenceTransformer

        print("  bge-small ...", flush=True)
        SentenceTransformer("BAAI/bge-small-en-v1.5", device="cpu")
    except Exception as exc:
        print(f"  skip bge: {exc}")
    try:
        from faster_whisper import WhisperModel

        print("  faster-whisper small ...", flush=True)
        WhisperModel("small", device="cpu", compute_type="int8")
    except Exception as exc:
        print(f"  skip whisper: {exc}")
    print("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
