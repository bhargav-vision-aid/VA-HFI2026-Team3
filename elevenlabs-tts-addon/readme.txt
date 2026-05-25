ElevenLabs TTS — NVDA Add-on
============================

Streaming text-to-speech for NVDA, powered by the ElevenLabs API.

Folder layout
-------------
  manifest.ini
  readme.txt
  synthDrivers/
    elevenlabs.py
  globalPlugins/
    elevenlabsTTS/
      __init__.py
      settings.py

The driver talks to the ElevenLabs streaming REST API using Python's
standard library (urllib + ssl), so there is no third-party Python
package to vendor. The add-on is therefore architecture-independent.

Building the .nvda-addon file
-----------------------------
From this folder, run:

  powershell -NoLogo -Command ^
    "Compress-Archive -Path manifest.ini,readme.txt,addon -DestinationPath elevenlabsTTS.zip -Force; ^
     Rename-Item elevenlabsTTS.zip elevenlabsTTS-1.0.0.nvda-addon"

Then double-click the resulting `.nvda-addon` to install it.

First-time setup
----------------
1. Install the add-on. Restart NVDA when prompted.
2. Open NVDA Menu > Preferences > Settings.
3. Select the "ElevenLabs TTS" category.
4. Paste your ElevenLabs API key (get one free at https://elevenlabs.io)
   and click OK.
5. Open NVDA Menu > Preferences > Settings > Speech and choose
   "ElevenLabs Streaming AI" as the synthesizer.

What the settings panel controls
--------------------------------
* API key   — required, stored in NVDA config.
* Default voice  — one of the bundled free-tier voices.
* Default rate   — 0..100, 50 = neutral.
* Default volume — 0..100 (multiplied into each PCM chunk).
* Default pitch  — 0..100, 50 = neutral. Implemented via PCM
                   resampling so it works regardless of which
                   ElevenLabs plan you are on.

Live controls (when ElevenLabs is the active synthesizer)
---------------------------------------------------------
Use NVDA's settings ring to cycle and adjust at any time:
  NVDA+Ctrl+Right / Left  — next / previous setting (rate, voice,
                            volume, pitch).
  NVDA+Ctrl+Up    / Down  — increase / decrease the current setting,
                            or change the voice when "voice" is active.

Troubleshooting
---------------
* "API key missing" in NVDA log:
    Set the key in NVDA Menu > Preferences > Settings > ElevenLabs TTS.
* No audio but no error:
    The active synthesizer is not ElevenLabs. Switch under
    Preferences > Settings > Speech.
