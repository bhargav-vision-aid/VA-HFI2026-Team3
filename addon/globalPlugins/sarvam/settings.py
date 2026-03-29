# -*- coding: utf-8 -*-

import wx
import webbrowser
import gui
import config
import addonHandler

addonHandler.initTranslation()

LANG_OPTIONS = [
    ("English", "en-IN"),
    ("Hindi", "hi-IN"),
    ("Marathi", "mr-IN"),
    ("Bengali", "bn-IN"),
    ("Tamil", "ta-IN"),
    ("Telugu", "te-IN"),
    ("Gujarati", "gu-IN"),
    ("Kannada", "kn-IN"),
    ("Malayalam", "ml-IN"),
    ("Punjabi", "pa-IN"),
    ("Odia", "od-IN"),
]


class SarvamSettingsPanel(gui.settingsDialogs.SettingsPanel):

    title = "Sarvam AI Speech"

    def makeSettings(self, settingsSizer):

        # ✅ SAFE CONFIG INIT
        if "sarvamAI" not in config.conf:
            config.conf["sarvamAI"] = {}

        conf = config.conf["sarvamAI"]   # ✅ FIRST define

        if "translateEnabled" not in conf:
            conf["translateEnabled"] = False

        # ---------------- API KEY ----------------
        apiLabel = wx.StaticText(self, label="Sarvam API Key:")
        settingsSizer.Add(apiLabel, flag=wx.TOP | wx.LEFT, border=10)

        self.apiKeyCtrl = wx.TextCtrl(
            self,
            value=conf.get("apiKey", ""),
            style=wx.TE_PASSWORD
        )
        settingsSizer.Add(self.apiKeyCtrl, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        btn = wx.Button(self, label="Get API Key")
        btn.Bind(wx.EVT_BUTTON, lambda evt: webbrowser.open("https://dashboard.sarvam.ai"))
        settingsSizer.Add(btn, flag=wx.LEFT | wx.TOP, border=10)

        # ---------------- SPACE ----------------
        settingsSizer.Add(wx.StaticText(self, label=" "), flag=wx.TOP, border=5)

        # ---------------- TRANSLATION ----------------
        title = wx.StaticText(self, label="Translation (Experimental)")
        settingsSizer.Add(title, flag=wx.TOP | wx.LEFT, border=10)

        self.translateCheckbox = wx.CheckBox(self, label="Enable Translation")
        self.translateCheckbox.SetValue(
            str(conf.get("translateEnabled", "False")).lower() == "true"
        )
        settingsSizer.Add(self.translateCheckbox, flag=wx.LEFT | wx.TOP, border=10)

        # Language dropdown
        langLabel = wx.StaticText(self, label="Target Language:")
        settingsSizer.Add(langLabel, flag=wx.LEFT | wx.TOP, border=10)

        self.langChoice = wx.ComboBox(
            self,
            choices=[name for name, _ in LANG_OPTIONS],
            style=wx.CB_READONLY
        )

        currentLang = conf.get("targetLang", "en-IN")

        index = 0
        for i, (_, code) in enumerate(LANG_OPTIONS):
            if code == currentLang:
                index = i
                break

        self.langChoice.SetSelection(index)

        settingsSizer.Add(self.langChoice, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, border=10)

    def onSave(self):

        if "sarvamAI" not in config.conf:
            config.conf["sarvamAI"] = {}

        conf = config.conf["sarvamAI"]

        conf["apiKey"] = self.apiKeyCtrl.GetValue().strip()
        conf["translateEnabled"] = self.translateCheckbox.GetValue()

        idx = self.langChoice.GetSelection()
        conf["targetLang"] = LANG_OPTIONS[idx][1]

        config.conf.save()