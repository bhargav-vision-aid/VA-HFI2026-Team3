"""Settings panel for the ElevenLabs TTS add-on.

Adds an "ElevenLabs TTS" category under NVDA Menu > Preferences > Settings.
The user must paste their ElevenLabs API key here before the synthesizer can
produce speech. The panel also exposes:

* A "Test" button that calls the API right now to prove the key works.
* The current ElevenLabs quota (characters used / limit).
* The on-disk cache size, with a button to clear it.
* Default voice / rate / volume / pitch.
"""

import threading

import wx

import addonHandler
import config
import gui
from gui.settingsDialogs import SettingsPanel
from logHandler import log

# Install _() into this module's globals so user-facing strings get
# translated when a Hindi / Tamil / etc. .mo file is present in locale/.
addonHandler.initTranslation()

# Import the synth driver lazily inside methods to avoid pulling nvwave during
# plugin import; that keeps NVDA's startup unaffected when this panel is just
# being registered.

CONFIG_SECTION = "elevenlabsTTS"


def _load_voice_choices():
    """Return ([display_names], name_to_id_dict) — live API list if we have a
    key, hardcoded fallback otherwise."""
    try:
        from synthDrivers.elevenlabs import VOICE_LIST  # noqa: WPS433
        names = [name for name, _ in VOICE_LIST]
        mapping = {name: vid for name, vid in VOICE_LIST}
        return names, mapping
    except Exception:
        return ["Rachel"], {"Rachel": "21m00Tcm4TlvDq8ikWAM"}


def _load_model_choices():
    try:
        from synthDrivers.elevenlabs import MODEL_LIST
        labels = [lbl for lbl, _ in MODEL_LIST]
        mapping = {lbl: mid for lbl, mid in MODEL_LIST}
        rev = {mid: lbl for lbl, mid in MODEL_LIST}
        return labels, mapping, rev
    except Exception:
        return (
            ["Turbo v2.5 (balanced, default)"],
            {"Turbo v2.5 (balanced, default)": "eleven_turbo_v2_5"},
            {"eleven_turbo_v2_5": "Turbo v2.5 (balanced, default)"},
        )


def _load_translation_language_choices():
    """Indian-language targets for the translate-selection gesture.

    English is intentionally excluded — translating English text TO English
    isn't a meaningful action for this add-on's user base.
    """
    try:
        from synthDrivers.elevenlabs import LANGUAGE_LIST
        # Drop the English (India) entry — only target Indian languages.
        filtered = [(lbl, code) for lbl, code in LANGUAGE_LIST if code != "en"]
        labels = [lbl for lbl, _ in filtered]
        mapping = {lbl: code for lbl, code in filtered}
        rev = {code: lbl for lbl, code in filtered}
        return labels, mapping, rev
    except Exception:
        return (
            ["Tamil"],
            {"Tamil": "ta"},
            {"ta": "Tamil"},
        )


CONFIG_SPEC = {
    "apiKey":               "string(default=\"\")",
    "defaultVoice":         "string(default=\"\")",
    "defaultModel":         "string(default=\"eleven_turbo_v2_5\")",
    # Target language used by the NVDA+Shift+T translate-selection gesture.
    # Indian languages only (Tamil default). The old defaultLanguage key
    # (synth-level pronunciation hint) was removed in 1.4.0.
    "translationLanguage":  "string(default=\"ta\")",
    "defaultRate":          "integer(default=50, min=0, max=100)",
    "defaultVolume":        "integer(default=100, min=0, max=100)",
    "defaultPitch":         "integer(default=50, min=0, max=100)",
}


def ensureConfigSpec():
    """Install the config spec the first time the add-on loads."""
    if CONFIG_SECTION not in config.conf.spec:
        config.conf.spec[CONFIG_SECTION] = CONFIG_SPEC


def _format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.2f} GB"


def _format_quota_from_diagnosis(ok: bool, summary: str, info) -> str:
    if ok and isinstance(info, dict):
        used = info.get("character_count")
        limit = info.get("character_limit")
        tier = info.get("tier") or "?"
        if isinstance(used, int) and isinstance(limit, int) and limit > 0:
            pct = used * 100.0 / limit
            return f"Quota: {used:,} / {limit:,} chars used ({pct:.1f}%, tier: {tier})"
        return f"Quota: tier {tier}"
    # Not OK — explain why instead of "unavailable"
    if "401" in summary or "scoped" in summary.lower():
        return "Quota: not available (key scoped to TTS only — TTS still works)"
    if "network" in summary.lower() or "transport" in summary.lower():
        return "Quota: not available (network unreachable)"
    return f"Quota: not available ({summary})"


class ElevenLabsSettingsPanel(SettingsPanel):
    # Translators: heading for the settings category under
    # NVDA Menu > Preferences > Settings.
    title = _("ElevenLabs TTS")

    def makeSettings(self, settingsSizer):
        ensureConfigSpec()
        section = config.conf[CONFIG_SECTION]

        # Load dynamic catalogues — voices come from the live API when we
        # have a key, models from the driver's static table. Translation
        # languages are Indian-only (no English target).
        self._voice_names, self._voice_name_to_id = _load_voice_choices()
        self._model_labels, self._model_label_to_id, self._model_id_to_label = _load_model_choices()
        self._lang_labels, self._lang_label_to_code, self._lang_code_to_label = _load_translation_language_choices()

        helper = gui.guiHelper.BoxSizerHelper(self, sizer=settingsSizer)

        intro = wx.StaticText(
            self,
            label=(
                "Enter your ElevenLabs API key below. The key is required before "
                "the synthesizer can speak. You can get a free key from "
                "https://elevenlabs.io after signing in."
            ),
        )
        intro.Wrap(540)
        helper.addItem(intro)

        # ----- API key + show/hide -----
        self.apiKeyCtrl = helper.addLabeledControl(
            # Translators: label for the API key text box.
            _("ElevenLabs &API key:"),
            wx.TextCtrl,
            style=wx.TE_PASSWORD,
            value=section.get("apiKey", "") or "",
        )
        # Translators: checkbox to toggle API key visibility.
        self.showKeyCtrl = helper.addItem(wx.CheckBox(self, label=_("&Show API key")))
        self.showKeyCtrl.Bind(wx.EVT_CHECKBOX, self._onToggleShowKey)

        # ----- Test button + status label -----
        testRow = wx.BoxSizer(wx.HORIZONTAL)
        # Translators: button that calls the ElevenLabs API to verify the key.
        self.testBtn = wx.Button(self, label=_("&Test API key"))
        self.testBtn.Bind(wx.EVT_BUTTON, self._onTestKey)
        testRow.Add(self.testBtn, 0, wx.ALIGN_CENTER_VERTICAL)
        self.testStatus = wx.StaticText(self, label="")
        testRow.Add(self.testStatus, 1, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 12)
        helper.addItem(testRow)

        # ----- Live quota label -----
        self.quotaLabel = wx.StaticText(self, label="Quota: loading…")
        helper.addItem(self.quotaLabel)
        self._refresh_quota_async()

        # ----- Default voice -----
        self.voiceCtrl = helper.addLabeledControl(
            "Default &voice:",
            wx.Choice,
            choices=self._voice_names,
        )
        current_voice = (section.get("defaultVoice") or "").strip()
        if current_voice and current_voice in self._voice_names:
            self.voiceCtrl.SetStringSelection(current_voice)
        elif self._voice_names:
            self.voiceCtrl.SetSelection(0)

        # Refresh-voices button: pulls /v1/voices live, then refills the
        # voice dropdown with whatever is actually in the user's library.
        self.refreshVoicesBtn = helper.addItem(wx.Button(self, label="Re&fresh voice list"))
        self.refreshVoicesBtn.Bind(wx.EVT_BUTTON, self._onRefreshVoices)

        # ----- Default model -----
        self.modelCtrl = helper.addLabeledControl(
            "&Model:",
            wx.Choice,
            choices=self._model_labels,
        )
        current_model_id = (section.get("defaultModel") or "eleven_turbo_v2_5").strip()
        current_model_label = self._model_id_to_label.get(current_model_id)
        if current_model_label and current_model_label in self._model_labels:
            self.modelCtrl.SetStringSelection(current_model_label)
        else:
            self.modelCtrl.SetSelection(0)
        self.modelCtrl.Bind(wx.EVT_CHOICE, self._onModelChanged)

        # ----- Translation language (target for NVDA+Shift+T) -----
        transNote = wx.StaticText(
            self,
            label=(
                "Translation: select text in any application, then press "
                "NVDA+Shift+T. The selection will be translated into the "
                "language picked below and spoken aloud. The shortcut is "
                "rebindable under NVDA Menu > Preferences > Input gestures "
                "> ElevenLabs TTS. Translation is powered by Google's free "
                "public endpoint — no extra key required. Hindi and Tamil "
                "are officially supported; the rest are experimental."
            ),
        )
        transNote.Wrap(540)
        helper.addItem(transNote)

        self.languageCtrl = helper.addLabeledControl(
            "&Translation language:",
            wx.Choice,
            choices=self._lang_labels,
        )
        current_lang_code = (section.get("translationLanguage") or "ta").strip()
        current_lang_label = self._lang_code_to_label.get(current_lang_code, "Tamil")
        if current_lang_label in self._lang_labels:
            self.languageCtrl.SetStringSelection(current_lang_label)
        elif self._lang_labels:
            self.languageCtrl.SetSelection(0)

        # ----- Default rate / volume / pitch -----
        self.rateCtrl = helper.addLabeledControl(
            "Default &rate (0-100):",
            wx.SpinCtrl, min=0, max=100,
            initial=int(section.get("defaultRate", 50)),
        )
        self.volumeCtrl = helper.addLabeledControl(
            "Default vo&lume (0-100):",
            wx.SpinCtrl, min=0, max=100,
            initial=int(section.get("defaultVolume", 100)),
        )
        self.pitchCtrl = helper.addLabeledControl(
            "Default &pitch (0-100, 50 = neutral):",
            wx.SpinCtrl, min=0, max=100,
            initial=int(section.get("defaultPitch", 50)),
        )

        # ----- Cache controls -----
        cacheRow = wx.BoxSizer(wx.HORIZONTAL)
        self.cacheLabel = wx.StaticText(self, label="Cache: …")
        cacheRow.Add(self.cacheLabel, 1, wx.ALIGN_CENTER_VERTICAL)
        self.prewarmBtn = wx.Button(self, label="Pre-&warm cache")
        self.prewarmBtn.Bind(wx.EVT_BUTTON, self._onPrewarmCache)
        cacheRow.Add(self.prewarmBtn, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 12)
        self.clearCacheBtn = wx.Button(self, label="&Clear cache")
        self.clearCacheBtn.Bind(wx.EVT_BUTTON, self._onClearCache)
        cacheRow.Add(self.clearCacheBtn, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 12)
        helper.addItem(cacheRow)
        self._refresh_cache_label()

        # ----- Hint -----
        hint = wx.StaticText(
            self,
            label=(
                "Tip: while ElevenLabs TTS is the active synthesizer you can change "
                "rate, voice, volume and pitch on the fly with NVDA+Ctrl+Left/Right "
                "and NVDA+Ctrl+Up/Down."
            ),
        )
        hint.Wrap(540)
        helper.addItem(hint)

    # -----------------------------------------------------------------
    # Show/hide API key
    # -----------------------------------------------------------------
    def _onToggleShowKey(self, evt):
        current = self.apiKeyCtrl.GetValue()
        parent_sizer = self.apiKeyCtrl.GetContainingSizer()
        show = self.showKeyCtrl.GetValue()
        style = 0 if show else wx.TE_PASSWORD
        new_ctrl = wx.TextCtrl(self, value=current, style=style)
        parent_sizer.Replace(self.apiKeyCtrl, new_ctrl)
        self.apiKeyCtrl.Destroy()
        self.apiKeyCtrl = new_ctrl
        self.Layout()

    # -----------------------------------------------------------------
    # Test button — calls the API in a worker thread so the UI stays
    # responsive while the round-trip happens.
    # -----------------------------------------------------------------
    def _onTestKey(self, evt):
        api_key = self.apiKeyCtrl.GetValue().strip()
        voice_name = self.voiceCtrl.GetStringSelection() or (
            self._voice_names[0] if self._voice_names else ""
        )
        voice_id = self._voice_name_to_id.get(voice_name, "")
        if not voice_id:
            self.testStatus.SetLabel("No voice available — refresh the voice list first.")
            return
        if not api_key:
            self.testStatus.SetLabel("Enter an API key first.")
            return
        # Test plays an English phrase using the user's saved Model.
        # Translation-language verification is the gesture's job, not Test's.
        model_id = self._selected_model_id()
        self.testBtn.Disable()
        self.testStatus.SetLabel("Testing…")

        def worker():
            from synthDrivers.elevenlabs import speak_test_phrase
            ok, msg, voice_unusable = speak_test_phrase(
                api_key,
                voice_id,
                voice_label=voice_name,
                model_id=model_id,
            )
            wx.CallAfter(self._on_test_done, ok, msg, voice_unusable)

        threading.Thread(target=worker, daemon=True).start()

    def _on_test_done(self, ok: bool, msg: str, voice_unusable: bool = False):
        self.testBtn.Enable()
        short = msg.splitlines()[0] if msg else ""
        self.testStatus.SetLabel(("OK — " if ok else "Failed — ") + short)

        style = wx.OK | (wx.ICON_INFORMATION if ok else wx.ICON_ERROR)
        wx.MessageBox(
            msg,
            "ElevenLabs TTS — Test result" if ok else "ElevenLabs TTS — Test failed",
            style=style,
            parent=self,
        )
        if ok:
            # A successful test consumed characters — surface the new quota.
            self._refresh_quota_async()
        elif voice_unusable:
            # 402 on the selected voice. Step 1 already proved the key works,
            # so silently reload /v1/voices to show what the user CAN use.
            self._refresh_voices_silent()

    def _refresh_voices_silent(self):
        """Reload /v1/voices and update the dropdown without popping a dialog.

        Used after a 402 on the selected voice in the test — the error
        dialog has already told the user what happened; we just need to
        get them a fresh list of usable voices.
        """
        api_key = self.apiKeyCtrl.GetValue().strip()
        if not api_key:
            return

        def worker():
            from synthDrivers.elevenlabs import refresh_voice_list_from_api, VOICE_LIST
            refresh_voice_list_from_api(api_key)
            new_names = [name for name, _ in VOICE_LIST]
            new_map = {name: vid for name, vid in VOICE_LIST}
            current_pick = self.voiceCtrl.GetStringSelection()

            def apply():
                self._voice_names = new_names
                self._voice_name_to_id = new_map
                self.voiceCtrl.Set(new_names)
                if current_pick in new_names:
                    self.voiceCtrl.SetStringSelection(current_pick)
                elif new_names:
                    self.voiceCtrl.SetSelection(0)
                log.info("ElevenLabs: voice list silently refreshed after 402.")

            wx.CallAfter(apply)

        threading.Thread(target=worker, daemon=True).start()

    # -----------------------------------------------------------------
    # Quota — fetched in a worker thread on panel open.
    # -----------------------------------------------------------------
    def _refresh_quota_async(self):
        api_key = self.apiKeyCtrl.GetValue().strip()
        if not api_key:
            self.quotaLabel.SetLabel("Quota: enter an API key to load")
            return

        def worker():
            from synthDrivers.elevenlabs import diagnose_subscription
            ok, summary, info = diagnose_subscription(api_key)
            wx.CallAfter(
                self.quotaLabel.SetLabel,
                _format_quota_from_diagnosis(ok, summary, info),
            )

        threading.Thread(target=worker, daemon=True).start()

    # -----------------------------------------------------------------
    # Cache
    # -----------------------------------------------------------------
    def _refresh_cache_label(self):
        try:
            from synthDrivers.elevenlabs import _cache_size_bytes
            size = _cache_size_bytes()
            self.cacheLabel.SetLabel(f"Cache: {_format_bytes(size)} on disk")
        except Exception as e:
            self.cacheLabel.SetLabel(f"Cache: (size unavailable: {e})")

    def _onPrewarmCache(self, evt):
        """Fetch every common single character for the selected voice.

        Runs in a worker thread with a wx.ProgressDialog so the user
        sees what's happening and can cancel.
        """
        api_key = self.apiKeyCtrl.GetValue().strip()
        if not api_key:
            wx.MessageBox(
                "Enter an API key first.",
                "ElevenLabs TTS — Pre-warm",
                style=wx.OK | wx.ICON_WARNING,
                parent=self,
            )
            return
        voice_name = self.voiceCtrl.GetStringSelection() or (
            self._voice_names[0] if self._voice_names else ""
        )
        voice_id = self._voice_name_to_id.get(voice_name, "")
        if not voice_id:
            wx.MessageBox(
                "No voice selected.",
                "ElevenLabs TTS — Pre-warm",
                style=wx.OK | wx.ICON_WARNING,
                parent=self,
            )
            return
        model_id = self._selected_model_id()
        lang_label = self.languageCtrl.GetStringSelection() or "English (India)"
        lang_code = self._lang_label_to_code.get(lang_label, "en")

        from synthDrivers.elevenlabs import prewarm_cache_for_voice, _PREWARM_CHARS
        total = len(_PREWARM_CHARS)
        progress = wx.ProgressDialog(
            title="ElevenLabs TTS — Pre-warming cache",
            message=f"Fetching audio for {total} characters…",
            maximum=total,
            parent=self,
            style=wx.PD_APP_MODAL | wx.PD_CAN_ABORT | wx.PD_AUTO_HIDE,
        )

        cancelled_flag = {"v": False}

        def progress_cb(done, total_n, ch):
            if cancelled_flag["v"]:
                return
            def update():
                cont, _skip = progress.Update(done, f"Cached '{ch}' ({done}/{total_n})")
                if not cont:
                    cancelled_flag["v"] = True
            wx.CallAfter(update)

        def worker():
            cached, skipped, errors = prewarm_cache_for_voice(
                api_key=api_key,
                voice_id=voice_id,
                model_id=model_id,
                language_code=lang_code,
                progress_cb=progress_cb,
            )
            def done():
                progress.Destroy()
                wx.MessageBox(
                    f"Pre-warm complete.\n\n"
                    f"Newly cached: {cached}\n"
                    f"Already cached: {skipped}\n"
                    f"Errors: {errors}",
                    "ElevenLabs TTS — Pre-warm",
                    style=wx.OK | wx.ICON_INFORMATION,
                    parent=self,
                )
                self._refresh_cache_label()
            wx.CallAfter(done)

        threading.Thread(target=worker, daemon=True).start()

    def _onClearCache(self, evt):
        # Show size before clearing so the user can confirm something
        # actually happened.
        try:
            from synthDrivers.elevenlabs import _cache_size_bytes, _clear_cache
            before = _cache_size_bytes()
            removed = _clear_cache()
            after = _cache_size_bytes()
            log.info(f"ElevenLabs: cache cleared, {removed} files removed "
                     f"({_format_bytes(before)} -> {_format_bytes(after)}).")
            wx.MessageBox(
                f"Cache cleared.\n\n"
                f"Files removed: {removed}\n"
                f"Disk usage:    {_format_bytes(before)} -> {_format_bytes(after)}",
                "ElevenLabs TTS — Cache cleared",
                style=wx.OK | wx.ICON_INFORMATION,
                parent=self,
            )
        except Exception as e:
            log.error(f"ElevenLabs: cache clear failed: {e}")
            wx.MessageBox(
                f"Could not clear cache: {e}",
                "ElevenLabs TTS — Cache clear failed",
                style=wx.OK | wx.ICON_ERROR,
                parent=self,
            )
        self._refresh_cache_label()

    # -----------------------------------------------------------------
    def _selected_model_id(self) -> str:
        label = self.modelCtrl.GetStringSelection()
        return self._model_label_to_id.get(label, "eleven_turbo_v2_5")

    def _onModelChanged(self, evt):
        # Reserved for future model-dependent logic. Currently the
        # translation language picker is independent of the chosen model
        # because the translate gesture always uses eleven_multilingual_v2.
        pass

    # -----------------------------------------------------------------
    # Re-fetch /v1/voices and rebuild the voice dropdown
    # -----------------------------------------------------------------
    def _onRefreshVoices(self, evt):
        api_key = self.apiKeyCtrl.GetValue().strip()
        if not api_key:
            wx.MessageBox(
                "Enter an API key first.",
                "ElevenLabs TTS — Refresh voices",
                style=wx.OK | wx.ICON_WARNING,
                parent=self,
            )
            return
        self.refreshVoicesBtn.Disable()

        def worker():
            from synthDrivers.elevenlabs import refresh_voice_list_from_api, VOICE_LIST
            ok = refresh_voice_list_from_api(api_key)
            # VOICE_LIST is now updated; rebuild the dropdown on the UI thread.
            current_pick = self.voiceCtrl.GetStringSelection()
            new_names = [name for name, _ in VOICE_LIST]
            new_map = {name: vid for name, vid in VOICE_LIST}

            def apply():
                self._voice_names = new_names
                self._voice_name_to_id = new_map
                self.voiceCtrl.Set(new_names)
                if current_pick in new_names:
                    self.voiceCtrl.SetStringSelection(current_pick)
                elif new_names:
                    self.voiceCtrl.SetSelection(0)
                self.refreshVoicesBtn.Enable()
                wx.MessageBox(
                    f"Voice list reloaded from API ({len(new_names)} voices)."
                    if ok else
                    "Could not reach the API. Using the built-in fallback list.",
                    "ElevenLabs TTS — Refresh voices",
                    style=wx.OK | (wx.ICON_INFORMATION if ok else wx.ICON_WARNING),
                    parent=self,
                )

            wx.CallAfter(apply)

        threading.Thread(target=worker, daemon=True).start()

    # -----------------------------------------------------------------
    def onSave(self):
        ensureConfigSpec()
        section = config.conf[CONFIG_SECTION]
        section["apiKey"]           = self.apiKeyCtrl.GetValue().strip()
        section["defaultVoice"]     = self.voiceCtrl.GetStringSelection() or (
            self._voice_names[0] if self._voice_names else ""
        )
        section["defaultModel"]            = self._selected_model_id()
        lang_label = self.languageCtrl.GetStringSelection() or (
            self._lang_labels[0] if self._lang_labels else "Tamil"
        )
        section["translationLanguage"]     = self._lang_label_to_code.get(lang_label, "ta")
        section["defaultRate"]      = int(self.rateCtrl.GetValue())
        section["defaultVolume"]    = int(self.volumeCtrl.GetValue())
        section["defaultPitch"]     = int(self.pitchCtrl.GetValue())
        log.info("ElevenLabs: settings saved.")
