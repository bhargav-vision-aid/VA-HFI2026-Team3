# ElevenLabs TTS for NVDA — User Guide

A friendly, plain-language walkthrough for people who just want to **use**
the add-on. No coding, no jargon. If you're a developer who needs to know
*how* it works inside, read `TECHNICAL.md` instead.

---

## 1. What is this add-on?

ElevenLabs TTS lets NVDA speak in the **ElevenLabs AI voices** — the same
voices used by audiobook narrators, YouTubers, and podcasters. The voices
sound human, not robotic.

The add-on is **tuned for Indian users**: it surfaces Indian-accented voices
first, and includes a **translate-and-speak** keyboard shortcut for the ten
most-spoken Indian languages.

What it does in one sentence:

> Select any English text in any app, press **NVDA+Shift+T**, and hear it
> read aloud in Tamil, Hindi, Telugu, Marathi, Bengali, Kannada, Malayalam,
> Gujarati, Punjabi or Urdu — using a high-quality AI voice.

---

## 2. What you need before installing

| Requirement | Why |
|---|---|
| **Windows 10 or 11** | NVDA only runs on Windows. |
| **NVDA installed** (not portable) | Portable copies reset after every shutdown. The Start-Menu installed copy is the right one. |
| **Internet connection** | The AI voice runs in the cloud, not on your PC. |
| **ElevenLabs account** | Free tier available at https://elevenlabs.io (10,000 characters per month, no credit card required). |
| **An ElevenLabs API key** | A long string you copy from your ElevenLabs account page. |

### Quick way to check if you have installed (not portable) NVDA

Press **NVDA+N** to open the NVDA menu → **Help → About NVDA**.

- *"NVDA is installed on this computer"* → you're good.
- *"NVDA is running as a portable copy"* → please install NVDA properly
  from https://nvaccess.org. Add-ons don't persist on portable copies.

---

## 3. Getting your ElevenLabs API key

1. Go to **https://elevenlabs.io** and sign up (or sign in).
2. Top-right corner → click your profile picture → **Profile Settings**.
3. Scroll down to **API key**.
4. Click **Reveal** → **Copy**.

The key looks something like `sk_a1b2c3d4...` (long random characters).
Treat it like a password — anyone with the key can spend your monthly
character quota.

---

## 4. Installing the add-on

### Method A — From the NVDA Add-on Store (easiest, once published)

1. **NVDA+N → Tools → Add-on store**.
2. Search "ElevenLabs TTS".
3. Click **Install**.
4. When NVDA asks to restart — click **Yes**. Wait for NVDA to come back.

### Method B — From the `.nvda-addon` file (manual install)

1. Save the `elevenlabsTTS-X.Y.Z.nvda-addon` file somewhere you'll find it (Desktop is fine).
2. Press **Enter** on the file (or double-click it).
3. NVDA shows "Are you sure you want to install this add-on?" → press **Yes**.
4. NVDA shows "Add-on installed, restart NVDA now?" → press **Yes**.
5. Wait for NVDA to fully restart. Don't shut down Windows until it's back.

> **Important:** if you skip the restart prompt or shut down Windows
> before NVDA finishes restarting, the install can stay half-done. Always
> click **Yes** to restart, every time.

---

## 5. First-time setup (5 minutes, one time only)

After installing:

1. **NVDA+N → Preferences → Settings**.
2. In the left-side category list, find **ElevenLabs TTS**.
3. **Paste your API key** in the "ElevenLabs API key" box.
4. (Optional) tick **Show API key** to double-check what you pasted.
5. Click **Test API key** button. NVDA pops up a dialog after a moment:
   - **"Step 2 OK — voice 'Adam' plays …"** → everything works.
   - **"Voice X requires a paid plan"** → don't worry, the add-on now
     refreshes the voice list to show only voices you can use. Pick a
     different voice from the dropdown and Save.
6. Pick your **Default voice**, **Translation language** (Tamil, Hindi, etc.)
   and click **OK**.
7. Still in NVDA Settings, go to the **Speech** category.
8. Change **Synthesizer** to **"ElevenLabs Streaming AI"**.
9. Click **OK**.

NVDA should immediately start speaking in the ElevenLabs voice.

To make absolutely sure the settings save: press **NVDA+Ctrl+C**. NVDA will
say "Configuration saved." Now you can shut down Windows safely.

---

## 6. Day-to-day use

### Choosing different voices on the fly

While ElevenLabs is the active synth, NVDA's "settings ring" cycles through:

| Shortcut | Action |
|---|---|
| **NVDA+Ctrl+→** / **NVDA+Ctrl+←** | Move to the next / previous setting: rate, voice, volume, pitch. |
| **NVDA+Ctrl+↑** / **NVDA+Ctrl+↓** | Increase / decrease the current setting (or pick a different voice when "voice" is the active one). |

So a typical session might be:

- NVDA+Ctrl+Right four times → "Voice"
- NVDA+Ctrl+Up → switches to the next voice in your library
- NVDA+Ctrl+Up again → next voice

### Refreshing your voice list

If you add a new cloned voice to your ElevenLabs account, NVDA won't see
it until you refresh:

**Preferences → Settings → ElevenLabs TTS → Refresh voice list**.

A dialog tells you how many voices are now available. The new voice
appears in the Default voice dropdown.

### Speeding up letter-by-letter feedback

The first time NVDA speaks each letter (a, b, c…) it makes a quick network
call and saves the audio to disk. Every subsequent time you press that
letter, NVDA plays the saved audio — no network, instant.

To do this all at once for a new voice, click **Pre-warm cache** in the
settings panel. NVDA fetches all 42 common single characters in the
background (~30 seconds, ~150 characters of quota). After that, typing
feedback is buttery-smooth for that voice.

---

## 7. The translate-and-speak shortcut

This is the headline feature for Indian-language readers.

### How to use it

1. Open any app — browser, Notepad, Word, anywhere with selectable text.
2. **Select the text** you want translated (Shift+arrow keys, or click and drag).
3. Press **NVDA+Shift+T**.
4. NVDA briefly says "Translating…" and then speaks the selection in
   your chosen Indian language.

### Picking the target language

**Preferences → Settings → ElevenLabs TTS → Translation language**. Pick
one of:

- Tamil (default)
- Hindi
- Telugu
- Marathi
- Bengali
- Kannada
- Malayalam
- Gujarati
- Punjabi
- Urdu

Click OK. The next NVDA+Shift+T uses the new language.

### Changing the shortcut

If **NVDA+Shift+T** clashes with another shortcut, you can rebind it:

1. **NVDA+N → Preferences → Input gestures**.
2. Find the **ElevenLabs TTS** category.
3. Select "Translate the currently selected text…".
4. Click **Add** → press your preferred shortcut → **OK**.

### Notes on quality

- **Hindi and Tamil** are officially supported by ElevenLabs — quality is excellent.
- **Telugu, Marathi, Bengali, Kannada, Malayalam, Gujarati, Punjabi, Urdu**
  are best-effort — they're marked "(experimental)" in the dropdown.
  The model will usually do a decent job but won't be perfect.
- Translation itself is done by **Google's free public translation service**.
  No extra API key required. If it stops working for an hour, Google has
  rate-limited your IP — try again later.

---

## 8. Common questions and problems

### "I don't hear anything"

- Is the synthesizer set to ElevenLabs? **Preferences → Settings → Speech → Synthesizer**.
- Did you paste an API key? **Preferences → Settings → ElevenLabs TTS**.
- Did you click Test API key and see "Step 2 OK"? If not, the key isn't working.

### "After a Windows restart, the synth is back to Vocalizer"

NVDA saves which synth you chose, but only if "Save configuration on exit"
is ticked **and** NVDA exits cleanly. To force-save:

- Pick ElevenLabs as the synth.
- Press **NVDA+Ctrl+C**. NVDA confirms "Configuration saved".

After this, the synth choice survives reboots.

### "It says 'Voice X requires a paid plan'"

ElevenLabs moved several "premade" voices behind paywalls. Your **API key
still works** — just pick a different voice. Click **Refresh voice list**
in the settings panel; the dropdown will only show voices your account
can actually use.

### "My quota ran out"

ElevenLabs free tier is 10,000 characters per month. Watch the **Quota**
line at the top of the settings panel to see how much you've used.

If you ran out, options are:

- Wait until next month for the quota to reset.
- Upgrade your ElevenLabs plan.
- Lower how often NVDA reads things aloud (NVDA's punctuation and event
  settings have a big impact).

### "Translation stopped working"

- Google's free endpoint sometimes rate-limits per IP — wait an hour.
- Make sure you actually have text selected when you press NVDA+Shift+T.
- Make sure ElevenLabs is the active synthesizer (translation needs to
  speak through it).

### "Letters sound slow the first time"

Yes — that's the network round-trip. Click **Pre-warm cache** in the
settings panel once for each voice and it never happens again for that
voice.

### "I want to start fresh"

- **Clear cache** button in the settings panel wipes the saved audio.
- To reset all add-on settings: NVDA → Preferences → Settings →
  ElevenLabs TTS → blank the API key, blank Default voice etc., click OK.
- To remove the add-on entirely: NVDA → Tools → Manage add-ons → select
  ElevenLabs TTS → Remove → restart NVDA.

---

## 9. Where to get help

- **NVDA log** is your friend. **Tools → View log**. Search (Ctrl+F) for
  `ElevenLabs` — every important event the add-on does is logged there.
- **Author contact:** Tamil Selvan S and Vignesh (see `manifest.ini`).
- **License:** MIT — see `LICENSE` at the add-on root.

---

## 10. What the add-on does NOT do

So you don't waste time hunting for features that aren't there:

- **It does not translate everything NVDA reads.** Translation only
  happens when you press NVDA+Shift+T on a selection. NVDA's normal
  speech of English UI still sounds English.
- **It does not work offline.** ElevenLabs is a cloud service. No internet → no speech.
- **It does not store your API key in plain text on disk in a way the add-on
  authors can see.** The key sits in your local NVDA config, on your PC,
  encrypted at rest by Windows like any other file.
- **It does not include a paid voice library.** You only get voices your
  ElevenLabs account already has access to.

That's it. Happy reading.
