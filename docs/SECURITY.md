# Security and privacy: what this app does

**No accounts, no API keys, no tokens, no telemetry, no cloud services.** The installers contain no secrets.

## Network
The app itself contains no network code. Network is used only when *you* trigger it:
- **Settings > Install ... buttons** (or `--install-backend`): runs `pip` to download PyTorch, ACE-Step, etc. from
  pypi.org, download.pytorch.org and github.com (ACE-Step / OpenVoice source zips). Needs internet once.
- **Model libraries** (Hugging Face-based ones) may download weights on first use **unless Offline mode is on**, which sets
  `HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE` and refuses to start a job without a local model.
- `tools/fetch_stable_audio_small.py` (a developer tool, not in the installers) reads *your own* `HF_TOKEN` to download a gated model.

## Disk and processes
- Data lives in one folder: Linux `~/.local/share/sudo-make-music`, Windows portable `sudo-make-music-data` next to the exe.
- Programs it starts: `pip` (only when you press an install button), `ffmpeg` (optional MP3/format conversion, only if installed),
  `nvidia-smi` (read-only GPU detection). Nothing else. The command box under the lyrics only accepts the phrase
  `sudo make music`; it is compared, never executed.
- The Windows exe's `--run-module` hook is limited to `pip`.

## Why antivirus tools may flag the Windows exe (false positives)
- It is a **PyInstaller one-file exe**: it unpacks itself to a temp folder and runs from there. That behaviour is the
  most common cause of generic detections ("Trojan.Generic", "malicious_confidence"), usually from 1-5 of ~70 engines.
- It is **unsigned** (code-signing certificates cost money), so SmartScreen warns and reputation systems have no history yet.
- The in-app installer downloads and runs `pip`, which can look like a "downloader" to behaviour-based engines.

What is done about it: the exe has an icon and version information; no UPX packer is used; unused modules are excluded; CI tries to compile
PyInstaller's bootloader from source (the stock prebuilt one is shared with lots of malware, so some engines match it by signature); an
unpacked **folder build** is published as a zip (no self-extracting exe); every Windows build must pass `--selfcheck` in CI; releases carry
GitHub build-provenance attestations. There is no paid code-signing certificate (`docs/SIGNING.md` lists the free options).

If you see detections: compare the SHA-256 on VirusTotal with `SHA256SUMS.txt` in the release; the exe is built from this
public source by public CI, so the build is auditable. Report false positives to the vendors (most have a submission form).
Do not run builds from anywhere except the official release page.

Found a real security problem? Open a GitHub issue (or contact the maintainer privately if it is sensitive).
