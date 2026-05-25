# ElevenLabs TTS for NVDA — Technical Reference
  
For developers, maintainers, and anyone who needs to understand how the
add-on actually works under the hood. Pairs with USER_GUIDE.md (which
is for end users).

---

## 1. High-level architecture

Three modules talk to each other:

```
┌─────────────────────────────────────────────────────────────────┐
│  NVDA process                                                   │
│                                                                 │
│  ┌─────────────────────────────┐     ┌─────────────────────┐   │
│  │ synthDrivers/elevenlabs.py  │     │ globalPlugins/      │   │
│  │   (the synth driver)        │     │   elevenlabsTTS/    │   │
│  │                             │     │   __init__.py       │   │
│  │  - speak() per NVDA speech  │     │   (global plugin)   │   │
│  │  - speakTranslation()       │     │                     │   │
│  │  - HTTP streaming + cache   │     │ - registers panel   │   │
│  │  - audio transforms         │     │ - NVDA+Shift+T      │   │
│  │  - worker thread + queue    │     │   gesture           │   │
│  └─────────────────────────────┘     └─────────────────────┘   │
│              ▲                                  │              │
│              │                                  │              │
│              └──────────────────────────────────┤              │
│                                                 ▼              │
│                              ┌───────────────────────────────┐ │
│                              │ globalPlugins/elevenlabsTTS/  │ │
│                              │   settings.py                 │ │
│                              │   (settings panel)            │ │
│                              │ - API key field               │ │
│                              │ - voice / model / etc.        │ │
│                              │ - Test / Refresh / Pre-warm   │ │
│                              └───────────────────────────────┘ │
│                                                                │
└─────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
                ┌──────────────────────────────────┐
                │ api.elevenlabs.io (HTTPS)        │
                │ translate.googleapis.com (HTTPS) │
                └──────────────────────────────────┘
```

NVDA loads each module independently:

- **synth drivers** are loaded when their synth is activated.
- **global plugins** are loaded once at NVDA startup and stay resident.

Both find each other via `synthDriverHandler.getSynth()` and `from synthDrivers.elevenlabs import ...`.

---

## 2. File layout

```
elevenlabsTTS/
├── manifest.ini              # Add-on metadata. NVDA reads this on install.
├── LICENSE                   # MIT.
├── readme.txt                # Plain-text install/build notes for source readers.
├── CHANGELOG.txt             # What/Why/Purpose entry per release.
├── STORE_SUBMISSION.md       # How to ship a version to the NVDA Add-on Store.
├── build.py                  # `py -3 build.py --clean` → dist/*.nvda-addon
├── synthDrivers/
│   └── elevenlabs.py         # Synth driver, HTTP layer, cache, translate.
├── globalPlugins/
│   └── elevenlabsTTS/
│       ├── __init__.py       # Global plugin: registers panel + gesture.
│       └── settings.py       # wx settings panel + config spec.
├── docs/
│   ├── USER_GUIDE.md         # Plain-language guide for end users.
│   ├── TECHNICAL.md          # This file.
│   └── en/
│       └── readme.html       # HTML help shown by NVDA's "View add-on help".
└── locale/
    ├── README.txt
    ├── ta/LC_MESSAGES/nvda.po  # Tamil placeholder.
    └── hi/LC_MESSAGES/nvda.po  # Hindi placeholder.
```

`build.py` looks at `INCLUDE_ROOTS` (currently `manifest.ini`, `readme.txt`,
`CHANGELOG.txt`, `synthDrivers`, `globalPlugins`, `docs`, `locale`) and
zips everything that isn't `__pycache__`, `.pyc`, or an editor backup file.

---

## 3. Synth driver internals

### 3.1 Driver lifecycle

| Phase | What happens |
|---|---|
| NVDA loads synth | `__init__()` runs: voice list seeded with the hardcoded fallback, defaults loaded from `config.conf['elevenlabsTTS']`, worker thread started. If an API key is present, a background thread fetches `/v1/voices` and replaces the in-memory list. |
| `speak(sequence)` | Concatenates `str` items into `text`, increments `_cancelToken`, stops current player, puts `("speak", text, token)` on `self._queue`. |
| Worker pulls item | Calls `_streamAndPlay(text, token)`. Either reads cached PCM from disk (if eligible) or streams from the API. |
| `cancel()` | Increments `_cancelToken` and stops `_player`. The streaming loop checks `token != self._cancelToken` after every chunk and returns immediately if so. |
| `terminate()` | Cancels + puts `_STOP` on the queue → worker exits. |

### 3.2 Persistent HTTPS connection

Each worker-equivalent thread maintains a `threading.local()` instance of
`http.client.HTTPSConnection` pointed at `api.elevenlabs.io`. The first
call pays the TLS handshake (~200 ms). Every subsequent call reuses the
connection.

If the server has closed an idle keep-alive, the next request raises a
transport error. The retry logic in `_api_request()` resets the
connection (`_reset_https_conn()`) and retries **immediately** the first
time (the common stale-keep-alive case); subsequent retries use
exponential backoff (`0.4 s → 1.0 s → 2.5 s`).

Retries are triggered on:

- `http.client.HTTPException`, `ConnectionError`, `OSError` — transport.
- HTTP 5xx — server-side issue.
- HTTP 429 — rate-limited (`Retry-After` header is honoured).

Other 4xx are surfaced immediately as `ElevenLabsAPIError`.

### 3.3 Streaming text-to-speech

`_stream_tts()` is a generator yielding raw PCM chunks:

```
POST /v1/text-to-speech/{voice_id}/stream?output_format=pcm_16000&optimize_streaming_latency=4
Body: {"text": "...", "model_id": "eleven_turbo_v2_5",
       "voice_settings": {...}, "seed": 42,
       "language_code": "ta"  # only for multilingual_v2 model
}
Response: chunked binary PCM
```

The driver feeds each chunk through `_feed_chunk()` (pitch + volume
transforms) and into `nvwave.WavePlayer`. After feed it appends to the
cache buffer if cacheable.

### 3.4 The audio cache

| What | Value |
|---|---|
| Location | `%APPDATA%\nvda\elevenlabsTTS_cache\` |
| Key | `{voice_id_safe}_{output_format}_{sha1(text)[:16]}.pcm` |
| Cacheable | utterances of length ≤ 8 chars (`_CACHE_MAX_TEXT_LEN`) — letters, digits, short symbols |
| Skipped | translation path (model/language override sets `skip_cache=True`) |
| Capacity | 100 MB (`_CACHE_MAX_BYTES`) |
| Eviction | LRU by `st_mtime`; sweep runs on every successful write that pushes total > cap |
| Mutex | `_cache_eviction_lock` — only one eviction sweep at a time |

Pitch and volume are applied **at playback time**, not stored in the
cache, so changing those settings doesn't invalidate cached audio.

### 3.5 Pitch and volume transforms

Both are pure-Python (we replaced `audioop` in 1.0.2 when Python 3.13
removed the module).

- **Volume:** `_apply_volume()` scales each `int16` sample by `volume/100`
  via `array.array('h')`. Skips if volume == 100.
- **Pitch:** `_resample_mono16()` does per-chunk linear-interpolation
  resampling — feeding "more samples than were generated" raises pitch;
  fewer lowers it. Skips if pitch == 50. Per-chunk only, with a tiny
  inaudible seam at chunk boundaries.

### 3.6 Cancellation

Every loop that touches the network or feeds the player checks
`token != self._cancelToken` between operations. NVDA can interrupt
mid-utterance with negligible latency — the worker bails out before
yielding more bytes.

### 3.7 Voice list

- Hardcoded fallback (`_FALLBACK_VOICE_LIST`) used until a live fetch
  completes — keeps the synth selectable before any API call.
- `fetch_voices()` pulls `/v1/voices`, sorts Indian-accent voices first
  (label includes "indian"), formats as `Name (accent, gender)`.
- `refresh_voice_list_from_api()` swaps the module-level `VOICE_LIST`
  under `_voice_list_lock` and rebuilds the name↔id indexes.
- On driver init, if the saved default voice isn't in the live list
  (a common 402-paywall case), `_kick_off_voice_refresh()` switches to
  `VOICE_LIST[0]` and persists the new pick to
  `config.conf['elevenlabsTTS']['defaultVoice']`.

### 3.8 Translation path

```
SynthDriver.speakTranslation(text, lang_code)
  ↓
self._queue.put(("translate", text, token, lang_code))
  ↓
worker calls _streamAndPlay(text, token,
                            model_override="eleven_multilingual_v2",
                            language_override=lang_code)
  ↓
_stream_tts(..., model_id="eleven_multilingual_v2", language_code=lang_code)
```

Cache is bypassed (`skip_cache=True` when overrides are set), since the
same English text translated to different languages would collide on
cache key otherwise.

---

## 4. Global plugin

`globalPlugins/elevenlabsTTS/__init__.py`:

- Imports `ElevenLabsSettingsPanel` and `ensureConfigSpec` from
  `settings.py`, registers the panel into
  `gui.settingsDialogs.NVDASettingsDialog.categoryClasses` on startup,
  removes it on `terminate()`.
- Declares `script_translateSelection` with `@script(gesture="kb:NVDA+shift+t", category="ElevenLabs TTS")`.

Translation flow inside the script:

1. `_get_selected_text()` — tries treeInterceptor first, falls back to
   focus object's `POSITION_SELECTION` TextInfo. Returns "" if no
   selection.
2. `ui.message("Translating...")` — short status announcement.
3. Background thread:
   - `translate_text(text, target_lang)` → Google free endpoint.
   - `synth.speakTranslation(translated, target_lang)`.
4. Any failure → `wx.CallAfter(ui.message, ...)` shows an error on the
   NVDA speech channel, never blocks the UI.

The gesture is rebindable under NVDA → Preferences → Input gestures →
"ElevenLabs TTS" category, exactly because of the `category=` kwarg.

---

## 5. Settings panel

`globalPlugins/elevenlabsTTS/settings.py`:

### 5.1 Config spec

```python
CONFIG_SPEC = {
    "apiKey":              "string(default=\"\")",
    "defaultVoice":        "string(default=\"\")",
    "defaultModel":        "string(default=\"eleven_turbo_v2_5\")",
    "translationLanguage": "string(default=\"ta\")",
    "defaultRate":         "integer(default=50, min=0, max=100)",
    "defaultVolume":       "integer(default=100, min=0, max=100)",
    "defaultPitch":        "integer(default=50, min=0, max=100)",
}
```

Registered via `ensureConfigSpec()` on first load. Persisted into
`%APPDATA%\nvda\nvda.ini` under `[elevenlabsTTS]`.

### 5.2 Dynamic catalogues

| Catalogue | Source |
|---|---|
| Voices | live `synthDrivers.elevenlabs.VOICE_LIST` (loaded from API by the driver) |
| Models | static `MODEL_LIST` |
| Translation languages | static `LANGUAGE_LIST` minus the English entry |

Loaded lazily inside `_load_*` helpers so that the import chain
(`settings.py` → `synthDrivers.elevenlabs`) survives the case where the
synth module hasn't been touched yet by NVDA.

### 5.3 Background-thread UI patterns

Every operation that hits the network runs in a `threading.Thread(daemon=True)`:

- **Test API key** — `speak_test_phrase()` in worker, `wx.CallAfter` to
  show the dialog.
- **Quota refresh** — `diagnose_subscription()` in worker, `wx.CallAfter`
  to set the label.
- **Refresh voice list** — `refresh_voice_list_from_api()` in worker,
  `wx.CallAfter` to rebuild the Choice control.
- **Pre-warm cache** — `prewarm_cache_for_voice()` in worker, with a
  `wx.ProgressDialog` updated via `wx.CallAfter(progress.Update, …)`.

This keeps the dialog responsive even on slow networks.

### 5.4 Test button — two-step diagnostic

Designed to disambiguate three failure modes:

1. **Step 1:** `GET /v1/user/subscription` → tier, quota.
   - Failure here is **non-fatal**: scoped TTS-only keys reject this
     endpoint with 401 even though TTS itself works. We show
     `"Step 1 SKIPPED — key may be scoped to TTS only"` and continue.
2. **Step 2:** A real TTS call via `_stream_tts`. This is the actual
   "does the key work" check.
   - 200 + audio → all good.
   - 402 → `voice_unusable=True` flag returned; panel silently refreshes
     the voice list so the user gets a working voice on next try.

---

## 6. Network endpoints used

| Endpoint | Method | Purpose |
|---|---|---|
| `/v1/text-to-speech/{voice_id}/stream` | POST | The actual TTS — streaming PCM response. |
| `/v1/voices` | GET | List voices the account has access to. |
| `/v1/user/subscription` | GET | Quota + tier display in settings panel. |
| `translate.googleapis.com/translate_a/single` | GET | Google's free public translation endpoint (no API key). |

All ElevenLabs calls go through `_api_request()` which uses the
persistent `http.client.HTTPSConnection` with retry/backoff. The Google
call uses a one-shot `urllib.request.urlopen()` with a browser-like
User-Agent (Google blocks the default urllib UA).

---

## 7. Configuration

Stored in `%APPDATA%\nvda\nvda.ini`. Example after first-time setup:

```ini
[elevenlabsTTS]
apiKey = sk_a1b2c3d4...
defaultVoice = Adam
defaultModel = eleven_turbo_v2_5
translationLanguage = ta
defaultRate = 50
defaultVolume = 100
defaultPitch = 50
```

Plus NVDA's own per-synth voice ring values stored under
`[speech][elevenlabs]`.

---

## 8. Build and distribution

### 8.1 Building locally

```
py -3 D:\elevenlabs\elevenlabs-tts-addon\build.py --clean
```

Reads `version` from `manifest.ini`, walks `INCLUDE_ROOTS`, skips
`__pycache__` / `.pyc` / editor backups, writes
`dist/elevenlabsTTS-X.Y.Z.nvda-addon`.

### 8.2 Versioning convention

- `X.Y.0` — feature release (e.g. translation gesture)
- `X.Y.Z` (Z > 0) — bugfix / polish release
- `manifest.ini`'s `lastTestedNVDAVersion` should be bumped to match the
  NVDA version actively tested against, otherwise NVDA flags the add-on
  as "not tested" and forces a compatibility-override prompt.

### 8.3 Submitting to the NVDA Add-on Store

See `STORE_SUBMISSION.md` for the full workflow. Short version:

1. Tag the release on GitHub, attach the `.nvda-addon`.
2. Compute SHA-256 of the asset.
3. PR `addons/elevenlabsTTS/X.Y.Z.json` to `nvaccess/addon-datastore`.

---

## 9. Debugging

### 9.1 Log lines to look for

Every meaningful event emits an `ElevenLabs:` line in NVDA's log. Open
**NVDA → Tools → View log** and Ctrl+F for `ElevenLabs`.

| Line prefix | What it means |
|---|---|
| `ElevenLabs: Client initialized successfully` | (Legacy from pre-1.1; no longer printed.) |
| `ElevenLabs: settings panel registered.` | Global plugin loaded fine. |
| `ElevenLabs: voice list loaded from API (N voices).` | Live voice fetch worked. |
| `ElevenLabs: using fallback voice list ...` | Live fetch failed — hardcoded list shown. |
| `ElevenLabs: saved voice X is not available on this tier; switching to Y` | Auto-pick of first available voice. |
| `ElevenLabs: stale connection, reconnecting immediately (...)` | Common, harmless — keep-alive expired. |
| `ElevenLabs: transport error on attempt N/N+1, retrying in Ks` | Network blip; backoff retry. |
| `ElevenLabs: HTTP N on attempt ... retrying in Ks` | 5xx / 429 retry. |
| `ElevenLabs: API error (...): ...` | Final failure after retries; user heard nothing. |
| `ElevenLabs test: step 1 — /v1/user/subscription` | Test diagnostic running. |
| `ElevenLabs prewarm: voice=X cached=N skipped=N errors=N` | Pre-warm completed. |
| `ElevenLabs translate: ...` | Translation gesture errored. |

### 9.2 Common failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| No speech, log says "API key missing" | Key wasn't saved in config | Re-enter in settings panel, press OK. |
| "API error 402" on every TTS call | Voice is paid-only on user's tier | Pick a different voice; the panel auto-refreshes after a 402 from the Test button. |
| "API error 401" | Key is wrong/revoked | Get a fresh key from ElevenLabs. |
| Letter speech lags 500 ms on first press | Normal — first network call | Click Pre-warm cache once per voice. |
| Speech sounds correct in English but Tamil gibberish | Wrong model | Setting Model = Multilingual v2 only matters for typed Tamil text. Translation gesture forces multilingual regardless. |
| Add-on isn't in `Tools → Add-ons` after install | Pending install never promoted | Always click Yes on the "Restart NVDA?" prompt. |
| Synth reverts to Vocalizer after Windows restart | "Save configuration on exit" off, or NVDA killed hard | Tick the save-on-exit checkbox and press NVDA+Ctrl+C after changes. |

### 9.3 Reproducing a problem cleanly

1. Close NVDA.
2. Move `%APPDATA%\nvda\elevenlabsTTS_cache\` aside (renaming it is enough — clean cache).
3. In `nvda.ini`, blank out the `[elevenlabsTTS]` section (or delete it).
4. Start NVDA → no synth selected → install add-on fresh.

That gives a clean-slate first-run experience for reproducing user reports.

---

## 10. Adding features

### 10.1 New voice setting (e.g. "emphasis")

1. Add `emphasis` to `CONFIG_SPEC` in `settings.py`.
2. Add a control to `makeSettings()` and save in `onSave()`.
3. Read it in the synth driver's `_load_defaults_from_config()` and store
   on `self._emphasis`.
4. Pass into `_stream_tts(... voice_settings={..., "emphasis": self._emphasis})`.

If you want it in the NVDA settings ring, add a `NumericSynthSetting`
entry to `supportedSettings` and add a `@property` getter/setter.

### 10.2 New language for translation

1. Append `("Display name", "iso_code")` to `LANGUAGE_LIST` in `elevenlabs.py`.
2. (Optional) add a translated sample to `_TEST_PHRASES` if you want the
   future Test button to speak it.
3. Done — the settings panel rebuilds the dropdown from `LANGUAGE_LIST`
   on next panel open.

### 10.3 New gesture

In `globalPlugins/elevenlabsTTS/__init__.py`, add another
`@script(gesture=..., category="ElevenLabs TTS")` method. NVDA picks it
up automatically and shows it in the Input gestures dialog.

### 10.4 New endpoint

Add a helper next to `fetch_voices()` / `fetch_subscription()` that calls
`_api_request()`. Keep the same returning-`None`-on-failure pattern so
callers can degrade gracefully.

---

## 11. What's intentionally NOT here

To keep the codebase small and reliable:

- **No third-party Python dependencies.** Everything is stdlib. The
  official `elevenlabs` SDK is **not** vendored — its file paths blow
  past Windows' MAX_PATH on install. Hand-rolled HTTP calls instead.
- **No WebSocket path.** Tried in 1.5.0, no perceptible speed win,
  removed in 1.5.1.
- **No per-app voice routing.** Listed as future work (#16 in the
  internal task list).
- **No on-device TTS.** Cloud-only. Online required.
- **No audio file export.** This is a screen-reader synthesizer, not a
  voice-clip generator.

---

## 12. Credits

- **Authors:** Tamil Selvan S and Vignesh
- **License:** MIT (`LICENSE` in the repo root)
- **NVDA add-on API:** © NV Access, NVDA is GPLv2+; this add-on talks
  to the API only, doesn't statically link.
- **ElevenLabs API:** © ElevenLabs Inc. — used via their public HTTP/JSON
  interface.
- **Google Translate free endpoint:** unofficial; used for the
  translate-and-speak gesture.
