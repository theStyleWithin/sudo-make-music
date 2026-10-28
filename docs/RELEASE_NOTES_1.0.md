# sudo make music 1.0.0

Offline AI music generation for mid-range PCs (built for ~6GB VRAM / 16GB RAM). No cloud, no content filter,
every model is a local, swappable folder.

## Downloads
| File | Platform | Notes |
|---|---|---|
| `sudo-make-music-x86_64.AppImage` | Linux x86_64 | `chmod +x` and run. Needs FUSE (or run with `--appimage-extract-and-run`). |
| `sudo-make-music-portable.exe` | Windows 10/11 | Single file; data is kept in a `sudo-make-music-data` folder next to it. Unsigned: SmartScreen will warn. |
| `*.apk` | Android (arm64) | **Debug-signed** build, install from outside the store. UI only for now: see limits. |
| `SHA256SUMS.txt` | | Checksums for the files above. |

Arch/CachyOS (AUR) and Flathub packages are prepared in `packaging/` with handoff instructions in `docs/packaging/`.
Not every file above exists on every release: whatever failed to build in CI is simply missing from the list.

## First run
The installers contain only the light app. In **Settings** use *Install PyTorch + ACE-Step* (several GB, needs internet **once**),
or import model folders you already have (Settings > Models; works with no network). After the models are on disk,
turn on *Offline mode* and nothing touches the network.

## What is in 1.0
- Songs: lyrics + style prompt, lengths up to 30 min on a 6GB card (chunked, crossfaded, streamed to disk), Safe/Balanced/Quality memory modes, manual overrides.
- GPU/VRAM handling: auto-detect, CPU/system-RAM fallback with a hardware-warning popup and a manual resource selector.
- Local, swappable models with a model manager and offline mode. Backends: ACE-Step, Stable Audio Open Small (PyTorch and LiteRT).
- Voice library (separate from songs), Talk mode (text to speech), voice cloning, and Re-voice (change the singer of a song).
- History, WAV/MP3 export.

## Honest limits - please read
- **Never run against real models.** Everything was tested with mock engines. The ACE-Step, Stable Audio, Kokoro, Chatterbox, Demucs and OpenVoice adapters
  follow each library's public API but have not been executed with real weights; expect fixes on first real use.
- The Windows exe and the Android APK have never been run by the author. The Linux AppImage's contents were run headless; the final packaging was done by CI.
- **Android has no working AI model yet.** It needs converted LiteRT model files, a `sentencepiece` build for Android, and an on-device test (`docs/STABLE_AUDIO_LITERT.md`). Until then the Android app runs only the placeholder synth.
- Songs longer than one chunk are independent generations stitched together (the "continue from previous chunk" option is experimental).
- Re-voice and "use a voice in a song" are best-effort similarity, not exact singer reproduction.
- Stable Audio Open Small makes <= 11s instrumental clips, no lyrics; its weights are under the Stability AI Community License.
- Only clone voices you own or have permission to use.
