import os
import platform
import queue
import sys
import threading

import nvwave
import synthDriverHandler
from logHandler import log
from synthDriverHandler import synthDoneSpeaking
try:
    # NVDA newer API (e.g. SynthSetting)
    from synthDriverHandler import SynthSetting, NumericSynthSetting, BooleanSynthSetting
except ImportError:
    # NVDA older API (e.g. DriverSetting)
    try:
        from synthDriverHandler import (
            DriverSetting as _DriverSetting,
            NumericDriverSetting as _NumericDriverSetting,
            BooleanDriverSetting as _BooleanDriverSetting,
        )
    except ImportError:
        from autoSettingsUtils.driverSetting import (  # type: ignore
            DriverSetting as _DriverSetting,
            NumericDriverSetting as _NumericDriverSetting,
            BooleanDriverSetting as _BooleanDriverSetting,
        )

    class SynthSetting(_DriverSetting):
        def __init__(self, id: str, displayName: str, *, defaultVal: str = "", useConfig: bool = True):
            super().__init__(
                id=id,
                displayNameWithAccelerator=displayName,
                availableInSettingsRing=True,
                defaultVal=defaultVal,
                displayName=displayName,
                useConfig=useConfig,
            )

    class NumericSynthSetting(_NumericDriverSetting):
        def __init__(
            self,
            id: str,
            displayName: str,
            *,
            defaultVal: int = 50,
            minVal: int = 0,
            maxVal: int = 100,
            minStep: int = 1,
            normalStep: int = 5,
            largeStep: int = 10,
            useConfig: bool = True,
        ):
            super().__init__(
                id=id,
                displayNameWithAccelerator=displayName,
                availableInSettingsRing=True,
                defaultVal=defaultVal,
                minVal=minVal,
                maxVal=maxVal,
                minStep=minStep,
                normalStep=normalStep,
                largeStep=largeStep,
                displayName=displayName,
                useConfig=useConfig,
            )

    class BooleanSynthSetting(_BooleanDriverSetting):
        def __init__(self, id: str, displayName: str, *, defaultVal: bool = False, useConfig: bool = True):
            super().__init__(
                id=id,
                displayNameWithAccelerator=displayName,
                availableInSettingsRing=True,
                displayName=displayName,
                defaultVal=defaultVal,
                useConfig=useConfig,
            )

_STOP = object()

# --- PATH SETUP ---
baseDir = os.path.dirname(__file__)
vendorPath = os.path.join(baseDir, "vendor")
_PY_ARCH = platform.architecture()[0]
_VENDOR_HINT = ""
try:
    if os.path.isdir(vendorPath):
        vendor_pyds = [n.lower() for n in os.listdir(vendorPath) if n.lower().endswith(".pyd")]
        has_win32 = any("win32" in n for n in vendor_pyds)
        has_amd64 = any(("amd64" in n) or ("win_amd64" in n) for n in vendor_pyds)
        if _PY_ARCH == "64bit" and has_win32 and not has_amd64:
            _VENDOR_HINT = (
                "This NVDA/Python appears to be 64-bit, but the bundled vendor libraries look 32-bit (win32). "
                "Use 64-bit wheels in vendor/, or run a 32-bit NVDA build."
            )
        elif _PY_ARCH == "32bit" and has_amd64 and not has_win32:
            _VENDOR_HINT = (
                "This NVDA/Python appears to be 32-bit, but the bundled vendor libraries look 64-bit (amd64). "
                "Use 32-bit wheels in vendor/, or run a 64-bit NVDA build."
            )
except Exception:
    pass

if os.path.isdir(vendorPath) and vendorPath not in sys.path:
    sys.path.insert(0, vendorPath)

# --- IMPORTS ---
IMPORT_ERROR = ""
try:
    from elevenlabs.client import ElevenLabs
    from elevenlabs.core.api_error import ApiError

    IMPORT_SUCCESS = True
except Exception as e:
    IMPORT_ERROR = f"{type(e).__name__}: {e}"
    log.error(f"ElevenLabs: Import failed: {IMPORT_ERROR}")
    if _VENDOR_HINT:
        log.error(f"ElevenLabs: Vendor hint: {_VENDOR_HINT}")
    IMPORT_SUCCESS = False

_PCM_FORMAT_SAMPLE_RATES = {
    "pcm_44100": 44100,
    "pcm_22050": 22050,
    "pcm_16000": 16000,
}

# -------------------------------------------------------------------
# FREE-TIER VOICES (no paid subscription required)
# Includes voices with Indian/South Asian accent support.
# Voice IDs verified as available on free tier as of 2024-2025.
# -------------------------------------------------------------------
VOICE_LIST = [
    # Indian-accented voices (free tier)
    ("Riya - Indian Female",        "XB0fDUnXU5powFXDhCwa"),  # Indian English female
    ("Neel - Indian Male",          "IKne3meq5aSn9XLyUdCD"),  # Indian English male
    # Standard free-tier voices
    ("Rachel",                      "21m00Tcm4TlvDq8ikWAM"),
    ("Domi",                        "AZnzlk1XvdvUeBnXmlld"),
    ("Bella",                       "EXAVITQu4vr4xnSDxMaL"),
    ("Antoni",                      "ErXwobaYiN019PkySvjV"),
    ("Elli",                        "MF3mGyEYCl7XYWbV9V6O"),
    ("Josh",                        "TxGEqnHWrfWFTfGW9XjX"),
    ("Arnold",                      "VR6AewLTigWG4xSOukaG"),
    ("Adam",                        "pNInz6obpgDQGcFmaJgB"),
    ("Sam",                         "yoZ06aMxZJJ28mfd3POQ"),
]

# Build lookup: display-name → voice_id
_VOICE_NAME_TO_ID = {name: vid for name, vid in VOICE_LIST}
_VOICE_ID_TO_NAME = {vid: name for name, vid in VOICE_LIST}
_VOICE_NAMES      = [name for name, _ in VOICE_LIST]


def _load_elevenlabs_api_key() -> str:
    api_key = (os.getenv("ELEVENLABS_API_KEY") or "").strip()
    if api_key:
        return api_key

    key_path = os.path.join(baseDir, "elevenlabs_api_key.txt")
    try:
        with open(key_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _is_output_format_not_allowed(err: Exception) -> bool:
    api_error_cls = globals().get("ApiError")
    if api_error_cls is None:
        return False
    if not isinstance(err, api_error_cls):
        return False
    body = getattr(err, "body", None)
    if not isinstance(body, dict):
        return False
    detail = body.get("detail")
    if not isinstance(detail, dict):
        return False
    return detail.get("status") == "output_format_not_allowed"


# -------------------------------------------------------------------
# Expand a single letter to a speakable word so ElevenLabs doesn't
# skip it.  Falls back to spelling it out with spaces so the TTS
# engine sees a real word rather than a bare character.
# -------------------------------------------------------------------
_LETTER_NAMES = {
    'a': 'ay', 'b': 'bee', 'c': 'see', 'd': 'dee', 'e': 'ee',
    'f': 'ef', 'g': 'jee', 'h': 'aitch', 'i': 'eye', 'j': 'jay',
    'k': 'kay', 'l': 'el', 'm': 'em', 'n': 'en', 'o': 'oh',
    'p': 'pee', 'q': 'queue', 'r': 'ar', 's': 'ess', 't': 'tee',
    'u': 'you', 'v': 'vee', 'w': 'double-you', 'x': 'ex',
    'y': 'why', 'z': 'zee',
    '0': 'zero', '1': 'one', '2': 'two', '3': 'three', '4': 'four',
    '5': 'five', '6': 'six', '7': 'seven', '8': 'eight', '9': 'nine',
    '.': 'dot', ',': 'comma', '!': 'exclamation', '?': 'question mark',
    ':': 'colon', ';': 'semicolon', '-': 'dash', '_': 'underscore',
    '@': 'at', '#': 'hash', '$': 'dollar', '%': 'percent',
    '&': 'and', '*': 'star', '(': 'open bracket', ')': 'close bracket',
    '/': 'slash', '\\': 'backslash', '+': 'plus', '=': 'equals',
    '<': 'less than', '>': 'greater than', '[': 'open square bracket',
    ']': 'close square bracket', '{': 'open brace', '}': 'close brace',
    '"': 'quote', "'": 'apostrophe', '`': 'backtick', '~': 'tilde',
    '^': 'caret', '|': 'pipe',
}

def _expand_single_char(ch: str) -> str:
    """Return a speakable string for a single character."""
    return _LETTER_NAMES.get(ch.lower(), ch)


# -------------------------------------------------------------------
# Map speech-rate (0-100) to ElevenLabs stability / speed params.
# ElevenLabs doesn't have a direct "rate" knob on the streaming API,
# so we use voice_settings stability + style as a proxy:
#   rate=50  → normal  (stability=0.5, similarity_boost=0.75, style=0.0)
#   rate<50  → slower  (higher stability)
#   rate>50  → faster  (lower stability, small style push)
# -------------------------------------------------------------------
def _rate_to_voice_settings(rate: int) -> dict:
    rate = max(0, min(100, rate))
    # stability: 0.75 at rate=0, 0.5 at rate=50, 0.25 at rate=100
    stability = 0.75 - (rate / 100.0) * 0.50
    # style: 0.0 at rate<=50, up to 0.3 at rate=100 (adds energy / speed feel)
    style = max(0.0, (rate - 50) / 50.0 * 0.30)
    return {
        "stability": round(stability, 2),
        "similarity_boost": 0.75,
        "style": round(style, 2),
        "use_speaker_boost": True,
    }


class SynthDriver(synthDriverHandler.SynthDriver):
    name = "elevenlabs"
    description = "ElevenLabs Streaming AI"

    # ----------------------------------------------------------------
    # NVDA settings exposed in the synth settings ring (NVDA+Ctrl+←/→)
    # ----------------------------------------------------------------
    supportedSettings = (
        # Speech rate  0-100, default 50
        NumericSynthSetting("rate", "Rate", minVal=0, maxVal=100),
        # Voice selection
        SynthSetting("voice", "Voice"),
    )

    # NVDA needs these properties for the settings ring
    @property
    def rate(self) -> int:
        return self._rate

    @rate.setter
    def rate(self, value: int):
        self._rate = max(0, min(100, int(value)))

    @property
    def voice(self) -> str:
        return self._voice

    @voice.setter
    def voice(self, value: str):
        # NVDA may provide the selected voice as:
        # - the VoiceInfo id (recommended): the ElevenLabs voice_id
        # - a display name (legacy / custom UI)
        voice_id = None
        if value in _VOICE_NAME_TO_ID:
            voice_id = _VOICE_NAME_TO_ID[value]
        elif value in _VOICE_ID_TO_NAME:
            voice_id = value
        if not voice_id:
            log.warning(f"ElevenLabs: Unknown voice '{value}', keeping current.")
            return
        self._voice = voice_id
        self._voice_name = _VOICE_ID_TO_NAME.get(voice_id, voice_id)
        self.voice_id = voice_id

    def getVoices(self):
        """Return the list of available voices for the NVDA voice selector."""
        return list(self._getAvailableVoices().values())

    def _getAvailableVoices(self):
        from synthDriverHandler import VoiceInfo

        voices = {}
        for display_name, voice_id in VOICE_LIST:
            try:
                voices[voice_id] = VoiceInfo(voice_id, display_name, "en")
            except TypeError:
                voices[voice_id] = VoiceInfo(voice_id, display_name)
        return voices

    # ----------------------------------------------------------------

    @classmethod
    def check(cls):
        return IMPORT_SUCCESS

    def _init_client(self) -> bool:
        if not IMPORT_SUCCESS:
            if IMPORT_ERROR:
                log.error(f"ElevenLabs: Cannot initialize client because imports failed: {IMPORT_ERROR}")
            if _VENDOR_HINT:
                log.error(f"ElevenLabs: {_VENDOR_HINT}")
            return False

        api_key = _load_elevenlabs_api_key()
        if not api_key:
            log.error(
                "ElevenLabs: API key missing. Set ELEVENLABS_API_KEY or put the key in elevenlabs_api_key.txt next to elevenlabs.py"
            )
            return False

        try:
            self.client = ElevenLabs(api_key=api_key)
            log.info("ElevenLabs: Client initialized successfully")
            return True
        except Exception as e:
            self.client = None
            log.error(f"ElevenLabs: Client init failed: {type(e).__name__}: {e}")
            return False

    def __init__(self):
        super().__init__()

        # Default voice: first Indian voice in the list
        self._voice_name = _VOICE_NAMES[0]          # "Riya - Indian Female"
        self._voice      = _VOICE_NAME_TO_ID[self._voice_name]
        self.voice_id    = self._voice
        self.model_id    = "eleven_turbo_v2_5"
        self.output_format = (os.getenv("ELEVENLABS_OUTPUT_FORMAT") or "pcm_16000").strip()
        self._rate       = 50                        # neutral default

        self.client  = None
        self._queue  = queue.Queue()
        self._cancelToken = 0
        self._lock   = threading.Lock()
        self._player = None
        self._worker = threading.Thread(target=self._workerLoop, daemon=True)
        self._worker.start()

        self._init_client()

    def _getSampleRate(self, output_format: str) -> int:
        return _PCM_FORMAT_SAMPLE_RATES.get(output_format, 22050)

    def _ensurePlayer(self, sample_rate: int):
        if self._player is None:
            self._player = nvwave.WavePlayer(
                channels=1,
                samplesPerSec=sample_rate,
                bitsPerSample=16,
            )

    def _streamAndPlay(self, text: str, token: int):
        if not self.client and not self._init_client():
            log.error("ElevenLabs: No client instance found (API key missing or init failed).")
            return

        voice_settings = _rate_to_voice_settings(self._rate)

        fmt_try = self.output_format or "pcm_22050"
        for attempt_fmt in (fmt_try, "pcm_16000"):
            sample_rate = self._getSampleRate(attempt_fmt)
            try:
                audio_stream = self.client.text_to_speech.stream(
                    voice_id=self.voice_id,
                    text=text,
                    model_id=self.model_id,
                    output_format=attempt_fmt,
                    optimize_streaming_latency="4",  # 0-4 (4 = fastest)
                    seed=42,                          # faster cache retrieval
                    voice_settings=voice_settings,
                )

                with self._lock:
                    if token != self._cancelToken:
                        return
                    if self._player:
                        self._player.stop()
                        self._player = None
                    self._ensurePlayer(sample_rate)

                for chunk in audio_stream:
                    if not chunk:
                        continue
                    with self._lock:
                        if token != self._cancelToken:
                            return
                        player = self._player
                    if player is None:
                        return
                    if len(chunk) % 2 != 0:
                        chunk += b"\x00"
                    player.feed(chunk)

                synthDoneSpeaking.notify(synth=self)
                return
            except Exception as e:
                if attempt_fmt != "pcm_16000" and _is_output_format_not_allowed(e):
                    log.warning(f"ElevenLabs: output_format '{attempt_fmt}' not allowed; retrying with pcm_16000")
                    continue
                log.error(f"ElevenLabs: Streaming error ({attempt_fmt}): {type(e).__name__}: {e}")
                return

    def _workerLoop(self):
        while True:
            item = self._queue.get()
            try:
                if item is _STOP:
                    return
                text, token = item
                self._streamAndPlay(text, token)
            except Exception as e:
                log.error(f"ElevenLabs: worker failure: {type(e).__name__}: {e}")
            finally:
                self._queue.task_done()

    def speak(self, speechSequence):
        parts = []
        for item in speechSequence:
            if isinstance(item, str):
                parts.append(item)

        text = "".join(parts).strip()
        if not text:
            return

        # --- FIX: letter-by-letter navigation ---
        # When NVDA reads char-by-char (arrow keys / review cursor),
        # it sends a single character.  ElevenLabs silently skips
        # one-character inputs.  Expand them to a speakable word.
        if len(text) == 1:
            text = _expand_single_char(text)

        with self._lock:
            self._cancelToken += 1
            token = self._cancelToken
            if self._player:
                self._player.stop()
                self._player = None

        self._queue.put((text, token))

    def cancel(self):
        with self._lock:
            self._cancelToken += 1
            if self._player:
                self._player.stop()
                self._player = None

    def pause(self, switch):
        pass

    def terminate(self):
        try:
            with self._lock:
                self._cancelToken += 1
                if self._player:
                    self._player.stop()
                    self._player = None
            self._queue.put(_STOP)
        except Exception:
            pass
