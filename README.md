# sudo-make-music

Offline AI music generation for mid-range PCs. Target: **RTX 2060 6GB + 16GB RAM**, Linux first (Arch/CachyOS), Windows second.
No cloud APIs, no content filter, models swappable. After the one-time model download everything runs locally.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
# 1. torch for your CUDA (https://pytorch.org/get-started/locally/), e.g.:
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
# 2. the app + default backend (+ optional int8 quantization, mp3 fallback)
pip install -e '.[acestep,quant,mp3]'
sudo-make-music            # -> http://127.0.0.1:7860
```

Try it with no GPU/model first: pick **Mock synth** as the backend in the UI (verifies chunking, export, history).
First ACE-Step generation downloads weights (~7GB) into `~/.local/share/sudo-make-music/models/ace-step`; after that, offline.
MP3 export uses `ffmpeg` if on PATH, else `lameenc`.

## Install options

| Platform | How | Status |
|---|---|---|
| Linux AppImage | download `sudo-make-music-x86_64.AppImage` from Releases, `chmod +x`, run | built by CI; not yet run by the author |
| Windows portable | `sudo-make-music-portable.exe` (data kept next to the exe) | built by CI; untested |
| Android | `sudo-make-music-android.apk` - **remote client** for the PC app on your Wi-Fi (`sudo-make-music --host 0.0.0.0`, then enter the printed URL). The model can't run on a phone. | built by CI; untested |
| Arch / CachyOS | AUR `sudo-make-music-git` | package ready in `packaging/aur`, handed off |
| Flathub | `io.github.theStyleWithin.SudoMakeMusic` | manifest ready in `packaging/flatpak`, handed off |

Packages ship only the light app. On first run use **AI backend install** in the UI (or `sudo-make-music --install-backend cu126`) to download PyTorch + ACE-Step once (several GB); models download on first generation; then it's offline. Packagers: see `docs/packaging/HANDOFF.md`.

## How long songs fit in 6GB

| Technique | Where |
|---|---|
| Auto VRAM detection → Safe/Balanced/Quality default | `hardware.py`, `memory.py` |
| Segment-and-stitch: song is split into ≤`chunk` s segments, equal-power crossfaded | `audio.plan_segments`, `audio.Stitcher` |
| Stitched audio streams straight to a WAV on disk (only the crossfade tail is in RAM) | `audio.WavWriter` |
| CPU offload + overlapped VAE decode + (best-effort) INT8 weights | `backends/acestep.py` |
| Batch size fixed at 1 | `memory.GenParams` |
| `torch.cuda.empty_cache()` after every segment and job | `engine.py` |
| Model unloaded after N idle seconds (default 120) | `engine.py` |

| Mode | chunk | max song | offload | int8 |
|---|---|---|---|---|
| Safe (default <8GB VRAM) | 60s | 10 min | on | on |
| Balanced (8–12GB) | 120s | 8 min | on | off |
| Quality (≥12GB) | 240s | 5 min | off | off |

Every value (max duration, chunk, crossfade, offload, quantization, seed, steps) can be overridden in Settings.

## Known limitations (be aware)

- **Untested on real hardware.** The pipeline, stitching, UI, export, history and cancellation are covered by tests using the mock backend. The ACE-Step adapter is written against its public `ACEStepPipeline` API but was developed without a GPU; expect to tune it on your 2060 (bf16 is emulated on Turing — if it is slow or errors, report back; fp16 may be needed).
- **Chunked songs are independent generations** with the same prompt and consecutive seeds, joined by a crossfade. Long songs won't have a coherent arrangement/structure across chunks, and lyrics are repeated per chunk. Using ACE-Step's repaint/extend to condition each chunk on the previous one is the main planned improvement.
- INT8 quantization uses `torchao` on the transformer and falls back (with a log message) if it can't.
- Cancel takes effect between segments; a diffusion call in progress can't be interrupted.

## Adding a backend

Subclass `ModelBackend` (`backends/base.py`): implement `load`, `generate_segment`, `unload`, set `id/name/max_segment_seconds`, decorate with `@register`, import it in `backends/__init__.py`. It appears in the UI model selector automatically. See `backends/mock.py` for a minimal one. See `docs/ARCHITECTURE.md`.

## Tests

`pip install -e '.[dev]' && pytest`

Public domain (Unlicense).
