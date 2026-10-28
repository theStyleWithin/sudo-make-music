# Trust without buying a certificate

A code-signing certificate (what removes the Windows SmartScreen warning) costs money and needs your identity verified. This project
has no certificate, so **the Windows files are unsigned**. These are the free things in place instead, and the free route to real signing.

## In place now (free)
- **Build provenance attestation.** Every release file is attested by GitHub (sigstore): cryptographic proof it was built by this
  repository's public CI from a specific commit. Anyone can check a download:
  `gh attestation verify sudo-make-music-portable.exe --repo theStyleWithin/sudo-make-music`
- **`SHA256SUMS.txt`** in every release, so a hash on VirusTotal can be matched to the official file.
- **Folder build** (`sudo-make-music-windows-folder.zip`): no self-extracting exe, far fewer antivirus detections than the single exe.
- **Own bootloader:** CI compiles PyInstaller's bootloader from source (falls back to the stock one if that fails); the stock one is shared
  with malware and matched by some engines.
- Icon + version information, no UPX packer, unused modules excluded, and a **self-check** that every Windows build must pass in CI.

## Free ways to get real signing / reputation (needs you or a Windows user)
1. **SignPath Foundation: free code signing for open-source projects.** Apply at https://signpath.org/ (check their eligibility rules: public
   repository, open-source licence). If approved, tell me and I will wire the signing step into CI.
2. **Submit the release files to Microsoft** (free): https://www.microsoft.com/en-us/wdsi/filesubmission ("software developer" submission).
   It helps Defender/SmartScreen learn the files are fine; SmartScreen reputation also grows by itself as people download and run them.
3. **Report false positives** to any vendor that flags a file (VirusTotal links to each vendor's form). Most fix it within days.

## If you ever get a certificate
CI already signs automatically when two repository secrets exist: `WINDOWS_CERT_PFX_BASE64` (the .pfx, base64) and `WINDOWS_CERT_PASSWORD`.
Note: since 2023 new commercial certificates usually cannot be exported as a .pfx (hardware token / cloud HSM); use the CA's cloud signing
and have the CI step adapted.

## What does not help
A **self-signed certificate** gives no trust (SmartScreen still warns) and can look worse to scanners. Do not use one.
