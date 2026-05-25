"""ElevenLabs TTS global plugin.

Responsibilities:
* Register the config spec so the saved API key + defaults persist.
* Add an "ElevenLabs TTS" panel to NVDA Menu > Preferences > Settings.
* Bind NVDA+Shift+T to "translate the currently selected text into the
  configured Indian language and speak it via ElevenLabs". Rebindable in
  NVDA Menu > Preferences > Input gestures > ElevenLabs TTS.
"""

import threading

import addonHandler
import api
import config
import globalPluginHandler
import gui
import synthDriverHandler
import textInfos
import ui
import wx
from logHandler import log
from scriptHandler import script

from .settings import ElevenLabsSettingsPanel, ensureConfigSpec, CONFIG_SECTION

addonHandler.initTranslation()


def _get_selected_text() -> str:
    """Return the currently selected text in any focused app, or ''.

    Tries the tree interceptor first (browse mode in browsers / Office),
    falls back to the focus object's caret object (text fields).
    """
    try:
        obj = api.getFocusObject()
        treeInterceptor = obj.treeInterceptor
        if treeInterceptor is not None and getattr(treeInterceptor, "passThrough", False) is False:
            obj = treeInterceptor
        info = obj.makeTextInfo(textInfos.POSITION_SELECTION)
        if info.isCollapsed:
            return ""
        return info.text or ""
    except (RuntimeError, NotImplementedError, AttributeError, LookupError):
        return ""


class GlobalPlugin(globalPluginHandler.GlobalPlugin):

    # Translators: name of the gesture category in NVDA's Input Gestures dialog.
    scriptCategory = _("ElevenLabs TTS")

    def __init__(self):
        super().__init__()
        ensureConfigSpec()
        try:
            gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(
                ElevenLabsSettingsPanel
            )
            log.info("ElevenLabs: settings panel registered.")
        except Exception as e:
            log.error(
                f"ElevenLabs: failed to register settings panel: {type(e).__name__}: {e}"
            )

    def terminate(self):
        try:
            gui.settingsDialogs.NVDASettingsDialog.categoryClasses.remove(
                ElevenLabsSettingsPanel
            )
        except Exception:
            pass

    @script(
        # Translators: announced by NVDA in the Input Gestures dialog.
        description=_(
            "Translate the currently selected text into the configured "
            "Indian language and speak it via ElevenLabs"
        ),
        gesture="kb:NVDA+shift+t",
        category=_("ElevenLabs TTS"),
    )
    def script_translateSelection(self, gesture):
        text = _get_selected_text()
        if not text.strip():
            # Translators: announced when the gesture fires with no selection.
            ui.message(_("No text selected"))
            return

        ensureConfigSpec()
        target_lang = (config.conf[CONFIG_SECTION].get("translationLanguage") or "ta").strip()
        if not target_lang:
            target_lang = "ta"

        synth = synthDriverHandler.getSynth()
        if synth is None or not hasattr(synth, "speakTranslation"):
            ui.message(_(
                "Switch to the ElevenLabs synthesizer to use translation"
            ))
            return

        # Translators: short status announcement before the network call.
        ui.message(_("Translating..."))

        def worker():
            try:
                from synthDrivers.elevenlabs import translate_text, TranslationError
                translated = translate_text(text, target_lang)
            except TranslationError as e:
                log.warning(f"ElevenLabs translate: {e}")
                wx.CallAfter(ui.message, _("Translation failed: ") + str(e))
                return
            except Exception as e:
                log.error(f"ElevenLabs translate: {type(e).__name__}: {e}")
                wx.CallAfter(ui.message, _("Translation failed: ") + str(e))
                return

            if not translated.strip():
                wx.CallAfter(ui.message, _("Translation returned empty result"))
                return

            try:
                synth.speakTranslation(translated, target_lang)
            except Exception as e:
                log.error(f"ElevenLabs speakTranslation: {type(e).__name__}: {e}")
                wx.CallAfter(ui.message, _("Could not speak translation"))

        threading.Thread(target=worker, daemon=True).start()
