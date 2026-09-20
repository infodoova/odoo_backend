"""
Speech-to-Text (STT) Service powered by Deepgram Nova-3 Multilingual.
Provides fast, accurate transcription across Arabic, English, French, Spanish, and other languages.
"""

import os
import re
import json
import time
import logging
import asyncio
import aiohttp
import websockets
from typing import Dict, Any, Optional
from django.conf import settings as django_settings

logger = logging.getLogger(__name__)

DEBUG_LOG_FILE = "/home/alhassan/Projects/Doova/odoo/stt_debug.log"

def debug_log(msg: str):
    try:
        from datetime import datetime
        with open(DEBUG_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]} {msg}\n")
    except Exception:
        pass
    print(msg, flush=True)

DEEPGRAM_LISTEN_URL = "https://api.deepgram.com/v1/listen"
ARABIC_CHAR_PATTERN = re.compile(r'[\u0600-\u06FF]')
DEVANAGARI_PATTERN = re.compile(r'[\u0900-\u097F]')

COMMON_ENGLISH_WORDS = {
    'hello', 'hi', 'hey', 'nexus', 'how', 'are', 'you', 'what', 'is', 'the', 'this', 'that',
    'can', 'could', 'would', 'should', 'will', 'do', 'does', 'did', 'have', 'has', 'had',
    'our', 'my', 'your', 'we', 'i', 'me', 'us', 'today', 'yesterday', 'month', 'year',
    'revenue', 'profit', 'sales', 'loss', 'cost', 'expenses', 'balance', 'cash', 'flow',
    'customer', 'customers', 'vendor', 'vendors', 'invoice', 'invoices', 'report', 'good',
    'morning', 'afternoon', 'evening', 'night', 'thank', 'thanks', 'please', 'help', 'check',
    'order', 'orders', 'stock', 'inventory', 'total', 'company', 'business', 'data'
}


SPOKEN_EMAIL_PREFIXES = r'(?:info|admin|support|contact|sales|hello|team|billing|office|help|service|careers|jobs|press|media|mail)'


def normalize_spoken_symbols(text: str) -> str:
    """
    Normalizes spoken symbols and email addresses in transcripts.
    E.g.:
    - 'info at' -> 'info@'
    - 'info at example dot com' -> 'info@example.com'
    - 'admin at doova.com' -> 'admin@doova.com'
    - 'انفو ات' -> 'info@'
    """
    if not text:
        return text

    # 1. Spoken domain names in Arabic: e.g. 'دووفا' -> 'doova', 'جيميل' -> 'gmail', 'ياهو' -> 'yahoo'
    text = re.sub(r'(^|\s)(?:دووفا|دوفا)(?=$|\s|[.,!?])', r'\g<1>doova', text, flags=re.IGNORECASE)
    text = re.sub(r'(^|\s)(?:جيميل|جميل)(?=$|\s|[.,!?])', r'\g<1>gmail', text, flags=re.IGNORECASE)
    text = re.sub(r'(^|\s)(?:ياهو)(?=$|\s|[.,!?])', r'\g<1>yahoo', text, flags=re.IGNORECASE)
    text = re.sub(r'(^|\s)(?:اوتلوك)(?=$|\s|[.,!?])', r'\g<1>outlook', text, flags=re.IGNORECASE)

    # 2. Arabic spoken domain extensions: e.g. 'دوت كوم' -> '.com', 'دوت نت' -> '.net'
    text = re.sub(r'(^|\s)دوت\s+كوم(?=$|\s|[.,!?])', '.com', text, flags=re.IGNORECASE)
    text = re.sub(r'(^|\s)دوت\s+نت(?=$|\s|[.,!?])', '.net', text, flags=re.IGNORECASE)
    text = re.sub(r'(^|\s)دوت\s+(?:اورغ|اورج)(?=$|\s|[.,!?])', '.org', text, flags=re.IGNORECASE)
    text = re.sub(r'(^|\s)دوت\s+(?:اس\s*ايه|سا)(?=$|\s|[.,!?])', '.sa', text, flags=re.IGNORECASE)

    # 3. Arabic spoken 'ات' before email providers: e.g. 'ات جيميل' -> '@gmail.com'
    text = re.sub(r'(^|\s)(?:ات|at)\s+(gmail|yahoo|hotmail|outlook|icloud|proton)\b', r'\g<1>@\2.com', text, flags=re.IGNORECASE)

    # 4. Arabic 'انفو ات' or 'info at' followed by domain: e.g. 'انفو ات doova.com' -> 'info@doova.com'
    text = re.sub(r'(?:انفو|info)\s+(?:ات|at)\s*([a-zA-Z0-9.-]+)', r'info@\1', text, flags=re.IGNORECASE)

    # 5. Standalone Arabic 'انفو ات' or 'انفو at' -> 'info@'
    text = re.sub(r'(^|[^\u0600-\u06FF\w])(?:انفو|info)\s+(?:ات|at)(?=$|[^\u0600-\u06FF\w])', r'\g<1>info@', text, flags=re.IGNORECASE)

    # 4. Spoken email with 'dot com/org/net/etc': e.g. 'john at example dot com' -> 'john@example.com'
    text = re.sub(
        r'\b([a-zA-Z0-9._%+-]+)\s+at\s+([a-zA-Z0-9-]+)\s+dot\s+([a-zA-Z]{2,})\b',
        r'\1@\2.\3',
        text,
        flags=re.IGNORECASE
    )

    # 5. Spoken email with already dotted domain: e.g. 'info at doova.com' -> 'info@doova.com'
    text = re.sub(
        r'\b([a-zA-Z0-9._%+-]+)\s+at\s+([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b',
        r'\1@\2',
        text,
        flags=re.IGNORECASE
    )

    # 6. Spoken 'dot' in domain suffixes: e.g. 'example dot com' -> 'example.com'
    text = re.sub(
        r'\b([a-zA-Z0-9-]+)\s+dot\s+(com|org|net|io|ai|co|edu|gov|sa|ae|eg|uk|de|fr|app|dev)\b',
        r'\1.\2',
        text,
        flags=re.IGNORECASE
    )

    # 7. Spoken email prefix with 'at': e.g. 'info at', 'admin at', 'support at' -> 'info@', 'admin@'
    text = re.sub(
        rf'\b({SPOKEN_EMAIL_PREFIXES})\s+at(?=\s|$|[.,!?])',
        r'\1@',
        text,
        flags=re.IGNORECASE
    )

    # 8. Clean up trailing space after @ only if directly followed by a domain: e.g. 'info@ example.com' -> 'info@example.com'
    text = re.sub(r'(@)\s+([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', r'\1\2', text)
    text = re.sub(r'(@)\s+(gmail|yahoo|hotmail|outlook|icloud|proton|doova|company)\b', r'\1\2', text, flags=re.IGNORECASE)

    # 9. Spoken ERP Order references: "S O 0012" -> "SO0012", "P O 0005" -> "PO0005"
    text = re.sub(r'\b([Ss])\s*([Oo])\s*(\d{2,})\b', r'SO\3', text)
    text = re.sub(r'\b([Pp])\s*([Oo])\s*(\d{2,})\b', r'PO\3', text)

    # 10. Spoken phone prefix: "plus 966" / "بلاس 966" / "زائد 966" -> "+966"
    text = re.sub(r'\b(?:plus|بلاس|زائد)\s*(\d{1,4})\b', r'+\1', text, flags=re.IGNORECASE)

    # 11. Spoken percentage in Arabic / English: "15 percent" / "15 بالمية" -> "15%"
    text = re.sub(r'(\d+)\s*(?:percent|بالمية|بالمئة|في\s*المية|في\s*المئة)\b', r'\1%', text, flags=re.IGNORECASE)

    return text


def choose_best_transcript(multi_cand: Optional[Dict[str, Any]], ar_cand: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Arbitrates between Nova-3 Multilingual and Nova-3 Arabic candidates when dual candidates exist.
    """
    if not multi_cand and not ar_cand:
        return None
    if multi_cand and not ar_cand:
        return multi_cand
    if ar_cand and not multi_cand:
        return ar_cand

    t_m = (multi_cand.get("transcript") or "").strip()
    c_m = multi_cand.get("confidence", 0.0)

    t_a = (ar_cand.get("transcript") or "").strip()
    c_a = ar_cand.get("confidence", 0.0)

    if not t_m and t_a:
        return ar_cand
    if not t_a and t_m:
        return multi_cand
    if not t_m and not t_a:
        return None

    # 1. Devanagari script in multi is a clear signature of Arabic dialect misrecognized as Hindi
    if DEVANAGARI_PATTERN.search(t_m):
        return ar_cand

    # 2. English words detection
    words_m = set(re.findall(r'[a-zA-Z]+', t_m.lower()))
    has_common_en = bool(words_m.intersection(COMMON_ENGLISH_WORDS))

    # 3. If multi contains confirmed English words and reasonable confidence, English wins
    if has_common_en and c_m >= 0.65 and c_m >= (c_a - 0.10):
        return multi_cand

    # 4. If Arabic has solid confidence and clearly higher than multi, Arabic wins
    if c_a >= 0.75 and c_a > c_m:
        return ar_cand

    # 5. If multi has high confidence (e.g. 1.0 vs 0.74), multi wins
    if c_m >= 0.80 and c_m >= c_a:
        return multi_cand

    # 6. Fallback: whichever has higher confidence
    return ar_cand if c_a > c_m else multi_cand


class STTService:
    def __init__(self, api_key: Optional[str] = None):
        self._api_key = (
            api_key
            or getattr(django_settings, "DEEPGRAM_API_KEY", None)
            or os.getenv("DEEPGRAM_API_KEY")
            or os.getenv("DEEPGRAM_API_URL", "")
        ).strip()

    @property
    def api_key(self) -> str:
        if not self._api_key:
            self._api_key = (
                getattr(django_settings, "DEEPGRAM_API_KEY", None)
                or os.getenv("DEEPGRAM_API_KEY")
                or os.getenv("DEEPGRAM_API_URL", "")
            ).strip()
        return self._api_key

    async def transcribe(
        self,
        audio_bytes: bytes,
        content_type: str = "audio/webm",
        language: Optional[str] = "en",
    ) -> Dict[str, Any]:
        """
        Transcribe audio bytes using single-stream Deepgram Nova-3.

        Parameters:
            audio_bytes: Raw binary audio data.
            content_type: MIME type of audio (e.g. 'audio/webm', 'audio/wav', 'audio/mp3', 'audio/ogg').
            language: Specific code like 'ar', 'en', 'fr', 'es' or 'multi' / 'auto'.

        Returns:
            dict with:
                transcript: str
                language: str ('ar', 'en', 'fr', 'es', etc.)
                confidence: float
        """
        if not audio_bytes or len(audio_bytes) < 100:
            return {"transcript": "", "language": language or "en", "confidence": 0.0}

        key = self.api_key
        if not key:
            raise ValueError("DEEPGRAM_API_KEY is not configured. Please set DEEPGRAM_API_URL or DEEPGRAM_API_KEY in .env")

        headers = {
            "Authorization": f"Token {key}",
            "Content-Type": content_type or "audio/webm",
        }

        clean_lang = (language or "en").strip().lower()
        if clean_lang.startswith("ar"):
            clean_lang = "ar"
        elif clean_lang.startswith("en"):
            clean_lang = "en"
        elif clean_lang.startswith("fr"):
            clean_lang = "fr"
        elif clean_lang.startswith("es"):
            clean_lang = "es"
        else:
            clean_lang = "en"

        params = {
            "model": "nova-3",
            "language": clean_lang,
            "smart_format": "true",
            "punctuate": "true",
            "channels": "1",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(DEEPGRAM_LISTEN_URL, params=params, data=audio_bytes, headers=headers) as resp:
                if resp.status != 200:
                    err_text = await resp.text()
                    logger.error(f"Deepgram STT failed ({resp.status}): {err_text}")
                    raise RuntimeError(f"Deepgram STT API returned status {resp.status}: {err_text}")
                data = await resp.json()
                channel = data.get("results", {}).get("channels", [{}])[0]
                alt = channel.get("alternatives", [{}])[0]
                raw_text = alt.get("transcript", "").strip()
                normalized_text = normalize_spoken_symbols(raw_text)

                return {
                    "transcript": normalized_text,
                    "language": clean_lang,
                    "confidence": alt.get("confidence", 0.0),
                }

    def create_live_session(self, language: Optional[str] = "en", encoding: str = "linear16", sample_rate: int = 16000) -> "LiveStreamSession":
        """Creates a new real-time LiveStreamSession for WebSocket streaming."""
        return LiveStreamSession(api_key=self.api_key, language=language or "en", encoding=encoding, sample_rate=sample_rate)


class LiveStreamSession:
    """
    Manages real-time single-stream (mono) WebSocket between browser and Deepgram Nova-3.
    Direct, low-latency, and zero microphone conflict. Supports Linear16 PCM and WebM.
    """
    def __init__(self, api_key: str, language: str = "en", encoding: str = "linear16", sample_rate: int = 16000):
        self.api_key = api_key
        self.language = (language or "en").strip().lower()
        self.encoding = (encoding or "linear16").strip().lower()
        self.sample_rate = sample_rate or 16000
        self.is_closed = False

    async def stream_socket(self, client_ws):
        clean_lang = self.language
        if clean_lang.startswith("ar"):
            clean_lang = "ar"
        elif clean_lang.startswith("en"):
            clean_lang = "en"
        elif clean_lang.startswith("fr"):
            clean_lang = "fr"
        elif clean_lang.startswith("es"):
            clean_lang = "es"
        else:
            clean_lang = "en"

        ws_base = "wss://api.deepgram.com/v1/listen"
        if self.encoding == "linear16":
            url = f"{ws_base}?model=nova-3&language={clean_lang}&encoding=linear16&sample_rate={self.sample_rate}&channels=1&interim_results=true&smart_format=true&endpointing=300"
        else:
            url = f"{ws_base}?model=nova-3&language={clean_lang}&interim_results=true&smart_format=true&endpointing=300"

        logger.info(f"[Live STT] Connecting Deepgram Nova-3 socket (lang: {clean_lang}, encoding: {self.encoding}, rate: {self.sample_rate})...")

        import websockets
        try:
            debug_log(f"[Live STT] Connecting Deepgram Nova-3: {url}")
            async with websockets.connect(url, subprotocols=["token", self.api_key]) as dg_ws:
                debug_log("[Live STT] Connected to Deepgram Nova-3 socket successfully")
                chunk_count = 0
                total_bytes = 0
                dump_file = None
                try:
                    ext = "raw" if self.encoding == "linear16" else "webm"
                    dump_file = open(f"/home/alhassan/Projects/Doova/odoo/stt_dump.{ext}", "wb")
                except Exception:
                    pass

                async def pump_client():
                    nonlocal chunk_count, total_bytes
                    header_buf = bytearray()
                    initial_dispatched = False
                    try:
                        while not self.is_closed:
                            msg = await client_ws.receive()
                            msg_type = msg.get("type")
                            if msg_type == "websocket.disconnect":
                                debug_log(f"[Live STT] Client disconnected after {chunk_count} chunks ({total_bytes} bytes)")
                                self.is_closed = True
                                break
                            if "bytes" in msg and msg["bytes"]:
                                chunk_data = msg["bytes"]
                                chunk_count += 1
                                total_bytes += len(chunk_data)
                                if dump_file:
                                    try:
                                        dump_file.write(chunk_data)
                                        dump_file.flush()
                                    except Exception:
                                        pass

                                if self.encoding == "linear16":
                                    # Raw Linear16 PCM: zero-overhead streaming directly to Deepgram!
                                    if chunk_count <= 3 or chunk_count % 10 == 0:
                                        debug_log(f"[Live STT] Relaying PCM chunk #{chunk_count} ({len(chunk_data)} bytes, total: {total_bytes}) to Deepgram")
                                    await dg_ws.send(chunk_data)
                                else:
                                    # WebM container fallback: buffer initial small slices
                                    if not initial_dispatched:
                                        header_buf.extend(chunk_data)
                                        if len(header_buf) < 4000:
                                            debug_log(f"[Live STT] Buffering initial small chunk ({len(chunk_data)} B, buf: {len(header_buf)} B)")
                                            continue
                                        chunk_data = bytes(header_buf)
                                        header_buf.clear()
                                        initial_dispatched = True
                                        debug_log(f"[Live STT] Relaying initial unified chunk ({len(chunk_data)} bytes) to Deepgram")

                                    if chunk_count <= 3 or chunk_count % 10 == 0:
                                        debug_log(f"[Live STT] Relaying chunk #{chunk_count} ({len(chunk_data)} bytes, total: {total_bytes}) to Deepgram")
                                    await dg_ws.send(chunk_data)
                            elif "text" in msg and msg["text"]:
                                try:
                                    parsed = json.loads(msg["text"])
                                    if parsed.get("type") in ("close", "CloseStream"):
                                        debug_log(f"[Live STT] Client requested stream close after {chunk_count} chunks")
                                        if not initial_dispatched and header_buf:
                                            await dg_ws.send(bytes(header_buf))
                                            header_buf.clear()
                                            initial_dispatched = True
                                        # Send CloseStream to Deepgram so it flushes final results
                                        try:
                                            await dg_ws.send(json.dumps({"type": "CloseStream"}))
                                        except Exception:
                                            pass
                                        self.is_closed = True
                                        break
                                except Exception:
                                    pass
                    except Exception as e:
                        debug_log(f"[Live STT] pump_client error: {e}")
                        self.is_closed = True
                    finally:
                        if dump_file:
                            try:
                                dump_file.close()
                            except Exception:
                                pass

                async def pump_dg():
                    """Read Deepgram responses and relay to browser client."""
                    try:
                        async for raw_msg in dg_ws:
                            data = json.loads(raw_msg)
                            msg_type = data.get("type")
                            if msg_type == "Results":
                                alt = data.get("channel", {}).get("alternatives", [{}])[0]
                                raw_transcript = alt.get("transcript", "").strip()
                                is_final = data.get("is_final", False)
                                speech_final = data.get("speech_final", False)
                                conf = alt.get("confidence", 0.0)
                                debug_log(f"[Live STT] DG Results: is_final={is_final}, speech_final={speech_final}, conf={conf:.2f}, text='{raw_transcript}'")
                                if raw_transcript:
                                    transcript = normalize_spoken_symbols(raw_transcript)
                                    langs = alt.get("languages") or [clean_lang]
                                    try:
                                        await client_ws.send_json({
                                            "type": "transcript",
                                            "transcript": transcript,
                                            "is_final": is_final,
                                            "language": langs[0] if langs else clean_lang,
                                            "confidence": conf
                                        })
                                    except Exception as send_err:
                                        debug_log(f"[Live STT] Failed to send transcript to client: {send_err}")
                                        break
                            elif msg_type:
                                debug_log(f"[Live STT] DG non-results message: {msg_type} -> {raw_msg[:120]}")
                    except Exception as e:
                        debug_log(f"[Live STT] pump_dg error: {e}")

                client_task = asyncio.create_task(pump_client())
                dg_task = asyncio.create_task(pump_dg())

                # Wait for client to finish (mic stopped / close signal)
                await client_task

                # Grace period: keep draining Deepgram responses for up to 3 seconds
                # after the client disconnects, so in-flight transcripts are not lost
                if not dg_task.done():
                    debug_log("[Live STT] Client done, draining Deepgram responses (up to 3s grace)...")
                    try:
                        await asyncio.wait_for(dg_task, timeout=3.0)
                    except asyncio.TimeoutError:
                        debug_log("[Live STT] Grace period expired, closing Deepgram connection")
                    except Exception:
                        pass

                debug_log(f"[Live STT] Session pump ended. client_done: {client_task.done()}, dg_done: {dg_task.done()}")
                if not dg_task.done():
                    dg_task.cancel()
                    try:
                        await dg_task
                    except (asyncio.CancelledError, Exception):
                        pass
        except Exception as e:
            debug_log(f"[Live STT] WebSocket session error: {e}")
            logger.error(f"[Live STT] WebSocket session error: {e}")


stt_service = STTService()

