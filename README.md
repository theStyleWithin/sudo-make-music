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
sudo-make-music            # opens the desktop window
```

Try it with no GPU/model first: pick **Mock synth** as the backend (verifies chunking, export, history).
First ACE-Step generation downloads weights (~7GB) into `~/.local/share/sudo-make-music/models/ace-step`; after that, offline.
MP3 export uses `ffmpeg` if on PATH, else `lameenc`.

## Install options

It is a native desktop app (Kivy), not a web app. The same code is built for Android.

| Platform | How | Status |
|---|---|---|
| Linux AppImage | download from Releases, `chmod +x`, run | built by CI; not yet run by the author |
| Windows portable | `sudo-make-music-portable.exe` (data kept next to the exe) | built by CI; untested |
| Android | `sudo-make-music-android.apk` - **standalone, on-device**. See `docs/ANDROID.md`: the UI port is done, but the phone-capable AI model is not yet. | built by CI; untested |
| Arch / CachyOS | AUR `sudo-make-music-git` | package in `packaging/aur`, handed off |
| Flathub | `io.github.theStyleWithin.SudoMakeMusic` | manifest in `packaging/flatpak`, handed off |

Desktop packages ship only the light app. On first run use **Settings > Install PyTorch + ACE-Step** (or `sudo-make-music --install-backend cu126`) once (several GB); models download on first generation; then it's offline. Packagers: see `docs/packaging/HANDOFF.md`.

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

`pip install -e '.[dev]' && pytest`; headless UI check: `xvfb-run -a python tests/ui_smoke.py /tmp/shots` (saves screenshots).

Public domain (Unlicense).
