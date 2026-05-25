# Submitting elevenlabsTTS to the NVDA Add-on Store

The NVDA Add-on Store accepts add-ons via a pull request to
[github.com/nvaccess/addon-datastore](https://github.com/nvaccess/addon-datastore).
This is the checklist for getting this add-on accepted.

## 1. One-time setup

1. Pick a hosting location for the `.nvda-addon` file that exposes a
   stable HTTPS URL — GitHub Releases is the typical choice.
2. Fork [nvaccess/addon-datastore](https://github.com/nvaccess/addon-datastore).
3. Clone your fork locally.

## 2. Per-release steps

For every release (e.g., bumping from 1.3.0 → 1.4.0):

1. **Bump version**

   - Edit `manifest.ini`: `version = X.Y.Z`
   - Add a `CHANGELOG.txt` entry with What / Why / Purpose.

2. **Build**

   ```
   py -3 build.py --clean
   ```

   Output: `dist/elevenlabsTTS-X.Y.Z.nvda-addon`.

3. **Tag + release on GitHub**

   ```
   git tag vX.Y.Z
   git push origin vX.Y.Z
   gh release create vX.Y.Z dist/elevenlabsTTS-X.Y.Z.nvda-addon \
     --title "elevenlabsTTS X.Y.Z" --notes-file CHANGELOG.txt
   ```

   Record the SHA-256:

   ```
   certutil -hashfile dist/elevenlabsTTS-X.Y.Z.nvda-addon SHA256
   ```

4. **Open a PR against addon-datastore**

   In your fork, add:

   ```
   addons/elevenlabsTTS/X.Y.Z.json
   ```

   with this structure:

   ```json
   {
     "addonId": "elevenlabsTTS",
     "displayName": "ElevenLabs TTS",
     "URL": "https://github.com/<you>/elevenlabs-tts-addon/releases/download/vX.Y.Z/elevenlabsTTS-X.Y.Z.nvda-addon",
     "description": "ElevenLabs streaming AI text-to-speech for NVDA. Indian-focused: surfaces Indian voices and languages first.",
     "sha256": "<sha from step 3>",
     "homepage": "https://github.com/<you>/elevenlabs-tts-addon",
     "license": "MIT",
     "licenseURL": "https://github.com/<you>/elevenlabs-tts-addon/blob/main/LICENSE",
     "sourceURL": "https://github.com/<you>/elevenlabs-tts-addon",
     "addonVersionName": "X.Y.Z",
     "addonVersionNumber": { "major": X, "minor": Y, "patch": Z },
     "minNVDAVersion":      { "major": 2019, "minor": 3, "patch": 0 },
     "lastTestedVersion":   { "major": 2026, "minor": 1, "patch": 0 },
     "channel": "stable",
     "publisher": "Tamil Selvan S and Vignesh",
     "submissionTime": "<unix timestamp seconds>",
     "translations": []
   }
   ```

5. **Open the PR** — title `Add elevenlabsTTS X.Y.Z`.

6. **Address review comments.** The NVDA team verifies the file
   downloads, the SHA matches, and that it installs cleanly. Iterate
   until approved.

## 3. Things to watch out for

- The `addonId` in the store metadata must match `name` in `manifest.ini`
  (currently `elevenlabsTTS`).
- `lastTestedVersion` should match a version you've actually run NVDA
  against. Bumping it ahead of reality risks the add-on misbehaving in
  newer NVDA without warning.
- The Add-on Store does NOT pip-install dependencies — everything must
  be in the zip already. This add-on ships zero third-party deps
  (pure stdlib HTTP + custom audio path), so we're fine.
- API keys are user-supplied at runtime. NEVER bundle a key in the
  shipped zip.
