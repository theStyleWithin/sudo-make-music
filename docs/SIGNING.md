# Code signing the Windows build

Signing proves the files come from a known publisher and were not changed. It is the single most effective way to reduce
SmartScreen warnings and antivirus false positives. **Nothing is signed yet**: it needs a certificate that only you (the publisher)
can obtain, because a certificate authority has to verify your identity. The build is already prepared: it signs automatically as
soon as the two repository secrets below exist, and says "UNSIGNED" in the build log until then.

## Options (pick one)
1. **SignPath Foundation (free for open-source projects).** Apply at https://signpath.org/ (check their eligibility rules: public repo,
   open-source license). Signing then runs in their service; the workflow needs a SignPath step instead of the PFX step below. If you get
   approved, tell me and I will wire it (it uses their GitHub action and an API token you store as a repository secret).
2. **Azure Trusted Signing (about $10/month, Microsoft).** Works with GitHub Actions without a hardware token; needs an Azure
   account and identity validation. Also needs a different workflow step: tell me if you go this way.
3. **A certificate from a commercial CA** (OV/EV, roughly $100-400/year). Since 2023 these private keys must live on a hardware token or
   a cloud HSM, so you usually *cannot* export a `.pfx` for CI; use the CA's cloud-signing service (DigiCert KeyLocker, SSL.com eSigner, ...)
   and tell me which, so I wire its step.
4. **A `.pfx` file you can export** (older certificates, some resellers): the step already in `.github/workflows/release.yml` works with it:
   - Settings > Secrets and variables > Actions > New repository secret:
     - `WINDOWS_CERT_PFX_BASE64`: the PFX file, base64-encoded (`base64 -w0 cert.pfx`, or `[Convert]::ToBase64String([IO.File]::ReadAllBytes("cert.pfx"))`)
     - `WINDOWS_CERT_PASSWORD`: its password
   - The next Windows build signs `sudo-make-music-portable.exe` and the folder build's `sudo-make-music.exe` with SHA-256 and a DigiCert timestamp, then verifies them.

## What does not help
- **A self-signed certificate** gives no trust (SmartScreen still warns) and can look worse to scanners. Do not use one.
- Signing does not make SmartScreen silent immediately: a new publisher still builds reputation over some downloads (EV certificates skip that wait).

## Linux
AppImages can carry a GPG signature (`appimagetool --sign`). Not set up; ask if you want it.
