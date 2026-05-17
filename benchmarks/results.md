# Retrieval benchmark — tech_talk fixture

| query | videomemory P@1 | transcript-only P@1 | vm latency (ms) | baseline latency (ms) |
|---|---:|---:|---:|---:|
| When was OAuth discussed? | 1.00 | 1.00 | 62.3 | 13.7 |
| Find scenes mentioning Docker | 1.00 | 1.00 | 39.5 | 11.5 |
| Kubernetes Networking topic | 1.00 | 1.00 | 33.6 | 13.0 |

## Frame recall selectivity

- total keyframes: 3
- selective recall (`Docker`): 3 frames
- compression ratio: 100.00% (naive baseline returns all frames)
