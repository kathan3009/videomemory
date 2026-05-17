# Model defaults & swaps

## Default (light) profile

| Component | Default | Disk | RAM | Notes |
|---|---|---:|---:|---|
| Embeddings | `BAAI/bge-small-en-v1.5` | ~120 MB | ~250 MB | 384-dim |
| Vision tags | `open_clip ViT-B-32` (openai) | ~340 MB | ~700 MB | MPS-capable |
| OCR | `rapidocr-onnxruntime` | ~10 MB | ~150 MB | ARM-clean ONNX |
| Transcription | `faster-whisper small` | ~470 MB | ~700 MB | CTranslate2 int8 |
| Detection | `yolov8n.pt` (off by default) | ~6 MB | ~200 MB | enable via config |
| Diarization | `pyannote.audio` (off) | – | – | requires HF token |

Total disk for the default stack: ~1 GB.

## Heavier swap-ins (opt-in)

Edit your `PipelineConfig` (yaml file passed via `--config`):

```yaml
whisper_model: large-v3        # higher transcription quality, ~3 GB
clip_model: ViT-L-14
clip_pretrained: openai
embedding_model: BAAI/bge-large-en-v1.5
use_yolo: true
use_diarization: true          # requires VIDEOMEMORY_HF_TOKEN
```

## Captioning

Default: templated caption built from `objects + OCR + scene tag`. No VLM call.

Optional: connect a local Ollama VLM (e.g. llava-7b). Add to your config:

```yaml
# Future enhancement: caption_provider: ollama, vlm_model: llava
```

The interface lives in `videomemory/vision/caption.py` — a plugin slot exists, the default impl is the templated one to keep the light profile offline.

## Devices on Apple Silicon

The model wrappers auto-detect MPS via `config.select_device("auto")`. Whisper does not currently support MPS (we fall back to CPU/CTranslate2 int8, which is fast on M-series). CLIP and bge run on MPS. `device: cpu` in your config forces everything to CPU.
