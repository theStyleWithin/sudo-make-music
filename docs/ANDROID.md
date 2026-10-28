# Android

The Android app is the **same app** as the desktop one: one Python codebase (Kivy UI + the same engine,
memory modes, chunk/stitch pipeline, history), packaged with python-for-android via `buildozer.spec`.
It runs fully on-device; there is no server.

## Status
- Done: UI, engine, history, settings, WAV export, build config + CI job. Only the Mock synth backend exists on Android today.
- **Not done: a phone-capable AI model backend.** ACE-Step (billions of parameters, needs CUDA/PyTorch) cannot run on a phone.
  PyTorch has no python-for-android recipe either.
- Untested: nobody has built or run the APK yet. Expect first-build fixes (CI job `android`).
- MP3 export is desktop-only for now (no ffmpeg/lameenc on Android); WAV works.
- Saving to `Music/sudo-make-music` uses legacy storage permission; Android 11+ may need a MediaStore-based save.

## Mobile model: Stable Audio Open Small (base, swappable)
The Android build defaults to the `stableaudio_litert` backend (LiteRT `.tflite` models, numpy sampler, pyjnius runner);
everything is a normal `ModelBackend`, so another small model can replace it. See `docs/STABLE_AUDIO_LITERT.md` for the model
folder contract, what is tested and the three remaining blockers (converted models, sentencepiece on Android, on-device runner test).
Expect short (<= 11s) instrumental clips and lower quality than ACE-Step on desktop; long songs are stitched from clips.
Licence: Stability AI Community License (gated weights; not public domain).
