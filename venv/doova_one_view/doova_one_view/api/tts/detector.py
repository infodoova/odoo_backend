"""
Language detector for Text-To-Speech (TTS).
Accurately identifies Arabic, English, French, and Spanish text.
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Arabic Unicode Block Range (covers Arabic, Arabic Supplement, Extended, Presentation Forms)
ARABIC_PATTERN = re.compile(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]')

# Specific diacritics / markers common in French & Spanish
FRENCH_MARKERS = re.compile(r'[àâçéèêëîïôûùüÿæœÀÂÇÉÈÊËÎÏÔÛÙÜŸÆŒ]', re.IGNORECASE)
SPANISH_MARKERS = re.compile(r'[áéíóúüñ¿¡ÁÉÍÓÚÜÑ]', re.IGNORECASE)

SUPPORTED_LANGUAGES = {"en", "fr", "es", "ar"}


def detect_language(text: str, fallback: str = "en") -> str:
    """
    Detects the target language from the input string.
    Returns one of: 'ar', 'en', 'fr', 'es'.
    """
    if not text or not text.strip():
        return fallback

    clean_sample = text.strip()

    # 1. Fast Arabic character presence test
    # If more than 15% of characters or multiple Arabic words are present, classify as Arabic
    arabic_chars = ARABIC_PATTERN.findall(clean_sample)
    if arabic_chars:
        # Check ratio of Arabic characters
        total_alpha = sum(1 for c in clean_sample if c.isalpha())
        if total_alpha > 0 and (len(arabic_chars) / total_alpha) > 0.15:
            return "ar"
        elif len(arabic_chars) >= 2:
            return "ar"

    # 2. Try langdetect for high-accuracy multilingual detection
    try:
        from langdetect import detect
        detected = detect(clean_sample)
        if detected in SUPPORTED_LANGUAGES:
            return detected
        elif detected.startswith("ar"):
            return "ar"
        elif detected.startswith("fr"):
            return "fr"
        elif detected.startswith("es"):
            return "es"
        elif detected.startswith("en"):
            return "en"
    except Exception as e:
        logger.debug(f"langdetect error: {e}, falling back to heuristic markers")

    # 3. Heuristic fallback based on specific characters
    if SPANISH_MARKERS.search(clean_sample):
        return "es"
    if FRENCH_MARKERS.search(clean_sample):
        return "fr"

    return fallback
