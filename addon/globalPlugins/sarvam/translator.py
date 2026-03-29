from sarvamai import SarvamAI
from logHandler import log
import config

class SarvamTranslator:

    def __init__(self):

        key = config.conf.get("sarvamAI", {}).get("apiKey", "")

        if not key:
            raise RuntimeError("Sarvam API key not configured")

        self.client = SarvamAI(api_subscription_key=key.strip())

    def translate(self, text, target_lang="en-IN"):

        if not text.strip():
            return text

        try:
            response = self.client.text.translate(
                input=text,
                source_language_code="auto",
                target_language_code=target_lang
            )

            return getattr(response, "translated_text", str(response))

        except Exception as e:
            log.error(f"Translation error: {e}")
            return text