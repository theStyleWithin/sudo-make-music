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

## Models at a glance (all local, all swappable)

| Backend | What it is | Good for | Needs |
|---|---|---|---|
| `acestep` (default on desktop) | 3.5B diffusion model, lyrics, up to 4 min/clip | real songs with vocals | ~6GB VRAM (or CPU, slow) |
| `stableaudio` | Stable Audio Open Small, PyTorch | fast short instrumental clips/loops, very low VRAM, no lyrics | `stable-audio-tools` |
| `stableaudio_litert` (default on Android) | same model as LiteRT `.tflite` | phones / no PyTorch | converted model files, see `docs/STABLE_AUDIO_LITERT.md` |
| `mock` | sine synth | testing | nothing |

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
| Safe (default <8GB VRAM) | 60s | 30 min | on | on |
| Balanced (8–12GB) | 120s | 20 min | on | off |
| Quality (≥12GB) | 240s | 15 min | off | off |

Every value (max duration, chunk, crossfade, offload, quantization, seed, steps) can be overridden in Settings.

## Voices: voice library, talk mode, cloning

- **Create > Talk:** type text and have a voice speak it (not sing). Long text is split into sentences, synthesized one at a time and streamed to disk.
- **Voice library (Voices tab)** is separate from your songs. A voice is a name, a short reference clip, tags and (for song voices) the seed it came from.
  - After generating a song press **Save voice**: pick the part of the song with the singing (start + length, up to 30s) and optionally describe it ("female vocal, warm alto").
  - **Clone a voice** from any audio file (5-30s of ONE speaker, clean recording works best; WAV works anywhere, other formats need ffmpeg). Everything stays on your machine.
  - **Add preset voice** saves a built-in voice of the speech backend (e.g. Kokoro's `af_heart`).
  - Pick a saved voice in the **Voice** box on Create (or press *Use in song* / *Use in talk*). Deleting a song never deletes its saved voice.
- **Songs with a saved voice:** the voice's seed is reused (so it is no longer random unless you pin another seed in Settings), its description is added to the prompt, and its reference clip is fed to the music model as context for every chunk. Music models have no real "voice ID", so this is *best-effort similarity*, not a guaranteed identical singer (and only for backends with context support, i.e. ACE-Step's experimental extend mode). Exact singing-voice cloning would need a separate voice-conversion model, which is not included.
- **Cloning engines (swappable, offline after one download):** `chatterbox` (MIT, clones from a reference clip, a few GB VRAM, falls back to CPU) and `kokoro` (tiny, preset voices only, no cloning). Install with Settings > *Install voice libraries* or `sudo-make-music --install-backend cu126 --with-speech`. Add other engines as `SpeechBackend`s (`backends/speech.py`). Only one model sits in memory at a time (the music model is unloaded before the voice model loads).
- **Re-voice (change the singer of an existing song):** needs two *separate* local models, because a music model cannot sing in a given voice. The app separates the vocals (Demucs), converts them to your saved voice (OpenVoice v2) and mixes them back with the original backing, 45s at a time so long songs stay in memory limits. Press **Re-voice** on a finished song (Create or Library) after picking a saved voice that has a reference clip. The result is a new entry; the original song is kept.
- **Cloning models are separate, offline and swappable.** The Voices tab lists the model each feature needs and whether it is on disk: *Music model*, *Talk voice model*, *Singing voice-cloning model*, *Vocal-separation model*. If one is missing it says so, and (in offline mode) the app refuses instead of downloading. Get a model once, on any machine, then use **Settings > Models > Import folder** (USB stick, other drive) with the matching *as ... model* choice; no network needed afterwards. Swap any role to another engine in Settings (they are plain `SpeechBackend` / `ConverterBackend` / `SeparatorBackend` classes). Libraries: Settings > *Install ...* buttons, or `sudo-make-music --install-backend cu126 --with-speech --with-cloning`.
- **Use voice cloning responsibly:** only clone voices you own or have permission to use.
- A voice saved from a *song* is a poor reference for talk mode (music bleeds in); clone talk voices from a clean recording.
- **Not verified:** the Kokoro, Chatterbox, Demucs and OpenVoice adapters were written against their public APIs but never run (no model downloads possible where this was built). The library, talk and re-voice pipelines, model status/offline checks, UI and the mock engines are tested. OpenVoice's expected folder layout is `converter/config.json` + `converter/checkpoint.pth`.

## Choosing the resource (GPU vs CPU + system RAM)

- **You choose:** the Create screen has a *Resource* selector (Auto / GPU / CPU + system RAM); Settings has the same plus the warning switch below. Restart the app after switching if the GPU was already used this session (PyTorch limitation with ACE-Step).
- **Auto:** uses the GPU if it has at least 2GB VRAM, otherwise CPU + system RAM (small 30s chunks, int8 weights; works, but slow).
- **Hardware warning popup:** when the app needs a different resource than you chose, it pauses and asks, with a button per option:
  - no GPU / too little VRAM at start: *Continue on CPU + system RAM* / *Try the GPU anyway* / *Cancel*;
  - GPU runs out of memory mid-song: *Keep GPU, offload to RAM + int8* / *Use CPU + system RAM* / *Cancel*. The song resumes at the chunk that failed. If the backend can't switch GPU to CPU live (ACE-Step), the button saves "CPU" as the setting and asks you to restart.
  - No popup if you explicitly picked CPU yourself. Turn the popup off in Settings (*Hardware warning popup*) to let the app step down automatically instead.

## Local, offline, swappable models

- Every model is a plain folder in `<data>/models/<name>/` (Linux: `~/.local/share/sudo-make-music/models`, Windows portable: next to the exe) with a small `smm-model.json` (`{"backend": "acestep", "name": "..."}`).
- **Settings > Models:** import a folder from anywhere (USB stick, another drive), pick which one a backend uses, delete it. Swap ACE-Step checkpoints or fine-tunes without touching code; new model *families* are added as backends (`backends/base.py`).
- **Offline mode** (Settings): sets `HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE` and refuses to start a job without a local model, so nothing can touch the network.
- **Longer songs:** the length limit is time, not memory (audio streams to disk). Safe mode allows 30 min on 6GB. For better coherence across chunks, turn on *Continue each chunk from the previous one*: the last ~10s of the previous chunk is passed as context (ACE-Step "extend" task; falls back to independent chunks if it fails). Experimental and untested on real hardware.

## Known limitations (be aware)

- **Untested on real hardware.** The pipeline, stitching, UI, export, history and cancellation are covered by tests using the mock backend. The ACE-Step adapter is written against its public `ACEStepPipeline` API but was developed without a GPU; expect to tune it on your 2060 (bf16 is emulated on Turing — if it is slow or errors, report back; fp16 may be needed).
- **Chunked songs are independent generations by default** (same prompt, consecutive seeds, crossfaded), so long songs lack a coherent arrangement and lyrics repeat per chunk. The experimental continuity switch above is meant to improve this; it is unverified.
- INT8 quantization uses `torchao` on the transformer and falls back (with a log message) if it can't.
- Cancel takes effect between segments; a diffusion call in progress can't be interrupted.

## Adding a backend

Subclass `ModelBackend` (`backends/base.py`): implement `load`, `generate_segment`, `unload`, set `id/name/max_segment_seconds`, decorate with `@register`, import it in `backends/__init__.py`. It appears in the UI model selector automatically. See `backends/mock.py` for a minimal one. See `docs/ARCHITECTURE.md`.

## Tests

`pip install -e '.[dev]' && pytest`; headless UI check: `xvfb-run -a python tests/ui_smoke.py /tmp/shots` (saves screenshots).

Public domain (Unlicense).
