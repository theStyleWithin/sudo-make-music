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

## What the mobile model needs (next step)
A small model with a mobile runtime, wrapped as a `ModelBackend` (see `backends/base.py`):
- Candidate: Stable Audio Open Small (~341M params, short ~11s clips) via LiteRT/ONNX - note its license
  (Stability Community License) is not fully open and should be checked against the "no restrictions" goal.
- Needs a native runtime reachable from Python on Android (pyjnius to LiteRT, or a p4a recipe for onnxruntime).
- Expect short clips and much lower quality than ACE-Step; the chunk/stitch pipeline would still extend length.
