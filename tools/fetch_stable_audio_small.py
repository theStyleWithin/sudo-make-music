#!/usr/bin/env python3
"""Download Stable Audio Open Small ONCE (needs internet + a Hugging Face account that accepted the model licence),
into a plain folder you can then import offline: Settings > Models > Import folder (as music model).

  HF_TOKEN=hf_xxx python tools/fetch_stable_audio_small.py ./stable-audio-open-small

Result: model_config.json, model.safetensors, t5-base/ (text encoder, so no hub access is needed later), smm-model.json.
Not run in CI (no network there): report problems.
"""
import json
import os
import sys
from pathlib import Path

from huggingface_hub import snapshot_download

out = Path(sys.argv[1] if len(sys.argv) > 1 else "stable-audio-open-small").resolve()
tok = os.environ.get("HF_TOKEN")
out.mkdir(parents=True, exist_ok=True)
snapshot_download("stabilityai/stable-audio-open-small", local_dir=str(out), token=tok,
                  allow_patterns=["model_config.json", "model.safetensors", "model.ckpt", "README.md", "LICENSE*"])
snapshot_download("google-t5/t5-base", local_dir=str(out / "t5-base"), token=tok,
                  allow_patterns=["*.json", "*.model", "model.safetensors"])
(out / "smm-model.json").write_text(json.dumps({"backend": "stableaudio", "name": "Stable Audio Open Small"}))
print(f"done: {out}\nNow in the app: Settings > Models > 'as music model' > Import folder, pick this folder.")
