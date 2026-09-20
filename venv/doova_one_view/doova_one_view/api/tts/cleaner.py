"""
Text cleaner for Text-To-Speech (TTS).
Strips Markdown, code blocks, URLs, tables, and special formatting to produce natural spoken text.
Paces headings and bullet points with natural punctuation pauses, and expands financial abbreviations.
"""

import re
from typing import List

try:
    from num2words import num2words
except ImportError:
    num2words = None

from doova_one_view.api.tts.tashkeel import vocalize_arabic_text, clean_arabic_for_speech


def expand_numbers_for_speech(text: str, lang: str = "en") -> str:
    """
    Expands digits, percentages, years, currencies, and numbers into spoken words.
    Prevents TTS neural duration compression where raw digits cause the voice
    to speak at unnatural 2x-3x speed.
    """
    if not text or not num2words:
        return text

    clean_lang = (lang or "en").lower().strip()
    num_lang = "en"
    if clean_lang.startswith("ar"):
        if re.search(r'[\u0600-\u06FF]', text):
            num_lang = "ar"
    elif clean_lang.startswith("fr"):
        from doova_one_view.api.tts.detector import FRENCH_MARKERS, FRENCH_WORDS, ENGLISH_WORDS
        words = set(re.findall(r"\b[a-zA-Z\u00C0-\u017F]+\b", text.lower()))
        has_french = bool(FRENCH_MARKERS.search(text)) or bool(words & FRENCH_WORDS)
        has_english = bool(words & ENGLISH_WORDS)
        if has_french or not has_english:
            num_lang = "fr"
    elif clean_lang.startswith("es"):
        from doova_one_view.api.tts.detector import SPANISH_MARKERS, SPANISH_WORDS, ENGLISH_WORDS
        words = set(re.findall(r"\b[a-zA-Z\u00C0-\u017F]+\b", text.lower()))
        has_spanish = bool(SPANISH_MARKERS.search(text)) or bool(words & SPANISH_WORDS)
        has_english = bool(words & ENGLISH_WORDS)
        if has_spanish or not has_english:
            num_lang = "es"

    # 1. Negative sign before numbers: e.g. -56.3%, -1,000, -100
    text = re.sub(r"(^|[\s(])[-–]\s*(\d)", r"\1minus \2", text)

    # 2. Percentages: e.g. 56.3% or 15%
    def replace_percent(m):
        val_str = m.group(1).replace(",", "")
        try:
            val = float(val_str) if "." in val_str else int(val_str)
            words = num2words(val, lang=num_lang)
            percent_word = "percent" if num_lang == "en" else "pour cent" if num_lang == "fr" else "por ciento" if num_lang == "es" else "بالمائة"
            return f"{words} {percent_word}"
        except Exception:
            return m.group(0)

    text = re.sub(r"\b(\d+(?:\.\d+)?)\s*%", replace_percent, text)

    # 3. Years between 1900 and 2099: e.g. "in 2026", "2025"
    def replace_year(m):
        val_str = m.group(1)
        try:
            val = int(val_str)
            if num_lang == "en":
                return num2words(val, to="year", lang="en")
            return num2words(val, lang=num_lang)
        except Exception:
            return val_str

    text = re.sub(r"\b(19\d\d|20\d\d)\b", replace_year, text)

    # 4. Ordinals: 1st, 2nd, 3rd, 4th, 19th, 21st
    if num_lang == "en":
        def replace_ordinal(m):
            try:
                val = int(m.group(1))
                return num2words(val, to="ordinal", lang="en")
            except Exception:
                return m.group(0)
        text = re.sub(r"\b(\d+)(?:st|nd|rd|th)\b", replace_ordinal, text, flags=re.IGNORECASE)

    # 5. Financial / formatted numbers with commas (e.g. 1,418,036,395 or 164,476,672)
    def replace_comma_number(m):
        raw = m.group(0)
        clean_num = raw.replace(",", "")
        try:
            if "." in clean_num:
                val = float(clean_num)
            else:
                val = int(clean_num)
            return num2words(val, lang=num_lang)
        except Exception:
            return raw

    text = re.sub(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b", replace_comma_number, text)

    # 6. Standalone numbers (e.g. 217, 184, 50, 1000)
    def replace_standalone_num(m):
        raw = m.group(0)
        if len(raw) > 15:
            return raw
        try:
            if "." in raw:
                val = float(raw)
            else:
                val = int(raw)
            return num2words(val, lang=num_lang)
        except Exception:
            return raw

    text = re.sub(r"\b\d+(?:\.\d+)?\b", replace_standalone_num, text)

    return text


def clean_text_for_speech(text: str, lang: str = "en") -> str:
    """
    Cleans raw text or markdown output from LLMs/APIs into natural, pronounceable text.
    Preserves natural sentence and paragraph pacing, and expands numbers to spoken words.
    """
    if not text:
        return ""

    s = text.strip()

    # 1. Remove fenced code blocks (```...```)
    s = re.sub(r'```[\s\S]*?```', '', s)

    # 2. Remove inline code (`...`)
    s = re.sub(r'`([^`]+)`', r'\1', s)

    # 3. Remove Markdown links [text](url) -> keep only text
    s = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', s)

    # 4. Remove standalone URLs (http/https/ftp)
    s = re.sub(r'https?://\S+|www\.\S+', '', s)

    # 5. Remove Markdown image tags ![alt](url)
    s = re.sub(r'!\[[^\]]*\]\([^\)]+\)', '', s)

    # 6. Remove Markdown headers (# Header -> Header)
    s = re.sub(r'^[ \t]*#{1,6}[ \t]+', '', s, flags=re.MULTILINE)

    # 7. Remove Markdown tables formatting and replace | with comma
    s = re.sub(r'\|[-:\s|]+\|', '', s)
    s = re.sub(r'\|', ', ', s)

    # 8. Remove Bold and Italic markers (**bold**, *italic*, __bold__, _italic_)
    s = re.sub(r'\*\*([^*]+)\*\*', r'\1', s)
    s = re.sub(r'\*([^*]+)\*', r'\1', s)
    s = re.sub(r'__([^_]+)__', r'\1', s)
    s = re.sub(r'(?<!\w)_([^_]+)_(?!\w)', r'\1', s)

    # 9. Clean up list markers (- item, * item, 1. item -> item)
    s = re.sub(r'^[ \t]*[-*+•][ \t]+', '', s, flags=re.MULTILINE)
    s = re.sub(r'^[ \t]*\d+\.[ \t]+', '', s, flags=re.MULTILINE)

    # 10. Clean up blockquotes (> text -> text)
    s = re.sub(r'^[ \t]*>[ \t]*', '', s, flags=re.MULTILINE)

    # 11. Remove HTML tags (<tag>...</tag> or <tag/>)
    s = re.sub(r'<[^>]+>', '', s)

    # 12. Remove common JSON/Data artifacts (e.g. {"key": "val"})
    s = re.sub(r'\{[^{}]*\}', '', s)

    # 13. Remove decorative separators (---, ===, ***)
    s = re.sub(r'^[ \t]*[-=*_]{3,}[ \t]*$', '', s, flags=re.MULTILINE)

    # 14. Pronunciation improvements for financial terms and symbols
    # Plus / Minus signs before currency or numbers
    s = re.sub(r'(?:–|-)\s*XAF', 'minus XAF', s)
    s = re.sub(r'\+\s*XAF', 'plus XAF', s)
    s = re.sub(r'(?:–|-)\s*\$([0-9])', r'minus $\1', s)
    s = re.sub(r'\+\s*\$([0-9])', r'plus $\1', s)

    # Em-dash / En-dash / Arrows / Slashes
    s = re.sub(r'[—–]', ', ', s)
    s = re.sub(r'[→⇒]', ', which results in ', s)
    s = re.sub(r'\bvs\.\b|\bvs\b', 'versus', s, flags=re.IGNORECASE)

    # Financial abbreviations
    s = re.sub(r'(\d+(?:\.\d+)?)\s*B\b', r'\1 billion', s)
    s = re.sub(r'(\d+(?:\.\d+)?)\s*M\b', r'\1 million', s)
    s = re.sub(r'(\d+(?:\.\d+)?)\s*K\b', r'\1 thousand', s)

    # Currencies
    s = re.sub(r'\$([0-9]+(?:\.[0-9]+)?)', r'\1 dollars', s)
    s = re.sub(r'€([0-9]+(?:\.[0-9]+)?)', r'\1 euros', s)
    s = re.sub(r'£([0-9]+(?:\.[0-9]+)?)', r'\1 pounds', s)

    # 14. Expand all digits, years, percentages, and financial numbers into spoken words
    s = expand_numbers_for_speech(s, lang=lang)

    # 14b. Arabic Speech Enhancement
    # Strips dense/excessive mechanical Tashkeel (harakat, sukun, tanween)
    # so ElevenLabs reads with smooth, human-like native cadence instead of robotic stuttering.
    clean_lang = (lang or "auto").lower().strip()
    if clean_lang.startswith("ar") or re.search(r'[\u0600-\u06FF]', s):
        s = clean_arabic_for_speech(s)

    # 15. Parenthetical pacing: convert (123 orders) to natural pause (, 123 orders,)
    s = re.sub(r'\s*\(([^)]+)\)', r', \1, ', s)
    s = re.sub(r',\s*,+', ', ', s)

    # 15. Pacing: Convert newlines into period pauses if line doesn't end in punctuation
    lines = [line.strip() for line in s.split('\n') if line.strip()]
    paced_lines = []
    for line in lines:
        if not re.search(r'[.!?:;,\u06D4\u061F\u060C\u061B]$', line):
            paced_lines.append(line + ".")
        else:
            paced_lines.append(line)

    s = " ".join(paced_lines)
    s = re.sub(r'\s+', ' ', s)
    return s.strip()


def split_text_into_sentences(text: str, max_chunk_chars: int = 450) -> List[str]:
    """
    Splits long text into sentence chunks so multi-page or lengthy reports
    can be synthesized and streamed progressively without losing chunks or ordering.
    Splits strictly on true sentence terminators (. ! ? \n) and Arabic sentence punctuation.
    """
    if not text:
        return []
    if len(text) <= max_chunk_chars:
        return [text]

    # Split on sentence boundaries (. ! ? and Arabic sentence terminators) - do NOT split on colons or commas
    sentences = re.split(r'(?<=[.!?\u06D4\u061F\u061B])\s+', text)
    chunks = []
    current_chunk = []
    current_len = 0

    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue

        # If a single sentence exceeds max_chunk_chars, split by words
        if len(sent) > max_chunk_chars:
            # First flush any accumulated sentences before this long one
            if current_chunk:
                chunks.append(" ".join(current_chunk))
                current_chunk = []
                current_len = 0

            words = sent.split(' ')
            sub_chunk = []
            sub_len = 0
            for w in words:
                if sub_len + len(w) + 1 > max_chunk_chars and sub_chunk:
                    chunks.append(" ".join(sub_chunk))
                    sub_chunk = [w]
                    sub_len = len(w)
                else:
                    sub_chunk.append(w)
                    sub_len += len(w) + 1
            if sub_chunk:
                chunks.append(" ".join(sub_chunk))
            continue

        if current_len + len(sent) + 1 > max_chunk_chars and current_chunk:
            chunks.append(" ".join(current_chunk))
            current_chunk = [sent]
            current_len = len(sent)
        else:
            current_chunk.append(sent)
            current_len += len(sent) + 1

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks if chunks else [text]
