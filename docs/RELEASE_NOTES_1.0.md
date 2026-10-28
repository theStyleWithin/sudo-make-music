# sudo make music 1.0.0

Offline AI music generation for mid-range PCs (built for ~6GB VRAM / 16GB RAM). No cloud, no content filter,
every model is a local, swappable folder.

## Downloads
| File | Platform | Notes |
|---|---|---|
| `sudo-make-music-x86_64.AppImage` | Linux x86_64 | `chmod +x` and run. Needs FUSE (or run with `--appimage-extract-and-run`). |
| `sudo-make-music-portable.exe` | Windows 10/11 | Single file; data is kept in a `sudo-make-music-data` folder next to it. Unsigned: SmartScreen will warn. Built with a bootloader compiled in CI where possible. |
| `sudo-make-music-windows-folder.zip` | Windows 10/11 | Same app unpacked as a folder (unzip, run `sudo-make-music.exe`). **Try this one if your antivirus flags the single exe**: it does not self-extract, which scanners dislike. |
| `sudo-make-music-android.apk` | Android (arm64) | **Debug-signed** build, install from outside the store. UI only for now: see limits. |
| `SHA256SUMS.txt` | | Checksums for the files above. |

### Windows: community-tested, please report
The maintainer does not use Windows and does **not** test the Windows build. It is offered as a courtesy so Windows users are not left out.
CI builds it and runs a built-in self-check (`--selfcheck`) on the finished exe, but nobody has used it on a real Windows PC. If you try it,
please open an issue with the "Windows test report" form: your Windows version, whether it started, your antivirus/VirusTotal result, and the
output of `sudo-make-music-portable.exe --selfcheck selfcheck.txt` (the report file is written next to the exe). Windows help from the community is very welcome.

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
