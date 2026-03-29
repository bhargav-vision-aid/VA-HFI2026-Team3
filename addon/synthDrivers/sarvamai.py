import os
import sys

PLUGIN_DIR = os.path.dirname(__file__)
LIB_DIR = os.path.join(PLUGIN_DIR, "lib")

if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

# force our newer typing_extensions
if "typing_extensions" in sys.modules:
    del sys.modules["typing_extensions"]

import asyncio
import base64
import queue
import threading
import time
import config
import nvwave
import synthDriverHandler

import languageHandler
from speech.commands import LangChangeCommand, IndexCommand
from logHandler import log
from synthDriverHandler import VoiceInfo, synthDoneSpeaking, synthIndexReached
#from globalPlugins.sarvam.translator import SarvamTranslator
# ------------------------------------------------------------------
# Sarvam SDK
# ------------------------------------------------------------------


from sarvamai import AsyncSarvamAI, AudioOutput, EventResponse

MODEL = "bulbul:v3"

# ------------------------------------------------------------------
class SynthDriver(synthDriverHandler.SynthDriver):

    name = "sarvamai"
    supportedLanguages = None
    supportedCommands = {IndexCommand}
    supportedNotifications = {synthDoneSpeaking, synthIndexReached}
    description = "Indian Sarvam AI TTS"
    

    supportedSettings = (
        synthDriverHandler.SynthDriver.VoiceSetting(),
        synthDriverHandler.SynthDriver.RateSetting(),
    )

    @classmethod
    def check(cls):
        return True

    # ------------------------------------------------------------------

    def __init__(self):

        super().__init__()

        self._voice = "shubh"
        self.availableVoices = self._getAvailableVoices()
        self._rate = 50
        self._currentLang = "en"

        self._queue = queue.Queue()



        self._cancelToken = 0
        self._lock = threading.Lock()

        self._player = None
        self._streamLock = asyncio.Lock()

        # speaking state
        self._speaking = False

        # text buffering
        self._buffer = ""
        self._bufferTime = 0
        self._bufferDelay = 0.03

        # asyncio loop for streaming
        self._loop = asyncio.new_event_loop()

        self._worker = threading.Thread(
            target=self._workerLoop,
            daemon=True,
        )

        self._worker.start()

        log.info("Sarvam streaming synth initialized")

    # ------------------------------------------------------------------

    def _workerLoop(self):

        asyncio.set_event_loop(self._loop)

        self._loop.run_until_complete(self._asyncWorker())

    # ------------------------------------------------------------------

    async def _asyncWorker(self):

        api_key = self._getApiKey()

        client = AsyncSarvamAI(api_subscription_key=api_key)

        while True:

            text, token = await self._loop.run_in_executor(
                None,
                self._queue.get,
            )

            try:
                await self._streamSpeech(client, text, token)

            except Exception as e:
                log.error(f"Sarvam stream error: {e}")

            finally:
                self._queue.task_done()

    # ------------------------------------------------------------------

    async def _streamSpeech(self, client, text, token):

        async with self._streamLock:

            text = text.strip()



            #if not text or len(text) < 1:
            if not text or len(text.strip()) == 0:
                return

            # --- Translation Hook ---
            try:
                conf = config.conf.get("sarvamAI", {})   # ✅ REQUIRED LINE

                enabled = str(conf.get("translateEnabled", "False")).lower() == "true"

                if enabled:
                    targetLang = conf.get("targetLang", "en-IN")

                    from globalPlugins.sarvam.translator import SarvamTranslator
                    translator = SarvamTranslator()

                    text = translator.translate(text, targetLang)

                    if not text or len(text.strip()) == 0:
                        return

            except Exception as e:
                log.warning(f"Translation hook failed: {e}")
            # Only skip extremely useless noise (rare case)
            if len(text.strip()) == 1 and not text.strip().isalnum():
                return

            log.info(f"Sarvam sending text: {text}")
            start_time = time.time()

            try:
                async with client.text_to_speech_streaming.connect(
                    model=MODEL,
                    send_completion_event=True,
                ) as ws:

                    await ws.configure(
                        speaker=self._voice,
                        target_language_code=self._getLanguageCode(),
                        pace=self._getPace(),
                        min_buffer_size=30,
                        max_chunk_length=90,
                        speech_sample_rate="24000",
                        output_audio_codec="linear16",
                    )

                    await ws.convert(text)
                    await ws.flush()

                    try:
                        async for message in ws:

                            if token != self._cancelToken:
                                log.info("Sarvam stream cancelled (fast exit)")
                                break

                            if isinstance(message, AudioOutput):
                                audio_chunk = base64.b64decode(message.data.audio)

                                if token != self._cancelToken:
                                    break

                                if self._player is None:
                                    self._player = nvwave.WavePlayer(
                                        channels=1,
                                        samplesPerSec=24000,
                                        bitsPerSample=16,
                                    )

                                self._player.feed(audio_chunk)

                            elif isinstance(message, EventResponse):

                                if message.data.event_type == "final":
                                    log.info("Sarvam stream completed")
                                    synthDoneSpeaking.notify(synth=self)
                                    break

                    except asyncio.TimeoutError:
                        log.warning("Sarvam stream timeout")

            except Exception as e:
                log.error(f"Sarvam websocket error: {e}")
    # ------------------------------------------------------------------


    def speak(self, speechSequence):

        buffer = []

        with self._lock:
            token = self._cancelToken

        for item in speechSequence:

            if isinstance(item, LangChangeCommand):

                lang = item.lang.split("_")[0]

                if lang == "any":
                    # 🔥 reset to default (important)
                    self._currentLang = "en"
                else:
                    self._currentLang = lang

            elif isinstance(item, str):
                buffer.append(item)

            elif isinstance(item, IndexCommand):

                synthIndexReached.notify(
                    synth=self,
                    index=item.index
                )

        text = "".join(buffer).strip()

        # 🔥 safer limit (avoid cutting too early speech)
        if len(text) > 250 and " " in text:
            text = text[:250].rsplit(" ", 1)[0]
        log.info(f"FINAL TEXT SENT: {text}")

        if text:
            with self._lock:
                token = self._cancelToken

            # ✅ ALWAYS enqueue first (critical fix)
            self._queue.put((text, token))

            # ✅ THEN cancel old audio (not before)
            if self._player is not None:
                self.cancel()
    # ------------------------------------------------------------------

    def cancel(self):

        with self._lock:

            self._cancelToken += 1

            # ✅ STOP audio FIRST (correct order)
            if self._player:
                try:
                    self._player.stop()
                except Exception as e:
                    log.warning(f"Sarvam player stop error: {e}")

            # ✅ THEN reset
            self._player = None

            # 🧹 clear pending queue
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                except:
                    break

        self._speaking = False
        self._buffer = ""

        log.info("Sarvam cancel issued")

    # ------------------------------------------------------------------

    def _getLanguageCode(self):

        lang = getattr(self, "_currentLang", "en")

        LANG_MAP = {
            "en": "en-IN",
            "hi": "hi-IN",
            "mr": "mr-IN",
            "bn": "bn-IN",
            "ta": "ta-IN",
            "te": "te-IN",
            "kn": "kn-IN",
            "ml": "ml-IN",
            "gu": "gu-IN",
            "pa": "pa-IN",
            "or": "od-IN",
        }

        return LANG_MAP.get(lang, "en-IN")

    # ------------------------------------------------------------------

    def _getPace(self):

        return max(
            0.5,
            min(
                2.0,
                0.5 + (self._rate / 100.0) * 1.5,
            ),
        )

    # ------------------------------------------------------------------

    def _getApiKey(self):

        key = config.conf.get("sarvamAI", {}).get("apiKey", "")

        if key:
            return key.strip()

        raise RuntimeError("Sarvam API key not configured")

    # ------------------------------------------------------------------

    def _getAvailableVoices(self):

        return {

            "shubh": VoiceInfo(
                "shubh",
                "Shubh (Male)",
                "en",
            ),

            "rahul": VoiceInfo(
                "rahul",
                "Rahul (Male)",
                "en",
            ),

            "kabir": VoiceInfo(
                "kabir",
                "Kabir (Male)",
                "en",
            ),

            "ritu": VoiceInfo(
                "ritu",
                "Ritu (Female)",
                "en",
            ),

            "priya": VoiceInfo(
                "priya",
                "Priya (Female)",
                "en",
            ),

            "neha": VoiceInfo(
                "neha",
                "Neha (Female)",
                "en",
            ),
        }

    # ------------------------------------------------------------------

    def _get_voice(self):
        return self._voice

    def _set_voice(self, value):

        voices = self._getAvailableVoices()

        if value not in voices:
            log.warning(f"Sarvam: invalid voice '{value}', using Shubh instead")
            value = "shubh"

        self._voice = value

    def _get_rate(self):
        return self._rate

    def _set_rate(self, value):
        self._rate = value
        

    def isSupported(self, language):
        return True