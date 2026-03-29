# -*- coding: UTF-8 -*-

def _(arg):
    return arg

addon_info = {
    "addon_name": "Indian_Sarvam_AI_TTS",  # Internal name
    "addon_summary": _("Indian Sarvam AI TTS"),
    "addon_description": _(
        "Indian Sarvam AI TTS is an NVDA synthesizer add-on that enables high quality "
        "cloud-based speech synthesis using the Sarvam AI Text-to-Speech API.\n\n"

        "🔊 Features\n"
        "• Natural sounding neural voices\n"
        "• Multiple Indian language voices\n"
        "• Cloud powered speech synthesis\n"
        "• Adjustable speech rate\n"
        "• API key configuration through NVDA settings\n\n"

        "🌐 Supported Languages\n"
        "supports major Indian languages including Hindi, Bengali, Tamil, Telugu, Gujarati, Kannada, Malayalam, Marathi, Punjabi, Odia and English.\n\n"

        "⚙ Setup\n"
        "1. Open NVDA Settings.\n"
        "2. Navigate to 'Sarvam AI Speech'.\n"
        "3. Paste your Sarvam API key.\n"
        "4. Select 'Indian Sarvam AI TTS' from NVDA synthesizer list.\n\n"

        "To obtain an API key visit the Sarvam AI dashboard."
    ),
    "addon_version": "1.0",
    "addon_author": "Vision-Aid Hackathon Team 3 Barrier Breakers (Ramesh, Pavankumar, Vignesh, Tamilselvam)",
    "addon_url": "https://github.com/bhargav-vision-aid/VA-HFI2026-Team3/",
    "addon_sourceURL": "https://github.com/bhargav-vision-aid/VA-HFI2026-Team3/",
    "addon_docFileName": "readme.html",
    "addon_minimumNVDAVersion": "2025.1",
    "addon_lastTestedNVDAVersion": "2025.1.2",
    "addon_updateChannel": None,
    "addon_license": "GPL",
    "addon_licenseURL": "https://www.gnu.org/licenses/gpl-2.0.html",
}

# Python files included in build
pythonSources = [
    "addon/synthDrivers/*.py",
    "addon/globalPlugins/*.py",
]

# Files used for translation extraction
i18nSources = pythonSources + ["buildVars.py"]

excludedFiles = []

baseLanguage = "en"

markdownExtensions = []

brailleTables = {}

symbolDictionaries = {}