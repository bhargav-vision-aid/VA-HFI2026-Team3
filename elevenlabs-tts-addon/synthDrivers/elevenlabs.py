"""ElevenLabs streaming TTS driver for NVDA.

Talks directly to the ElevenLabs HTTP streaming endpoint using Python's
standard library so the add-on does not have to ship the official SDK
(which has very long auto-generated file paths that blow past Windows'
MAX_PATH during installation).
"""

import array
import hashlib
import http.client
import json
import os
import queue
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import config
import nvwave
import synthDriverHandler
from logHandler import log
from synthDriverHandler import synthDoneSpeaking

try:
    from synthDriverHandler import SynthSetting, NumericSynthSetting, BooleanSynthSetting
except ImportError:
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
_API_BASE = "https://api.elevenlabs.io"
_API_HOST = "api.elevenlabs.io"

# --- persistent HTTPS connection (per worker thread) ---
# urllib.request opens a fresh TCP+TLS connection on every call, which costs
# ~150-300 ms before any audio bytes can come back. Keeping a single
# HTTPSConnection alive across requests on the same thread eliminates that
# overhead on every cache miss after the first.
_tls = threading.local()


def _get_https_conn() -> http.client.HTTPSConnection:
    conn = getattr(_tls, "conn", None)
    if conn is None:
        conn = http.client.HTTPSConnection(
            _API_HOST,
            timeout=30,
            context=ssl.create_default_context(),
        )
        _tls.conn = conn
    return conn


def _reset_https_conn():
    """Force a fresh connection on next request — used after a transport error."""
    conn = getattr(_tls, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
    _tls.conn = None

_PCM_FORMAT_SAMPLE_RATES = {
    "pcm_44100": 44100,
    "pcm_22050": 22050,
    "pcm_16000": 16000,
}

# Hardcoded fallback used until the live /v1/voices fetch completes (or if
# it fails because the user has no API key set or no network). Kept small;
# the live fetch returns the user's actual library.
_FALLBACK_VOICE_LIST = [
    ("Rachel",  "21m00Tcm4TlvDq8ikWAM"),
    ("Domi",    "AZnzlk1XvdvUeBnXmlld"),
    ("Bella",   "EXAVITQu4vr4xnSDxMaL"),
    ("Antoni",  "ErXwobaYiN019PkySvjV"),
    ("Elli",    "MF3mGyEYCl7XYWbV9V6O"),
    ("Josh",    "TxGEqnHWrfWFTfGW9XjX"),
    ("Arnold",  "VR6AewLTigWG4xSOukaG"),
    ("Adam",    "pNInz6obpgDQGcFmaJgB"),
    ("Sam",     "yoZ06aMxZJJ28mfd3POQ"),
]

VOICE_LIST = list(_FALLBACK_VOICE_LIST)        # mutable; replaced by live fetch
_VOICE_NAME_TO_ID = {name: vid for name, vid in VOICE_LIST}
_VOICE_ID_TO_NAME = {vid: name for name, vid in VOICE_LIST}
_VOICE_NAMES      = [name for name, _ in VOICE_LIST]
_voice_list_lock  = threading.Lock()


def _rebuild_voice_indexes():
    global _VOICE_NAME_TO_ID, _VOICE_ID_TO_NAME, _VOICE_NAMES
    _VOICE_NAME_TO_ID = {name: vid for name, vid in VOICE_LIST}
    _VOICE_ID_TO_NAME = {vid: name for name, vid in VOICE_LIST}
    _VOICE_NAMES      = [name for name, _ in VOICE_LIST]


# --- model + language catalogues ---
MODEL_LIST = [
    ("Flash v2.5 (fastest, English only)", "eleven_flash_v2_5"),
    ("Turbo v2.5 (balanced, default)",     "eleven_turbo_v2_5"),
    ("Multilingual v2 (best, 29 languages)", "eleven_multilingual_v2"),
]
_MODEL_LABEL_TO_ID = {label: mid for label, mid in MODEL_LIST}
_MODEL_ID_TO_LABEL = {mid: label for label, mid in MODEL_LIST}


def _model_supports_language(model_id: str) -> bool:
    return "multilingual" in (model_id or "")


# Indian-subcontinent languages only. Hindi and Tamil are officially
# supported by eleven_multilingual_v2; the rest are best-effort — the model
# may handle them via transfer learning, but quality is not guaranteed by
# ElevenLabs. Labels carry that note so users see it in the dropdown.
LANGUAGE_LIST = [
    ("English (India)",         "en"),
    ("Hindi",                   "hi"),
    ("Tamil",                   "ta"),
    ("Bengali (experimental)",  "bn"),
    ("Telugu (experimental)",   "te"),
    ("Marathi (experimental)",  "mr"),
    ("Gujarati (experimental)", "gu"),
    ("Kannada (experimental)",  "kn"),
    ("Malayalam (experimental)","ml"),
    ("Punjabi (experimental)",  "pa"),
    ("Urdu (experimental)",     "ur"),
]
_LANG_LABEL_TO_CODE = {label: code for label, code in LANGUAGE_LIST}
_LANG_CODE_TO_LABEL = {code: label for label, code in LANGUAGE_LIST}

CONFIG_SECTION = "elevenlabsTTS"

# --- on-disk cache for short utterances (letter echo, char-by-char review) ---
# Network round-trip per keypress makes typed-character feedback unusable;
# we save the raw PCM bytes the first time each short text is spoken and
# replay them from disk on subsequent hits.
_CACHE_MAX_TEXT_LEN = 8  # only cache short snippets (letters, digits, short symbols)
_CACHE_DIR_NAME = "elevenlabsTTS_cache"
_CACHE_MAX_BYTES = 100 * 1024 * 1024  # 100 MB default ceiling
_cache_dir_cache = None  # memoized resolved path
_cache_eviction_lock = threading.Lock()


def _get_cache_dir():
    global _cache_dir_cache
    if _cache_dir_cache is not None:
        return _cache_dir_cache
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "nvda", _CACHE_DIR_NAME)
    try:
        os.makedirs(path, exist_ok=True)
        _cache_dir_cache = path
    except OSError:
        _cache_dir_cache = ""
    return _cache_dir_cache


def _cache_path(voice_id: str, text: str, output_format: str):
    cache_dir = _get_cache_dir()
    if not cache_dir:
        return None
    h = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    safe_voice = "".join(c for c in voice_id if c.isalnum())[:24] or "v"
    return os.path.join(cache_dir, f"{safe_voice}_{output_format}_{h}.pcm")


def _read_cache(path):
    if not path:
        return None
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def _write_cache(path, data: bytes):
    if not path or not data:
        return
    try:
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except OSError:
        return
    # Evict in the background-ish (cheap O(n) sweep) so the cache never
    # grows unbounded. Only runs if we just pushed over the configured ceiling.
    _evict_cache_if_needed()


def _cache_size_bytes() -> int:
    """Total bytes used by .pcm files in the cache dir."""
    cache_dir = _get_cache_dir()
    if not cache_dir:
        return 0
    total = 0
    try:
        with os.scandir(cache_dir) as it:
            for entry in it:
                if entry.is_file() and entry.name.endswith(".pcm"):
                    try:
                        total += entry.stat().st_size
                    except OSError:
                        pass
    except OSError:
        return 0
    return total


def _clear_cache() -> int:
    """Delete every .pcm cache file. Returns count of removed entries."""
    cache_dir = _get_cache_dir()
    if not cache_dir:
        return 0
    removed = 0
    try:
        with os.scandir(cache_dir) as it:
            for entry in it:
                if entry.is_file() and entry.name.endswith((".pcm", ".tmp")):
                    try:
                        os.remove(entry.path)
                        removed += 1
                    except OSError:
                        pass
    except OSError:
        pass
    return removed


def _evict_cache_if_needed(max_bytes: int = _CACHE_MAX_BYTES):
    """If the cache exceeds max_bytes, delete the oldest files until it doesn't.

    "Oldest" = least-recently-modified (mtime). Cheap and good enough for an
    LRU approximation since _write_cache touches mtime on every refresh.
    """
    cache_dir = _get_cache_dir()
    if not cache_dir:
        return
    if not _cache_eviction_lock.acquire(blocking=False):
        return  # another thread is already evicting; skip
    try:
        entries = []
        total = 0
        try:
            with os.scandir(cache_dir) as it:
                for entry in it:
                    if not entry.is_file() or not entry.name.endswith(".pcm"):
                        continue
                    try:
                        st = entry.stat()
                    except OSError:
                        continue
                    entries.append((st.st_mtime, st.st_size, entry.path))
                    total += st.st_size
        except OSError:
            return
        if total <= max_bytes:
            return
        entries.sort()  # oldest first
        for mtime, size, path in entries:
            if total <= max_bytes:
                break
            try:
                os.remove(path)
                total -= size
            except OSError:
                pass
    finally:
        _cache_eviction_lock.release()


def _load_elevenlabs_api_key() -> str:
    try:
        conf_key = (config.conf[CONFIG_SECTION].get("apiKey") or "").strip()
        if conf_key:
            return conf_key
    except Exception:
        pass

    api_key = (os.getenv("ELEVENLABS_API_KEY") or "").strip()
    if api_key:
        return api_key

    key_path = os.path.join(os.path.dirname(__file__), "elevenlabs_api_key.txt")
    try:
        with open(key_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


class ElevenLabsAPIError(Exception):
    def __init__(self, status_code: int, body):
        self.status_code = status_code
        self.body = body
        super().__init__(f"ElevenLabs API error {status_code}: {body!r}")


def _is_output_format_not_allowed(err: Exception) -> bool:
    if not isinstance(err, ElevenLabsAPIError):
        return False
    body = err.body
    if not isinstance(body, dict):
        return False
    detail = body.get("detail")
    if not isinstance(detail, dict):
        return False
    return detail.get("status") == "output_format_not_allowed"


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
    """Make sure a single character isn't silently dropped by ElevenLabs.

    For ASCII alphanumerics we just append a period: ElevenLabs pronounces
    "E." as the letter name "ee", "5." as "five", etc. — close to how a
    screen reader normally announces a character, and much shorter than
    spelling it out as "ee" or "five".
    """
    if not ch:
        return ch
    if len(ch) == 1 and ord(ch) < 128 and ch.isalnum():
        return f"{ch}."
    return _LETTER_NAMES.get(ch.lower(), ch)


def _rate_to_voice_settings(rate: int) -> dict:
    rate = max(0, min(100, rate))
    stability = 0.75 - (rate / 100.0) * 0.50
    style = max(0.0, (rate - 50) / 50.0 * 0.30)
    return {
        "stability": round(stability, 2),
        "similarity_boost": 0.75,
        "style": round(style, 2),
        "use_speaker_boost": True,
    }


def _apply_volume(pcm_bytes: bytes, volume: int) -> bytes:
    """Scale signed 16-bit mono PCM by volume 0..100 (pure-Python, no audioop)."""
    if volume >= 100 or not pcm_bytes:
        return pcm_bytes
    if volume <= 0:
        return b"\x00" * len(pcm_bytes)
    factor = max(0.0, min(1.0, volume / 100.0))
    samples = array.array('h')
    try:
        samples.frombytes(pcm_bytes)
    except ValueError:
        return pcm_bytes
    for i, s in enumerate(samples):
        samples[i] = int(s * factor)
    return samples.tobytes()


def _resample_mono16(pcm_bytes: bytes, in_rate: int, out_rate: int) -> bytes:
    """Linear-interpolation resample for signed 16-bit mono PCM.

    Used to fake a pitch knob: feeding the WavePlayer "more samples than
    were generated" effectively raises pitch (and shortens duration);
    fewer samples lowers pitch. Per-chunk only — tiny seam between
    chunks is inaudible on speech.
    """
    if in_rate == out_rate or not pcm_bytes:
        return pcm_bytes
    samples = array.array('h')
    try:
        samples.frombytes(pcm_bytes)
    except ValueError:
        return pcm_bytes
    n = len(samples)
    if n < 2:
        return pcm_bytes
    step = in_rate / out_rate
    out_n = max(1, int(n / step))
    out = array.array('h', [0] * out_n)
    for i in range(out_n):
        pos = i * step
        idx = int(pos)
        if idx + 1 >= n:
            out[i] = samples[n - 1]
            continue
        frac = pos - idx
        s1 = samples[idx]
        s2 = samples[idx + 1]
        v = int(s1 + (s2 - s1) * frac)
        if v > 32767:
            v = 32767
        elif v < -32768:
            v = -32768
        out[i] = v
    return out.tobytes()


_RETRY_BACKOFFS = (0.4, 1.0, 2.5)  # seconds between attempts


# ---------------------------------------------------------------------------
# Google Translate free endpoint
# ---------------------------------------------------------------------------
# Unofficial public endpoint Google uses for the translate.google.com web UI.
# No API key required. Works fine for short selections (a sentence or two);
# Google can rate-limit per-IP under heavy use. If it ever shuts down,
# swap to LibreTranslate or DeepL by changing _translate_call only.

_GOOGLE_TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"


class TranslationError(Exception):
    pass


def _translate_call(text: str, target_lang: str, source_lang: str = "auto") -> str:
    params = {
        "client": "gtx",
        "sl": source_lang,
        "tl": target_lang,
        "dt": "t",
        "q": text,
    }
    url = _GOOGLE_TRANSLATE_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            # Google sniffs the UA; default urllib UA gets 403'd.
            "User-Agent": "Mozilla/5.0 (compatible; NVDA-ElevenLabs-TTS)",
        },
    )
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise TranslationError(f"HTTP {e.code} from Google Translate") from e
    except Exception as e:
        raise TranslationError(f"{type(e).__name__}: {e}") from e

    try:
        data = json.loads(raw)
        # Response shape: [[[translated, original, ...], ...], ..., source_lang]
        segments = data[0] or []
        return "".join(seg[0] for seg in segments if seg and seg[0])
    except Exception as e:
        raise TranslationError(f"could not parse response ({e})") from e


def translate_text(text: str, target_lang: str, source_lang: str = "auto") -> str:
    """Translate text using Google's free public endpoint.

    Returns the translated string. Raises TranslationError on failure.
    Long selections are chunked at sentence boundaries to stay under
    the endpoint's ~5000-character soft limit.
    """
    text = (text or "").strip()
    if not text:
        return ""
    if len(text) < 4500:
        return _translate_call(text, target_lang, source_lang)

    # Long input — chunk at sentence-ish boundaries.
    chunks = []
    cur = ""
    for piece in text.replace("?", "? ").replace("!", "! ").split(". "):
        if len(cur) + len(piece) + 2 > 4500:
            if cur:
                chunks.append(cur)
            cur = piece
        else:
            cur = (cur + ". " + piece) if cur else piece
    if cur:
        chunks.append(cur)

    out = []
    for ch in chunks:
        out.append(_translate_call(ch, target_lang, source_lang))
    return " ".join(out)


def _api_request(method: str, path: str, api_key: str, body: bytes | None = None,
                 extra_headers: dict | None = None, retries: int = 3):
    """Issue an HTTP request with retry-and-backoff.

    Retried:
      * transport errors (TLS reset, connection closed, etc.) — could just be
        a stale keep-alive connection.
      * HTTP 5xx — server-side hiccup.
      * HTTP 429 — rate-limited; we honour Retry-After when present.
    Not retried:
      * 4xx other than 429 — caller fault, won't fix itself.
    """
    headers = {
        "xi-api-key": api_key,
        "Accept": "*/*",
        "Connection": "keep-alive",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    if extra_headers:
        headers.update(extra_headers)

    last_err = None
    for attempt in range(retries + 1):
        conn = _get_https_conn()
        try:
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
        except (http.client.HTTPException, ConnectionError, OSError) as e:
            last_err = e
            _reset_https_conn()
            if attempt >= retries:
                break
            # The most common transport error is a stale keep-alive: the server
            # closed the idle connection but our cached HTTPSConnection didn't
            # notice. That just needs an immediate reconnect — sleeping makes
            # the user wait for nothing. Only back off if a *fresh* connection
            # also failed (real network trouble).
            if attempt == 0:
                log.info(f"ElevenLabs: stale connection, reconnecting immediately ({e})")
                continue
            delay = _RETRY_BACKOFFS[min(attempt - 1, len(_RETRY_BACKOFFS) - 1)]
            log.warning(
                f"ElevenLabs: transport error on attempt {attempt + 1}/"
                f"{retries + 1}, retrying in {delay}s: {e}"
            )
            time.sleep(delay)
            continue

        # Got an HTTP response — decide if it's retryable.
        retryable = resp.status >= 500 or resp.status == 429
        if not retryable or attempt >= retries:
            return resp

        # Drain + close before retry.
        retry_after = resp.getheader("Retry-After")
        try:
            resp.read()
        finally:
            resp.close()
        _reset_https_conn()
        try:
            delay = float(retry_after) if retry_after else _RETRY_BACKOFFS[min(attempt, len(_RETRY_BACKOFFS) - 1)]
        except ValueError:
            delay = _RETRY_BACKOFFS[min(attempt, len(_RETRY_BACKOFFS) - 1)]
        log.warning(
            f"ElevenLabs: HTTP {resp.status} on attempt {attempt + 1}/"
            f"{retries + 1}, retrying in {delay}s"
        )
        time.sleep(delay)

    raise ElevenLabsAPIError(0, f"transport error after retries: {last_err}")


def _read_error_body(resp) -> dict | str:
    raw = b""
    try:
        raw = resp.read()
    except Exception:
        pass
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return raw.decode("utf-8", errors="replace")


def _stream_tts(
    api_key: str,
    voice_id: str,
    text: str,
    model_id: str,
    output_format: str,
    optimize_streaming_latency: str,
    voice_settings: dict,
    seed: int = 42,
    chunk_size: int = 4096,
    language_code: str | None = None,
):
    """Yield raw audio chunks from the ElevenLabs streaming endpoint.

    Uses the persistent HTTPS connection so back-to-back requests skip the
    TLS handshake. `language_code` is only sent when the chosen model is
    multilingual.
    """
    path = (
        f"/v1/text-to-speech/{urllib.parse.quote(voice_id)}/stream"
        f"?output_format={urllib.parse.quote(output_format)}"
        f"&optimize_streaming_latency={urllib.parse.quote(str(optimize_streaming_latency))}"
    )
    payload_dict = {
        "text": text,
        "model_id": model_id,
        "voice_settings": voice_settings,
        "seed": seed,
    }
    if language_code and _model_supports_language(model_id):
        payload_dict["language_code"] = language_code
    payload = json.dumps(payload_dict).encode("utf-8")

    resp = _api_request("POST", path, api_key, body=payload)
    if resp.status >= 400:
        body = _read_error_body(resp)
        raise ElevenLabsAPIError(resp.status, body)

    try:
        while True:
            chunk = resp.read(chunk_size)
            if not chunk:
                return
            yield chunk
    except (http.client.HTTPException, ConnectionError, OSError):
        # Stream interrupted — reset connection so the next call starts clean.
        _reset_https_conn()
        return
    finally:
        try:
            resp.close()
        except Exception:
            pass


# A pure-Python WebSocket client lived here briefly in 1.5.0 but was
# removed in 1.5.1 — on real networks it wasn't faster than the
# persistent-HTTP path below, and the opt-in checkbox confused users.
# HTTP via http.client.HTTPSConnection (stdlib) is the only backend now.




def fetch_voices(api_key: str):
    """Fetch the user's voice library from ElevenLabs.

    Returns a list of (display_name, voice_id) tuples — Indian-accent voices
    floated to the top — or None on error.
    """
    if not api_key:
        return None
    try:
        resp = _api_request("GET", "/v1/voices", api_key)
    except ElevenLabsAPIError as e:
        log.warning(f"ElevenLabs: fetch_voices transport error: {e}")
        return None
    if resp.status != 200:
        try:
            resp.read()
        finally:
            resp.close()
        log.warning(f"ElevenLabs: fetch_voices HTTP {resp.status}")
        return None
    try:
        data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log.warning(f"ElevenLabs: fetch_voices parse error: {e}")
        return None
    finally:
        try:
            resp.close()
        except Exception:
            pass

    voices = data.get("voices") or []
    if not voices:
        return None

    def sort_key(v):
        labels = v.get("labels") or {}
        name = (v.get("name") or "").lower()
        accent = (labels.get("accent") or "").lower()
        is_indian = "indian" in accent or "indian" in name
        return (0 if is_indian else 1, name)

    voices.sort(key=sort_key)

    result = []
    for v in voices:
        name = (v.get("name") or "").strip()
        vid = (v.get("voice_id") or "").strip()
        if not (name and vid):
            continue
        labels = v.get("labels") or {}
        accent = labels.get("accent")
        gender = labels.get("gender")
        tag_parts = [p for p in (accent, gender) if p]
        display = f"{name}" + (f" ({', '.join(tag_parts)})" if tag_parts else "")
        result.append((display, vid))
    return result or None


def refresh_voice_list_from_api(api_key: str) -> bool:
    """Replace module-level VOICE_LIST with the live API result.

    Returns True if VOICE_LIST was updated, False if we fell back to the
    hardcoded list (no key, no network, or empty response).
    """
    fetched = fetch_voices(api_key)
    with _voice_list_lock:
        global VOICE_LIST
        if fetched:
            VOICE_LIST = fetched
            _rebuild_voice_indexes()
            log.info(f"ElevenLabs: voice list loaded from API ({len(fetched)} voices).")
            return True
        VOICE_LIST = list(_FALLBACK_VOICE_LIST)
        _rebuild_voice_indexes()
        log.warning("ElevenLabs: using fallback voice list (live fetch failed or empty).")
        return False


def diagnose_subscription(api_key: str) -> tuple[bool, str, dict | None]:
    """Verbose version of fetch_subscription used by the test diagnostic.

    Returns (ok, summary, info_dict_or_None).

    The summary string tells the caller *why* step 1 didn't work so the
    user sees something more useful than "step 1 failed". A 401 here is
    not a deal-breaker — it usually just means the key is scoped to TTS
    only and the test should keep going (step 2 will tell us if the key
    actually works for TTS).
    """
    if not api_key:
        return False, "no API key entered", None
    try:
        resp = _api_request("GET", "/v1/user/subscription", api_key)
    except ElevenLabsAPIError as e:
        return False, f"network/transport error ({e})", None

    if resp.status == 200:
        try:
            data = json.loads(resp.read().decode("utf-8"))
            return True, "OK", data
        except Exception as e:
            return False, f"could not parse subscription JSON ({e})", None
        finally:
            try:
                resp.close()
            except Exception:
                pass

    # Non-200 → drain body for diagnostics
    body = _read_error_body(resp)
    status = resp.status
    try:
        resp.close()
    except Exception:
        pass

    if status == 401:
        return (
            False,
            "HTTP 401 — endpoint refused the key. Most likely the key is "
            "scoped to TTS only (no user_read permission). TTS may still work.",
            body if isinstance(body, dict) else None,
        )
    if status == 403:
        return (
            False,
            "HTTP 403 — key forbidden for /v1/user/subscription "
            "(scoped key without user_read permission). TTS may still work.",
            body if isinstance(body, dict) else None,
        )
    return False, f"HTTP {status}: {body!r}", body if isinstance(body, dict) else None


def fetch_subscription(api_key: str) -> dict | None:
    """Return ElevenLabs subscription/quota info, or None on error.

    Shape (subset): {character_count, character_limit, tier, ...}
    """
    if not api_key:
        return None
    try:
        resp = _api_request("GET", "/v1/user/subscription", api_key)
    except ElevenLabsAPIError:
        return None
    if resp.status != 200:
        try:
            resp.read()
        finally:
            resp.close()
        return None
    try:
        return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    finally:
        try:
            resp.close()
        except Exception:
            pass


def _explain_api_error(err: ElevenLabsAPIError, voice_label: str) -> tuple[str, bool]:
    """Turn an API error into a friendly multi-line message.

    Returns (message, voice_unusable). voice_unusable is True when the
    failure is specifically about the chosen voice not being on the
    user's tier — the caller (settings panel) should refresh the voice
    list in that case.
    """
    code = err.status_code
    body = err.body
    msg = None
    status = None
    if isinstance(body, dict):
        d = body.get("detail")
        if isinstance(d, dict):
            msg = d.get("message")
            status = d.get("status")
        elif isinstance(d, str):
            msg = d

    # 402 / payment_required → voice issue, key is fine
    if code == 402 or status == "payment_required" or (
        msg and ("upgrade" in msg.lower() or "library voices" in msg.lower())
    ):
        return (
            f"Voice '{voice_label}' requires a paid plan.\n\n"
            f"Server message: {msg or '(no detail)'}\n\n"
            f"The voice list has been refreshed to show only the voices your "
            f"account can use. Pick one of those and try again.",
            True,
        )
    if code == 401:
        return (
            f"API rejected the key (HTTP 401).\n\nServer message: "
            f"{msg or '(no detail)'}\n\nCheck the key for typos or expiration.",
            False,
        )
    if code == 429:
        return (
            "Rate-limited (HTTP 429). Wait a moment and try again.",
            False,
        )
    if 500 <= code < 600:
        return (
            f"ElevenLabs server error ({code}). Try again in a moment.",
            False,
        )
    if code == 0:
        return (
            f"Could not reach api.elevenlabs.io.\n\nDetails: {body!r}",
            False,
        )
    return (
        f"HTTP {code}: {msg or body!r}",
        False,
    )


# Sample phrases per language for the "Test" button. Each translates
# roughly to "Hello, this is ElevenLabs TTS." so the user hears the
# language they picked actually produce sound in that language.
_TEST_PHRASES = {
    "en":  "ElevenLabs T T S connected.",
    "hi":  "नमस्ते, यह एलेवनलैब्स टीटीएस है।",
    "ta":  "வணக்கம், இது எலெவன்லேப்ஸ் டிடிஎஸ்.",
    "bn":  "নমস্কার, এটি এলেভেনল্যাবস টিটিএস।",
    "te":  "నమస్కారం, ఇది ఎలెవెన్‌ల్యాబ్స్ టిటిఎస్.",
    "mr":  "नमस्कार, हे एलेवनलॅब्स टीटीएस आहे.",
    "gu":  "નમસ્તે, આ એલેવનલેબ્સ ટીટીએસ છે.",
    "kn":  "ನಮಸ್ಕಾರ, ಇದು ಎಲೆವೆನ್‌ಲ್ಯಾಬ್ಸ್ ಟಿಟಿಎಸ್.",
    "ml":  "നമസ്കാരം, ഇത് എലെവെൻലാബ്സ് ടിടിഎസ് ആണ്.",
    "pa":  "ਨਮਸਤੇ, ਇਹ ਇਲੈਵਨਲੈਬਜ਼ ਟੀਟੀਐਸ ਹੈ।",
    "ur":  "السلام علیکم، یہ ایلیون لیبز ٹی ٹی ایس ہے۔",
}


def speak_test_phrase(
    api_key: str,
    voice_id: str,
    voice_label: str = "",
    language_code: str = "en",  # accepted but ignored — kept for old callers
    model_id: str = "eleven_turbo_v2_5",
    phrase: str | None = None,
) -> tuple[bool, str, bool]:
    """Two-step diagnostic for the settings panel "Test" button.

    Step 1: GET /v1/user/subscription — verifies that the key
    authenticates. Works on every tier (free included).

    Step 2: TTS request with the selected voice — verifies the audio
    pipeline AND that the user's tier allows that voice.

    Returns (success, multi-line message, voice_unusable).
    voice_unusable is True only when step 1 passed but step 2 failed
    with a 402 / payment_required — the caller refreshes the voice list.
    """
    if not api_key:
        log.warning("ElevenLabs test: no API key.")
        return False, "Enter an API key first.", False

    label = voice_label or voice_id

    # Test always uses an English phrase (1.4.0 design): the Test button
    # is about "is the key + voice working", not "does my translation
    # language sound right". For Indian-language verification, use the
    # NVDA+Shift+T translate-selection gesture instead.
    test_text = phrase if phrase is not None else _TEST_PHRASES["en"]
    effective_model = model_id or "eleven_turbo_v2_5"
    effective_language = None
    lang_label = "English"

    # ---- Step 1 — subscription info (PURELY INFORMATIONAL) ----
    # Some keys are scoped to TTS only and 401 on /v1/user/subscription
    # even though TTS itself works perfectly. Step 1 must not gate the
    # test — step 2 (actually speaking) is the real authentication check.
    log.info("ElevenLabs test: step 1 — /v1/user/subscription")
    sub_ok, sub_summary, sub_info = diagnose_subscription(api_key)
    if sub_ok and isinstance(sub_info, dict):
        tier = sub_info.get("tier") or "?"
        used = sub_info.get("character_count")
        limit = sub_info.get("character_limit")
        if isinstance(used, int) and isinstance(limit, int) and limit > 0:
            step1_line = f"Step 1 OK — Tier '{tier}', {used:,} / {limit:,} characters used."
        else:
            step1_line = f"Step 1 OK — Tier '{tier}'."
    else:
        step1_line = (
            f"Step 1 SKIPPED — {sub_summary}\n"
            f"(That's usually fine — many keys are scoped to TTS only. "
            f"Step 2 is the real test.)"
        )
        log.info(f"ElevenLabs test: step 1 skipped — {sub_summary}")

    # ---- Step 2 — voice / audio (THE ACTUAL AUTH + USABILITY CHECK) ----
    log.info(
        f"ElevenLabs test: step 2 — voice_id={voice_id!r}, "
        f"model={effective_model!r}, language={effective_language!r}, "
        f"phrase={test_text!r}"
    )
    try:
        chunks = list(_stream_tts(
            api_key=api_key,
            voice_id=voice_id,
            text=test_text,
            model_id=effective_model,
            output_format="pcm_16000",
            optimize_streaming_latency="4",
            voice_settings=_rate_to_voice_settings(50),
            language_code=effective_language,
        ))
    except ElevenLabsAPIError as e:
        log.error(f"ElevenLabs test: step 2 API error {e.status_code}: {e.body!r}")
        explanation, voice_unusable = _explain_api_error(e, label)
        return False, f"{step1_line}\n\nStep 2 (voice) failed.\n{explanation}", voice_unusable
    except Exception as e:
        log.error(f"ElevenLabs test: step 2 {type(e).__name__}: {e}")
        return False, f"{step1_line}\n\nStep 2 transport error: {type(e).__name__}: {e}", False

    pcm = b"".join(chunks)
    nbytes = len(pcm)
    log.info(f"ElevenLabs test: received {nbytes} bytes of PCM ({len(chunks)} chunks).")
    if nbytes == 0:
        return False, f"{step1_line}\n\nStep 2: voice returned no audio.", False
    if nbytes % 2 != 0:
        pcm += b"\x00"

    try:
        player = nvwave.WavePlayer(channels=1, samplesPerSec=16000, bitsPerSample=16)
        player.feed(pcm)
        try:
            player.idle()
        except Exception:
            pass
        try:
            player.close()
        except Exception:
            pass
    except Exception as e:
        log.error(f"ElevenLabs test: step 2 playback failed: {type(e).__name__}: {e}")
        return False, f"{step1_line}\n\nStep 2: audio playback failed: {e}", False

    seconds = nbytes / (16000 * 2)
    return (
        True,
        f"{step1_line}\n\n"
        f"Step 2 OK — voice '{label}' speaking {lang_label} plays "
        f"({seconds:.1f}s of audio, {nbytes:,} PCM bytes).\n\n"
        f"Phrase used: {test_text}",
        False,
    )


# Letters + digits + a few common single-character punctuation marks.
# Each is sent as "<char>." to mimic the driver's _expand_single_char path.
_PREWARM_CHARS = list("abcdefghijklmnopqrstuvwxyz0123456789.,!?;:")


def prewarm_cache_for_voice(
    api_key: str,
    voice_id: str,
    model_id: str = "eleven_turbo_v2_5",
    output_format: str = "pcm_16000",
    language_code: str | None = None,
    progress_cb=None,
):
    """Fetch + cache audio for every common single character.

    Run from a worker thread. progress_cb(done, total, char) is invoked
    after each fetch so the UI can show progress. Returns
    (cached_count, skipped_count, error_count).
    """
    cached = skipped = errors = 0
    total = len(_PREWARM_CHARS)
    voice_settings = _rate_to_voice_settings(50)

    for i, ch in enumerate(_PREWARM_CHARS):
        text = _expand_single_char(ch)
        path = _cache_path(voice_id, text, output_format)
        if path and _read_cache(path) is not None:
            skipped += 1
            if progress_cb:
                try:
                    progress_cb(i + 1, total, ch)
                except Exception:
                    pass
            continue
        try:
            buf = bytearray()
            for chunk in _stream_tts(
                api_key=api_key,
                voice_id=voice_id,
                text=text,
                model_id=model_id,
                output_format=output_format,
                optimize_streaming_latency="4",
                voice_settings=voice_settings,
                language_code=language_code,
            ):
                buf.extend(chunk)
            if buf and path:
                _write_cache(path, bytes(buf))
                cached += 1
            else:
                errors += 1
        except Exception as e:
            log.warning(f"ElevenLabs prewarm: '{ch}' failed: {type(e).__name__}: {e}")
            errors += 1
        if progress_cb:
            try:
                progress_cb(i + 1, total, ch)
            except Exception:
                pass

    log.info(f"ElevenLabs prewarm: voice={voice_id} cached={cached} skipped={skipped} errors={errors}")
    return cached, skipped, errors


class SynthDriver(synthDriverHandler.SynthDriver):
    name = "elevenlabs"
    description = "ElevenLabs Streaming AI"

    supportedSettings = (
        NumericSynthSetting("rate",   "Rate",   minVal=0, maxVal=100),
        SynthSetting       ("voice",  "Voice"),
        NumericSynthSetting("volume", "Volume", minVal=0, maxVal=100),
        NumericSynthSetting("pitch",  "Pitch",  minVal=0, maxVal=100),
    )

    @property
    def rate(self) -> int:
        return self._rate

    @rate.setter
    def rate(self, value: int):
        self._rate = max(0, min(100, int(value)))

    @property
    def volume(self) -> int:
        return self._volume

    @volume.setter
    def volume(self, value: int):
        self._volume = max(0, min(100, int(value)))

    @property
    def pitch(self) -> int:
        return self._pitch

    @pitch.setter
    def pitch(self, value: int):
        self._pitch = max(0, min(100, int(value)))

    @property
    def voice(self) -> str:
        return self._voice

    @voice.setter
    def voice(self, value: str):
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

    @classmethod
    def check(cls):
        return True

    def _have_api_key(self) -> bool:
        if _load_elevenlabs_api_key():
            return True
        log.error(
            "ElevenLabs: API key missing. Open NVDA Menu > Preferences > Settings > "
            "ElevenLabs TTS and paste your key."
        )
        return False

    def _load_defaults_from_config(self):
        try:
            section = config.conf[CONFIG_SECTION]
        except Exception:
            return
        try:
            default_voice = (section.get("defaultVoice") or "").strip()
            if default_voice and default_voice in _VOICE_NAME_TO_ID:
                self._voice_name = default_voice
                self._voice = _VOICE_NAME_TO_ID[default_voice]
                self.voice_id = self._voice
        except Exception:
            pass
        try:
            default_model = (section.get("defaultModel") or "").strip()
            if default_model and default_model in _MODEL_ID_TO_LABEL:
                self.model_id = default_model
        except Exception:
            pass
        # Note: defaultLanguage was removed in 1.4.0. The Language synth
        # setting was confusing — it only acts as a pronunciation hint, not
        # a translator. The translate-selection gesture uses
        # translationLanguage instead (read at gesture time, not here).

    def _kick_off_voice_refresh(self):
        """Pull the live voice list from /v1/voices in the background.

        If the saved default voice is not in the user's actual library
        (the most common case after install — ElevenLabs has moved
        several premade voices behind paywalls) we transparently switch
        to the first voice the account CAN use, and persist that change
        to config so a restart doesn't undo it.
        """
        def worker():
            try:
                api_key = _load_elevenlabs_api_key()
                if not api_key:
                    return
                refresh_voice_list_from_api(api_key)
                with _voice_list_lock:
                    if self.voice_id in _VOICE_ID_TO_NAME:
                        # Saved voice survived — just refresh the display name.
                        self._voice_name = _VOICE_ID_TO_NAME[self.voice_id]
                        return
                    if not VOICE_LIST:
                        return
                    name, vid = VOICE_LIST[0]
                    old_vid = self.voice_id
                    self._voice_name = name
                    self._voice = vid
                    self.voice_id = vid
                    log.info(
                        f"ElevenLabs: saved voice {old_vid!r} is not available "
                        f"on this tier; switching to {name!r} ({vid!r})."
                    )
                # Persist outside the voice-list lock — config writes can be slow.
                try:
                    config.conf[CONFIG_SECTION]["defaultVoice"] = name
                except Exception as e:
                    log.warning(f"ElevenLabs: could not persist auto-picked voice: {e}")
            except Exception as e:
                log.warning(f"ElevenLabs: voice refresh failed: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def __init__(self):
        super().__init__()

        self._voice_name = _VOICE_NAMES[0]
        self._voice      = _VOICE_NAME_TO_ID[self._voice_name]
        self.voice_id    = self._voice
        self.model_id    = "eleven_turbo_v2_5"
        self.output_format = (os.getenv("ELEVENLABS_OUTPUT_FORMAT") or "pcm_16000").strip()

        self._rate   = 50
        self._volume = 100
        self._pitch  = 50

        self._load_defaults_from_config()

        self._queue       = queue.Queue()
        self._cancelToken = 0
        self._lock        = threading.Lock()
        self._player      = None
        self._worker      = threading.Thread(target=self._workerLoop, daemon=True)
        self._worker.start()

        # Defer API key check to first speak() so the driver can be selected
        # even before a key has been entered (the user will be told via the
        # NVDA log if a key is missing).
        if not self._have_api_key():
            log.warning("ElevenLabs: driver loaded without an API key — no audio will play.")
        else:
            self._kick_off_voice_refresh()

    def _getSampleRate(self, output_format: str) -> int:
        return _PCM_FORMAT_SAMPLE_RATES.get(output_format, 22050)

    def _ensurePlayer(self, sample_rate: int):
        if self._player is None:
            self._player = nvwave.WavePlayer(
                channels=1,
                samplesPerSec=sample_rate,
                bitsPerSample=16,
            )

    def _feed_chunk(self, chunk: bytes, sample_rate: int):
        """Apply pitch + volume transforms then feed to the active player."""
        if len(chunk) % 2 != 0:
            chunk += b"\x00"
        if self._pitch != 50:
            ratio = 0.75 + (max(0, min(100, self._pitch)) / 100.0) * 0.50
            in_rate = max(4000, int(sample_rate * ratio))
            chunk = _resample_mono16(chunk, in_rate, sample_rate)
        if self._volume != 100:
            chunk = _apply_volume(chunk, self._volume)
        return chunk

    def _play_from_cache(self, cached: bytes, sample_rate: int, token: int) -> bool:
        with self._lock:
            if token != self._cancelToken:
                return True
            if self._player:
                self._player.stop()
                self._player = None
            self._ensurePlayer(sample_rate)
        # Feed cached PCM in modest-sized chunks so cancel still works.
        step = 4096
        for i in range(0, len(cached), step):
            with self._lock:
                if token != self._cancelToken:
                    return True
                player = self._player
            if player is None:
                return True
            player.feed(self._feed_chunk(cached[i:i + step], sample_rate))
        synthDoneSpeaking.notify(synth=self)
        return True

    def _streamAndPlay(self, text: str, token: int,
                       model_override: str | None = None,
                       language_override: str | None = None):
        api_key = _load_elevenlabs_api_key()
        if not api_key:
            log.error("ElevenLabs: API key missing — cannot speak.")
            return

        model_id = model_override or self.model_id
        language_code = language_override  # only set by translation path
        # Translations are user-triggered and per-language — caching them by
        # (voice, format, text) would let "translate me to Hindi" replay an
        # earlier "translate me to Tamil" result if the text matched. Skip
        # the cache for the overridden path.
        skip_cache = bool(model_override or language_override)

        voice_settings = _rate_to_voice_settings(self._rate)
        fmt_try = self.output_format or "pcm_22050"
        cache_eligible = (not skip_cache) and len(text) <= _CACHE_MAX_TEXT_LEN

        for attempt_fmt in (fmt_try, "pcm_16000"):
            sample_rate = self._getSampleRate(attempt_fmt)

            cached_path = _cache_path(self.voice_id, text, attempt_fmt) if cache_eligible else None
            cached = _read_cache(cached_path) if cached_path else None
            if cached:
                self._play_from_cache(cached, sample_rate, token)
                return

            try:
                audio_stream = _stream_tts(
                    api_key=api_key,
                    voice_id=self.voice_id,
                    text=text,
                    model_id=model_id,
                    output_format=attempt_fmt,
                    optimize_streaming_latency="4",
                    voice_settings=voice_settings,
                    language_code=language_code,
                )

                with self._lock:
                    if token != self._cancelToken:
                        return
                    if self._player:
                        self._player.stop()
                        self._player = None
                    self._ensurePlayer(sample_rate)

                cache_buf = bytearray() if cache_eligible else None
                for chunk in audio_stream:
                    if not chunk:
                        continue
                    with self._lock:
                        if token != self._cancelToken:
                            return
                        player = self._player
                    if player is None:
                        return
                    if cache_buf is not None:
                        cache_buf.extend(chunk)
                    player.feed(self._feed_chunk(chunk, sample_rate))

                if cache_buf and cached_path:
                    _write_cache(cached_path, bytes(cache_buf))

                synthDoneSpeaking.notify(synth=self)
                return
            except ElevenLabsAPIError as e:
                if attempt_fmt != "pcm_16000" and _is_output_format_not_allowed(e):
                    log.warning(
                        f"ElevenLabs: output_format '{attempt_fmt}' not allowed; "
                        f"retrying with pcm_16000"
                    )
                    continue
                log.error(f"ElevenLabs: API error ({attempt_fmt}): {e}")
                return
            except Exception as e:
                log.error(f"ElevenLabs: Streaming error ({attempt_fmt}): {type(e).__name__}: {e}")
                return

    def _workerLoop(self):
        while True:
            item = self._queue.get()
            try:
                if item is _STOP:
                    return
                # Two queue item forms:
                #   ("speak", text, token)        — normal NVDA speech
                #   ("translate", text, token, lang_code) — translation path
                kind = item[0]
                if kind == "speak":
                    _, text, token = item
                    self._streamAndPlay(text, token)
                elif kind == "translate":
                    _, text, token, lang_code = item
                    self._streamAndPlay(
                        text, token,
                        model_override="eleven_multilingual_v2",
                        language_override=lang_code,
                    )
                else:
                    log.warning(f"ElevenLabs: unknown queue item: {item!r}")
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

        if len(text) == 1:
            text = _expand_single_char(text)

        with self._lock:
            self._cancelToken += 1
            token = self._cancelToken
            if self._player:
                self._player.stop()
                self._player = None

        self._queue.put(("speak", text, token))

    def speakTranslation(self, text: str, lang_code: str):
        """Translate-and-speak entry point used by the global gesture.

        Forces eleven_multilingual_v2 + the supplied language code so the
        text is pronounced correctly regardless of the user's saved Model
        setting. Cancels whatever is playing right now (translation is a
        user-initiated interrupt).
        """
        text = (text or "").strip()
        if not text:
            return
        with self._lock:
            self._cancelToken += 1
            token = self._cancelToken
            if self._player:
                self._player.stop()
                self._player = None
        self._queue.put(("translate", text, token, lang_code))

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
