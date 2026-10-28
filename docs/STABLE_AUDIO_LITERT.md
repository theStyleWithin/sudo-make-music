# Stable Audio Open Small - model folders

Stable Audio Open Small (341M params) is the small-model base. It is **not** a song model: it makes <= ~11s stereo
clips (loops, instrumental ideas, sound effects), takes **no lyrics**, and long songs are stitched from independent clips.
Licence: Stability AI Community License (not public domain: read it before commercial use).
Everything below is swappable: another small model = another backend (`backends/base.py`).

## A. PyTorch backend (`stableaudio`, desktop)
1. Once, online, with a Hugging Face account that accepted the model licence:
   `HF_TOKEN=hf_xxx python tools/fetch_stable_audio_small.py ./sao` (downloads the weights + the T5 text encoder).
2. Offline from then on: Settings > Models > *as music model* > Import folder > `./sao`, pick the backend
   "Stable Audio Open Small (PyTorch)". Needs `pip install stable-audio-tools`.
3. Runs 8 pingpong steps in fp16 on GPU (about 1.5GB VRAM) or on CPU; the *Steps* setting does not apply.

## B. LiteRT backend (`stableaudio_litert`, phones / no PyTorch)
Folder contents (you must produce the `.tflite` files, e.g. following Arm's LiteRT guide for this model;
the app cannot convert them):

    smm-litert.json         descriptor (below)
    spiece.model            T5 sentencepiece tokenizer
    conditioners.tflite     text (+ seconds_total) -> cross-attention / global conditioning
    dit_model.tflite        denoiser: (latent, t, conditioning) -> v
    autoencoder_model.tflite  latent -> stereo audio

`smm-litert.json` maps *roles* to the real tensor names inside your files (print them with
`python tools/inspect_tflite.py *.tflite`). Names may carry the usual `serving_default_...:0` decoration.

```json
{
  "sample_rate": 44100, "sample_size": 524288, "latent_channels": 64, "downsample": 2048,
  "steps": 8, "max_tokens": 64, "tokenizer": "spiece.model",
  "conditioner": {"file": "conditioners.tflite",
    "inputs":  {"ids": "input_ids", "mask": "attention_mask", "seconds": "seconds_total"},
    "outputs": {"cross": "cross_attn_cond", "cross_mask": "cross_attn_mask", "global": "global_cond"}},
  "dit": {"file": "dit_model.tflite",
    "inputs":  {"x": "x", "t": "t", "cross": "cross_attn_cond", "cross_mask": "cross_attn_mask", "global": "global_cond"},
    "outputs": {"v": "output"}},
  "autoencoder": {"file": "autoencoder_model.tflite",
    "inputs": {"latent": "latent"}, "outputs": {"audio": "audio"}}
}
```
Optional: `"t_schedule": [1.0, ..., 0.0]` to use an exact timestep list instead of `linspace(1, 0, steps+1)`
(use it if the original model config applies a distribution shift).

The sampler is Stability's `sample_flow_pingpong` in numpy:
`denoised = x - t_i * v(x, t_i); x = (1 - t_{i+1}) * denoised + t_{i+1} * fresh_noise`.

## What is verified, what is not
- Verified by tests (with fake runners): sampler maths vs. the reference formula, step schedule, conditioning inputs,
  seeding, cancel, descriptor/tensor-name errors, chunking into long songs.
- **Not verified:** the real PyTorch weights, the real `.tflite` tensor layouts (I could not read Arm's reference app: its host
  was outside this session's allowed network), the Android runner (`AndroidLiteRTRunner`, pyjnius -> `org.tensorflow.lite`).
- **Android blockers still open:** (1) converted `.tflite` files, (2) `sentencepiece` has no python-for-android recipe yet
  (prompt tokenization), (3) on-device test of the runner. Until then the Android app only runs the mock synth.
