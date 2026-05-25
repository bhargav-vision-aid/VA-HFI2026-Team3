Locale folder
=============

Per-language translations of user-facing strings live here, one
sub-folder per language code:

  locale/ta/LC_MESSAGES/nvda.po   (Tamil)
  locale/hi/LC_MESSAGES/nvda.po   (Hindi)
  locale/en/...                   (English is the source; no .po needed)

The settings panel and global plugin wrap all user-facing strings in
addonHandler.initTranslation()'s `_()` function. NVDA picks the right
.po based on the user's NVDA language at startup.

To produce a fresh `nvda.pot` template:

    py -3 -m babel extract \
        -o locale/nvda.pot \
        synthDrivers/elevenlabs.py \
        globalPlugins/elevenlabsTTS/

Then per language:

    msginit -i locale/nvda.pot -o locale/<lang>/LC_MESSAGES/nvda.po -l <lang>
    # ... translate ...
    msgfmt locale/<lang>/LC_MESSAGES/nvda.po -o locale/<lang>/LC_MESSAGES/nvda.mo

NVDA only reads the compiled `.mo` files at runtime — keep both `.po`
(source) and `.mo` (compiled) committed.

Empty `.po` placeholders are kept in the Tamil and Hindi folders so
contributors can see where to start.
