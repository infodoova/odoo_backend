"""
Text cleaner for Text-To-Speech (TTS).
Strips Markdown, code blocks, URLs, tables, and special formatting to produce natural spoken text.
Paces headings and bullet points with natural punctuation pauses, and expands financial abbreviations.
"""

import re
from typing import List


def clean_text_for_speech(text: str) -> str:
    """
    Cleans raw text or markdown output from LLMs/APIs into natural, pronounceable text.
    Preserves natural sentence and paragraph pacing.
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


def split_text_into_sentences(text: str, max_chunk_chars: int = 500) -> List[str]:
    """
    Splits long text into sentence chunks so multi-page or lengthy reports
    can be synthesized and streamed progressively without losing chunks or ordering.
    Splits on sentence terminators (. ! ? : \n) and Arabic punctuation (؟ ، ؛).
    """
    if not text:
        return []
    if len(text) <= max_chunk_chars:
        return [text]

    # Split on sentence boundaries
    sentences = re.split(r'(?<=[.!?:\u06D4\u061F\u060C\u061B])\s+', text)
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
