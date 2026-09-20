"""
Arabic Tashkeel (Diacritization) Module for Text-To-Speech.
Ensures Arabic text sent to ElevenLabs and presented to users has complete, natural,
and grammatically sound diacritics (Fatha, Damma, Kasra, Sukun, Shadda, Tanween).
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Arabic unicode ranges
ARABIC_LETTERS_PATTERN = re.compile(r'[\u0621-\u064A\u0671-\u06D3]')
# Diacritics: Fathatan, Dammatan, Kasratan, Fatha, Damma, Kasra, Shadda, Sukun, Superscript Alef
ARABIC_HARAKAT_PATTERN = re.compile(r'[\u064B-\u0652\u0670]')

# Lazy-loaded Mishkal vocalizer instance
_vocalizer = None


def get_vocalizer():
    global _vocalizer
    if _vocalizer is None:
        try:
            from mishkal.tashkeel import TashkeelClass
            _vocalizer = TashkeelClass()
        except ImportError:
            logger.warning("mishkal not installed. Arabic diacritization fallback will use rule-based dictionary.")
            _vocalizer = False
    return _vocalizer


# Curated financial and business lexicon with perfect vocalization for ElevenLabs
FINANCIAL_VOCALIZATION_DICT = {
    # Percentages and units
    r'\bبالمائة\b': 'بِالمِائَةِ',
    r'\bبالمئة\b': 'بِالمِائَةِ',
    r'\bفي المائة\b': 'فِي المِائَةِ',
    r'\bفي المئة\b': 'فِي المِائَةِ',
    r'\bنسبة\b': 'نِسْبَةُ',
    r'\bبنسبة\b': 'بِنِسْبَةِ',

    # Currencies
    r'\bفرنك إفريقي\b': 'فِرَنْكٍ إِفْرِيقِيٍّ',
    r'\bفرنك افريقي\b': 'فِرَنْكٍ إِفْرِيقِيٍّ',
    r'\bفرنك\b': 'فِرَنْك',
    r'\bفرنكات\b': 'فِرَنْكَاتٍ',
    r'\bريال سعودي\b': 'رِيَالٍ سُعُودِيٍّ',
    r'\bريال\b': 'رِيَالٍ',
    r'\bريالات\b': 'رِيَالَاتٍ',
    r'\bدولار أمريكي\b': 'دُولَارٍ أَمْرِيكِيٍّ',
    r'\bدولار\b': 'دُولَارٍ',
    r'\bدولارات\b': 'دُولَارَاتٍ',
    r'\bيورو\b': 'يُورُو',
    r'\bدرهم إماراتي\b': 'دِرْهَمٍ إِمَارَاتِيٍّ',
    r'\bدرهم\b': 'دِرْهَمٍ',
    r'\bجنيه\b': 'جُنَيْهٍ',

    # Business terms
    r'\bإجمالي الإيرادات\b': 'إِجْمَالِيُّ الإِيرَادَاتِ',
    r'\bاجمالي الايرادات\b': 'إِجْمَالِيُّ الإِيرَادَاتِ',
    r'\bإجمالي المبيعات\b': 'إِجْمَالِيُّ المَبِيعَاتِ',
    r'\bاجمالي المبيعات\b': 'إِجْمَالِيُّ المَبِيعَاتِ',
    r'\bصافي الربح\b': 'صَافِي الرِّبْحِ',
    r'\bصافي الأرباح\b': 'صَافِي الأَرْبَاحِ',
    r'\bأرباح\b': 'أَرْبَاحٌ',
    r'\bالأرباح\b': 'الأَرْبَاحُ',
    r'\bإيرادات\b': 'إِيرَادَاتٌ',
    r'\bالإيرادات\b': 'الإِيرَادَاتُ',
    r'\bمصروفات\b': 'مَصْرُوفَاتٌ',
    r'\bالمصروفات\b': 'المَصْرُوفَاتُ',
    r'\bالتكاليف\b': 'التَّكَالِيفُ',
    r'\bتكلفة المبيعات\b': 'تَكْلُفَةُ المَبِيعَاتِ',
    r'\bتكلفة البضاعة المباعة\b': 'تَكْلُفَةُ البِضَاعَةِ المُبَاعَةِ',
    r'\bحسابات العملاء\b': 'حِسَابَاتُ العُمَلَاءِ',
    r'\bحسابات الموردين\b': 'حِسَابَاتُ المُوَرِّدِينَ',
    r'\bفواتير\b': 'فَوَاتِيرُ',
    r'\bالفواتير\b': 'الفَوَاتِيرُ',
    r'\bفاتورة\b': 'فَاتُورَةٌ',
    r'\bالفاتورة\b': 'الفَاتُورَةُ',
    r'\bميزانية عمومية\b': 'مِيزَانِيَّةٌ عُمُومِيَّةٌ',
    r'\bقائمة الدخل\b': 'قَائِمَةُ الدَّخْلِ',
    r'\bتدفقات نقدية\b': 'تَدَفُّقَاتٌ نَقْدِيَّةٌ',
    r'\bالتدفق النقدي\b': 'التَّدَفُّقُ النَّقْدِيُّ',
    r'\bرصيد البنك\b': 'رَصِيدُ البَنْكِ',
    r'\bالسيولة\b': 'السُّيُولَةُ',
    r'\bالمخزون\b': 'المَخْزُونُ',

    # Verbs common in business updates
    r'\bبلغت\b': 'بَلَغَتْ',
    r'\bسجلت\b': 'سَجَّلَتْ',
    r'\bارتفعت\b': 'ارْتَفَعَتْ',
    r'\bانخفضت\b': 'انْخَفَضَتْ',
    r'\bتم تحصيل\b': 'تَمَّ تَحْصِيلُ',
    r'\bتم سداد\b': 'تَمَّ سَدَادُ',
    r'\bيصل إلى\b': 'يَصِلُ إِلَى',
    r'\bمقارنة بـ\b': 'مُقَارَنَةً بِـ',
    r'\bمقارنة ب\b': 'مُقَارَنَةً بِـ',
}


def has_sufficient_tashkeel(text: str, min_density: float = 0.20) -> bool:
    """
    Checks whether Arabic text has sufficient diacritization.
    min_density is the ratio of harakat (diacritics) to Arabic base letters.
    """
    if not text:
        return False
    arabic_letters = len(ARABIC_LETTERS_PATTERN.findall(text))
    if arabic_letters == 0:
        return True  # Non-Arabic text doesn't need Arabic tashkeel

    harakat = len(ARABIC_HARAKAT_PATTERN.findall(text))
    density = harakat / arabic_letters
    return density >= min_density


has_tashkeel = has_sufficient_tashkeel


def clean_arabic_for_speech(text: str) -> str:
    """
    Cleans and prepares Arabic text for ElevenLabs Neural TTS.
    Strips excessive mechanical Tashkeel (harakat, sukun, tanween) so ElevenLabs
    speaks with natural, fluid native cadence without robotic stuttering or awkward pauses.
    """
    if not text or not ARABIC_LETTERS_PATTERN.search(text):
        return text

    try:
        from pyarabic.araby import strip_tashkeel
        cleaned = strip_tashkeel(text)
    except ImportError:
        cleaned = ARABIC_HARAKAT_PATTERN.sub('', text)

    # Clean up duplicate spaces
    cleaned = re.sub(r'[ ]{2,}', ' ', cleaned)
    return cleaned.strip()


def vocalize_arabic_text(text: str, force: bool = False) -> str:
    """
    Enriches Arabic text with accurate Tashkeel (diacritics).
    If text already has sufficient Tashkeel (e.g. directly generated by AI with full Tashkeel),
    it preserves existing diacritics and applies targeted domain improvements.
    If text has little or no Tashkeel (e.g. expanded numbers, user prompts), it applies
    Mishkal diacritization and financial vocabulary harmonization.
    """
    if not text or not ARABIC_LETTERS_PATTERN.search(text):
        return text

    result = text

    # If text lacks sufficient diacritization, run through Mishkal vocalizer
    if force or not has_sufficient_tashkeel(result, min_density=0.25):
        vocalizer = get_vocalizer()
        if vocalizer:
            try:
                # Vocalize line by line to preserve line breaks and formatting
                lines = result.split('\n')
                vocalized_lines = []
                for line in lines:
                    if ARABIC_LETTERS_PATTERN.search(line):
                        vocalized_lines.append(vocalizer.tashkeel(line))
                    else:
                        vocalized_lines.append(line)
                result = '\n'.join(vocalized_lines)
            except Exception as e:
                logger.warning(f"Mishkal vocalization encountered error: {e}")

    # Post-process with domain financial dictionary for perfect ElevenLabs cadence
    for pattern, replacement in FINANCIAL_VOCALIZATION_DICT.items():
        result = re.sub(pattern, replacement, result)

    # Clean up double diacritics or awkward spacing around diacritics
    result = re.sub(r'[\u064B-\u0652]{2,}', lambda m: m.group(0)[-1] if '\u0651' not in m.group(0) else ('\u0651' + [c for c in m.group(0) if c != '\u0651'][-1]), result)
    result = re.sub(r'[ ]{2,}', ' ', result)

    return result.strip()
