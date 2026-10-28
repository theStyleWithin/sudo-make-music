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

## Mobile model plan (researched, not yet implemented)
Chosen target: **Stable Audio Open Small** (341M params, up to ~11s clips; Stability/Arm report <8s per clip on a
flagship Arm phone). Arm publishes a recipe to convert it to LiteRT (`.tflite`): the T5 conditioner is exported via ONNX,
the DiT and the autoencoder become `dit_model.tflite` and `autoencoder_model.tflite`, run with XNNPACK/KleidiAI on the CPU.
Naively quantizing the whole model badly hurts quality; Arm uses mixed FP16/INT8.
- Sources: Arm learning path <https://learn.arm.com/learning-paths/mobile-graphics-and-gaming/run-stable-audio-open-small-with-lite-rt/>,
  <https://stability.ai/news/stability-ai-and-arm-bring-on-device-generative-audio-to-smartphones>.
- **Licence:** Stability AI Community License (free for non-commercial and for commercial use under $1M revenue). Not
  public domain, and the weights are gated on Hugging Face (account + accepting the licence). Verify the current terms.
- Needed to finish: (1) the converted `.tflite` files (made on a PC with >=8GB RAM following Arm's steps), (2) a
  `ModelBackend` that runs conditioner -> sampler loop -> decoder through LiteRT (pyjnius to the Java/C++ LiteRT API on Android),
  with the exact tensor names/shapes taken from the converted models. Chunk/stitch then extends clips into longer songs.
- Not written yet on purpose: the tensor signatures can only be taken from real converted files, and guessing them would be untested code.
