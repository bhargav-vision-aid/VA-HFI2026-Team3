import globalPluginHandler
import ui
import config
import gui

from .settings import SarvamSettingsPanel


class GlobalPlugin(globalPluginHandler.GlobalPlugin):

    scriptCategory = "Sarvam AI"

    # ✅ CORRECT gesture binding (CLASS LEVEL)
    __gestures = {
        "kb:NVDA+shift+t": "toggleTranslate",
        "kb:NVDA+shift+y": "translateSelection",   # ✅ NEW
    }

    def __init__(self):
        super().__init__()
        self._registerSettings()

        # ✅ Load config
        conf = config.conf.get("sarvamAI", {})
        self.translateEnabled = conf.get("translateEnabled", False)
        self.targetLang = conf.get("targetLang", "en-IN")

    def terminate(self):
        self._unregisterSettings()

    def _registerSettings(self):
        cats = gui.settingsDialogs.NVDASettingsDialog.categoryClasses
        if SarvamSettingsPanel not in cats:
            cats.append(SarvamSettingsPanel)

    def _unregisterSettings(self):
        cats = gui.settingsDialogs.NVDASettingsDialog.categoryClasses
        if SarvamSettingsPanel in cats:
            try:
                cats.remove(SarvamSettingsPanel)
            except:
                pass

    # ✅ SCRIPT
    def script_toggleTranslate(self, gesture):

        conf = config.conf.get("sarvamAI", {})
        current = str(conf.get("translateEnabled", "False")).lower() == "true"
        newState = not current

        if "sarvamAI" not in config.conf:
            config.conf["sarvamAI"] = {}

        config.conf["sarvamAI"]["translateEnabled"] = newState
        config.conf.save()

        # 🔥 clear old speech
        import synthDriverHandler
        synth = synthDriverHandler.getSynth()
        if synth and hasattr(synth, "cancel"):
            synth.cancel()

        state = "ON" if newState else "OFF"
        ui.message(f"Translation {state}")

    # ✅ Required for Input Gestures dialog
    script_toggleTranslate.__doc__ = "Toggle Sarvam AI translation"

    def script_translateSelection(self, gesture):

        import api
        import ui
        import wx
        import time
        from speech import speakMessage
        import keyboardHandler

        try:
            text = ""

            # ✅ 1. Try normal selection (Word, Notepad)
            try:
                obj = api.getFocusObject()
                text = obj.makeTextInfo("selection").text
            except:
                pass

            # ✅ 2. Try review cursor (browser fallback)
            if not text or not text.strip():
                try:
                    review = api.getReviewPosition()
                    text = review.text
                except:
                    pass

            # ✅ 3. FORCE clipboard (MOST IMPORTANT FIX)
            if not text or not text.strip():
                try:
                    # Simulate Ctrl+C
                    keyboardHandler.KeyboardInputGesture.fromName("control+c").send()
                    time.sleep(0.1)  # allow clipboard update

                    if wx.TheClipboard.Open():
                        data = wx.TextDataObject()
                        if wx.TheClipboard.GetData(data):
                            text = data.GetText()
                        wx.TheClipboard.Close()
                except:
                    pass

            # ❌ Nothing found
            if not text or not text.strip():
                ui.message("No text selected")
                return

            # 🔹 Config
            import config
            conf = config.conf.get("sarvamAI", {})
            targetLang = conf.get("targetLang", "en-IN")

            # ✅ Lazy translator
            if not hasattr(self, "_translator"):
                from .translator import SarvamTranslator
                try:
                    self._translator = SarvamTranslator()
                except:
                    ui.message("Translation not ready")
                    return

            # 🔹 Translate
            translated = self._translator.translate(text, targetLang)

            if not translated:
                ui.message("Translation failed")
                return

            # ✅ Copy translated text to clipboard
            try:
                if wx.TheClipboard.Open():
                    wx.TheClipboard.SetData(wx.TextDataObject(translated))
                    wx.TheClipboard.Close()
            except:
                pass

            # ✅ Speak
            speakMessage(translated)

        except Exception as e:
            ui.message("Translation failed")

    script_translateSelection.__doc__ = "translate Selected Text"