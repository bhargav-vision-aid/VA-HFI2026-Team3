import addonHandler
import gui
import wx
import config
from logHandler import log

addonHandler.initTranslation()

# ---------------- INSTALL ----------------
def onInstall():

    def showMessage():
        gui.messageBox(
            "Sarvam AI TTS installed successfully.\n\n"
            "Go to NVDA Settings → Sarvam AI Speech and add your API key.",
            "Sarvam AI",
            wx.OK | wx.ICON_INFORMATION
        )

    wx.CallAfter(showMessage)


# ---------------- UNINSTALL ----------------
def onUninstall():

    CONFIG_DOMAIN = "sarvamAI"

    try:
        # ✅ Remove config spec (if any)
        if CONFIG_DOMAIN in config.conf.spec:
            del config.conf.spec[CONFIG_DOMAIN]

        # ✅ Remove from ALL profiles (VERY IMPORTANT)
        for profile in config.conf.profiles:
            if CONFIG_DOMAIN in profile:
                del profile[CONFIG_DOMAIN]
                profile.save()

        # ✅ Final save
        config.save()

        log.info("Sarvam config removed successfully")

    except Exception as e:
        log.error(f"Sarvam uninstall cleanup failed: {e}")