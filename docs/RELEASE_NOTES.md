# sudo make music 1.0.3

Offline AI music generation for mid-range PCs (built for ~6GB VRAM / 16GB RAM). No cloud, no content filter,
every model is a local, swappable folder.

## What is new in 1.0.3
- **Sample cards:** the app now starts with eight ready-made song cards (lo-fi, house, synthwave, ambient, rock, jazz, trance, chiptune) in Library > Cards. Play, remix or extend them as a reference for your own songs. They are added once and you can delete them.

## What is new in 1.0.2
- **Procedural music (BETA):** a no-AI, no-download engine that builds songs from rules and sings your lyrics. Instant, tiny, and the default on Android.
- **Song cards:** every procedural song is kept as a card in Library > Cards, showing its genre, key, tempo, length, sections and first lyric. Play it again, remix it (new style, key, tempo, or new melody/harmony/drums) or extend it with a new tune. Cards can be exported and imported as small files; imported cards are checked and are data only.

## What is new since 1.0.0
- **Windows fix:** the 1.0.0 Windows exe could not open its window (Kivy crashed at startup in a windowed exe). Fixed, and every Windows build now has to pass a built-in self-check in CI before it is published.
- **New Models tab:** the app reads your PC (GPU, VRAM, RAM), lists models with a "runs well / fits with limits / CPU only / too big" note plus **Best for your PC** and **Lightweight** tags, and downloads them in one click (resumable, checksum-verified, no need to navigate Hugging Face). The list can be refreshed online without a new release.
- **Built-in safety checks:** pickle-style weights are analysed without running them, safetensors/GGUF are validated, executables/symlinks/escaping archives are blocked, and your computer's antivirus (Windows Defender / ClamAV) runs on new downloads. A **VirusTotal** button opens any model's page by SHA-256; files are never uploaded.
- **Windows folder build** (`sudo-make-music-windows-folder.zip`): unzipped, no self-extracting exe, which antivirus tools flag less often.
- **Android APK** now builds (debug-signed, UI only, see limits).
- Release files carry GitHub build-provenance attestations; the Windows launcher is compiled in CI where possible.

## Downloads
| File | Platform | Notes |
|---|---|---|
| `sudo-make-music-x86_64.AppImage` | Linux x86_64 | `chmod +x` and run. Needs FUSE (or run with `--appimage-extract-and-run`). |
| `sudo-make-music-portable.exe` | Windows 10/11 | Single file; data is kept in a `sudo-make-music-data` folder next to it. **Unsigned**: SmartScreen will warn. |
| `sudo-make-music-windows-folder.zip` | Windows 10/11 | Same app unpacked as a folder (unzip, run `sudo-make-music.exe`). **Try this one if your antivirus flags the single exe.** |
| `sudo-make-music-android.apk` | Android (arm64) | **Debug-signed** build, install from outside the store. UI only for now: see limits. |
| `SHA256SUMS.txt` | | Checksums for the files above. |

Verify a download: `gh attestation verify <file> --repo theStyleWithin/sudo-make-music`. There is no paid code-signing certificate (see `docs/SIGNING.md`).

### Windows: community-tested, please report
The maintainer does not use Windows and does **not** test the Windows build. It is offered as a courtesy so Windows users are not left out.
CI builds it and runs a built-in self-check (`--selfcheck`) on the finished exe, but nobody has used it on a real Windows PC. If you try it,
please open an issue with the "Windows test report" form: your Windows version, whether it started, your antivirus/VirusTotal result, and the
output of `sudo-make-music-portable.exe --selfcheck selfcheck.txt` (the report file is written next to the exe).

Arch/CachyOS (AUR) and Flathub packages are prepared in `packaging/` with handoff instructions in `docs/packaging/`.
Not every file above exists on every release: whatever failed to build in CI is simply missing from the list.

## First run
The installers contain only the light app. Open the **Models** tab and pick a model for your PC, then use the **Install ...** buttons in Settings for the engine libraries
(several GB, needs internet **once**), or import model folders you already have (works with no network). After the models are on disk,
turn on *Offline mode* and nothing touches the network.

## Honest limits - please read
- **Never run against real models.** Everything was tested with mock engines and a fake model server. The ACE-Step, Stable Audio, Kokoro, Chatterbox, Demucs and OpenVoice adapters
  follow each library's public API but have not been executed with real weights, and the Models tab list entries were never downloaded for real; expect fixes on first real use.
- The Windows exe and the Android APK have never been used on real devices. The Linux AppImage's contents were run headless.
- **Android has no working AI model yet.** It needs converted LiteRT model files, a `sentencepiece` build for Android, and an on-device test (`docs/STABLE_AUDIO_LITERT.md`). Until then the Android app runs only the placeholder synth.
- Songs longer than one chunk are independent generations stitched together (the "continue from previous chunk" option is experimental).
- Re-voice and "use a voice in a song" are best-effort similarity, not exact singer reproduction.
- Stable Audio Open Small makes <= 11s instrumental clips, no lyrics; its weights are under the Stability AI Community License.
- Only clone voices you own or have permission to use.
