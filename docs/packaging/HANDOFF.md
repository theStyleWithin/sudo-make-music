# Packaging handoff (for whoever submits to Flathub / AUR)

You do **not** need the project owner. See `AUTHORIZATION.md` for the owner's standing permission. Everything
needed is in `packaging/`. Nothing here has been built by the original author's tooling on a real
machine, so please run the checklist below and fix what you find (PRs welcome).

## Shared facts
- App ID: `io.github.theStyleWithin.SudoMakeMusic`; license Unlicense; project is a **light Python app**
  (stdlib + numpy). The heavy AI libs (torch, ACE-Step, several GB) are intentionally *not* packaged;
  the app installs them into the user's data dir on first use (`sudo_make_music/runtime.py`, UI button
  "Install AI backend", or `sudo-make-music --install-backend cu126`). Models download on first generation.
- Desktop file, AppStream metainfo and icon: `packaging/common/`.
- Releases: tag `vX.Y.Z` on `main`. CI (`.github/workflows/release.yml`) builds AppImage, Windows exe, Android APK.

## AUR  (`packaging/aur/PKGBUILD`, package `sudo-make-music-git`)
1. `cp -r packaging/aur /tmp/smm-aur && cd /tmp/smm-aur`
2. Fill `# Maintainer:` line. `makepkg -si` to test (needs `base-devel`).
3. `makepkg --printsrcinfo > .SRCINFO`
4. Create an AUR account, then `git clone ssh://aur@aur.archlinux.org/sudo-make-music-git.git`, copy `PKGBUILD` + `.SRCINFO`, commit, push.
5. After the first tagged release, optionally add a non-git `sudo-make-music` package using the tag tarball + real sha256.
Check: `namcap PKGBUILD` and `namcap *.pkg.tar.zst`. Arch's pip is PEP 668 "externally managed"; the app uses `pip install --target` into the user dir, which is allowed.

## Flathub  (`packaging/flatpak/io.github.theStyleWithin.SudoMakeMusic.yml`)
1. A release tag must exist (`v0.1.0`) - set `commit:` in the manifest to `git rev-parse v0.1.0`.
2. Local test: `flatpak-builder --user --install --force-clean build packaging/flatpak/*.yml` then `flatpak run io.github.theStyleWithin.SudoMakeMusic`.
3. Validate: `flatpak run --command=flatpak-builder-lint org.flatpak.Builder manifest packaging/flatpak/*.yml` and `... appstream packaging/common/*.metainfo.xml`.
4. Follow https://docs.flathub.org/docs/for-app-authors/submission - PR the manifest to `flathub/flathub` (branch `new-pr`).
5. **Likely review friction:**
   - Runtime pip download of torch/ACE-Step may be questioned; be ready to explain (GPU wheels are multi-GB) or propose a separate extension/`extra-data`.
   - The `io.github.theStyleWithin.*` ID must be verified for ownership by Flathub; this may require the repo owner to add a verification token once (https://docs.flathub.org/docs/for-app-authors/verification). Mention that you submit with the owner's permission (see `AUTHORIZATION.md`).
   - Check that the `org.freedesktop.Platform` Python has `pip` (needed for the backend installer) and that CUDA works with `--device=all` plus the host's NVIDIA GL extension.
   - Update the numpy wheel pins/runtime version (`25.08`, Python 3.13) if they have moved.

## Other artifacts (for information)
- AppImage: `bash packaging/appimage/build.sh` (CI uploads it).
- Windows portable exe: `packaging/windows/build.ps1` (PyInstaller, data stored next to the exe).
- Android: `android/` is a thin WebView client for the desktop app on the same network (`sudo-make-music --host 0.0.0.0`). It cannot run the model on the phone.
