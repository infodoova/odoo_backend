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

ENGLISH_WORDS = {
    "the", "be", "to", "of", "and", "a", "in", "that", "have", "i",
    "it", "for", "not", "on", "with", "he", "as", "you", "do", "at",
    "this", "but", "his", "by", "from", "they", "we", "say", "her", "she",
    "or", "an", "will", "my", "one", "all", "would", "there", "their", "what",
    "so", "up", "out", "if", "about", "who", "get", "which", "go", "me",
    "when", "make", "can", "like", "time", "no", "just", "him", "know", "take",
    "people", "into", "year", "your", "good", "some", "could", "them", "see", "other",
    "than", "then", "now", "look", "only", "come", "its", "over", "think", "also",
    "back", "after", "use", "two", "how", "our", "work", "first", "well", "way",
    "even", "new", "want", "because", "any", "these", "give", "day", "most", "us",
    "is", "are", "was", "were", "been", "being", "am", "has", "had", "did", "does",
    "here", "sure", "sales", "report", "total", "revenue", "order", "orders",
    "customer", "customers", "product", "products", "invoice", "invoices", "payment",
    "okay", "ok", "yes", "great", "thanks", "hello", "hi", "hey"
}

FRENCH_WORDS = {
    "le", "la", "les", "des", "du", "un", "une", "dans", "pour", "avec", "est", "sont",
    "sur", "par", "qui", "que", "quoi", "dont", "où", "ce", "cette", "ces", "mon", "ton",
    "son", "notre", "votre", "leur", "nous", "vous", "ils", "elles", "je", "tu", "il", "elle",
    "mais", "ou", "et", "donc", "or", "ni", "car", "pas", "plus", "tout", "tous", "toute",
    "toutes", "faire", "dire", "pouvoir", "aller", "voir", "bonjour", "merci", "salut"
}

SPANISH_WORDS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "en", "para", "por", "con",
    "es", "son", "sobre", "entre", "que", "quien", "cual", "cuyo", "donde", "este", "esta",
    "estos", "estas", "mi", "tu", "su", "nuestro", "vuestro", "nosotros", "vosotros",
    "ellos", "ellas", "yo", "tu", "el", "ella", "usted", "ustedes", "pero", "y", "o",
    "no", "mas", "todo", "todos", "toda", "todas", "hacer", "decir", "poder", "ir", "ver",
    "hola", "gracias", "buenos", "dias", "tardes", "noches"
}

SUPPORTED_LANGUAGES = {"en", "fr", "es", "ar"}


def detect_language(text: str, fallback: str = "en") -> str:
    """
    Detects the target language from the input string with high precision.
    Prioritizes Arabic script, vocabulary heuristics, and markers before statistical langdetect.
    Returns one of: 'ar', 'en', 'fr', 'es'.
    """
    if not text or not text.strip():
        return fallback

    clean_sample = text.strip()

    # 1. Arabic character presence test
    arabic_chars = ARABIC_PATTERN.findall(clean_sample)
    if arabic_chars:
        total_alpha = sum(1 for c in clean_sample if c.isalpha())
        if total_alpha > 0 and (len(arabic_chars) / total_alpha) > 0.15:
            return "ar"
        elif len(arabic_chars) >= 2:
            return "ar"

    words = set(re.findall(r"\b[a-zA-Z\u00C0-\u017F]+\b", clean_sample.lower()))
    french_markers = len(FRENCH_MARKERS.findall(clean_sample))
    spanish_markers = len(SPANISH_MARKERS.findall(clean_sample))
    english_hits = len(words & ENGLISH_WORDS)
    french_hits = len(words & FRENCH_WORDS)
    spanish_hits = len(words & SPANISH_WORDS)

    # 2. Vocabulary & marker arbitration (resolves short phrases like "Sure!", "Here you go", "Sales")
    if (french_markers > 0 or french_hits > 0) and (french_markers + french_hits > english_hits + spanish_hits):
        return "fr"
    if (spanish_markers > 0 or spanish_hits > 0) and (spanish_markers + spanish_hits > english_hits + french_hits):
        return "es"
    if english_hits > 0 and english_hits >= (french_hits + spanish_hits):
        return "en"

    # 3. Statistical langdetect for longer passages
    if len(clean_sample) >= 20 and len(words) >= 3:
        try:
            from langdetect import detect
            detected = detect(clean_sample)
            if detected in SUPPORTED_LANGUAGES:
                # Guard against false French/Spanish detections on English text
                if detected == "fr" and not (french_markers or french_hits) and english_hits > 0:
                    return "en"
                if detected == "es" and not (spanish_markers or spanish_hits) and english_hits > 0:
                    return "en"
                return detected
            elif detected.startswith("ar"):
                return "ar"
            elif detected.startswith("fr") and (french_markers or french_hits):
                return "fr"
            elif detected.startswith("es") and (spanish_markers or spanish_hits):
                return "es"
            elif detected.startswith("en"):
                return "en"
        except Exception as e:
            logger.debug(f"langdetect error: {e}, falling back to heuristic markers")

    # 4. Fallback: If any ASCII Latin letters exist, it is English
    if any(c.isascii() and c.isalpha() for c in clean_sample):
        return "en"

    return fallback
