# Architecture

```
web/index.html ──HTTP/JSON──> server.py ──> Engine (engine.py)
                                              │  one worker thread, one job at a time
                                              ├─ SettingsStore (settings.py)  mode + overrides
                                              ├─ memory.py  mode presets -> GenParams
                                              ├─ History (sqlite)
                                              ├─ audio.py  plan_segments / Stitcher / WavWriter / export_mp3
                                              └─ ModelBackend (backends/base.py)
                                                    ├─ MockBackend
                                                    └─ ACEStepBackend
```

## Backend choice: ACE-Step first
Diffusion model with lyric conditioning, native `cpu_offload` and `overlapped_decode`, ~4 min per call, permissive
licence, community reports of running in ~6GB with offload. Alternatives (e.g. autoregressive models like MusicGen)
need KV cache that grows with length, which is worse for long songs on small VRAM. New backends plug into the same interface.

## Adapter contract
`load(params)` / `generate_segment(req, params, progress, cancelled)` / `unload()`. The engine owns chunk planning,
stitching, cancellation, cache clearing, and idle unload; backends only turn (prompt, lyrics, duration, seed) into audio.

## Job flow
submit → clamp duration to `max_duration` → plan equal-length segments (≤ chunk, crossfade overlap) → load model →
for each segment: generate, crossfade-stitch into on-disk WAV, free memory → optional MP3 → history row.
Failures (incl. CUDA OOM, with a hint to use Safe mode) and cancels delete partial output.
