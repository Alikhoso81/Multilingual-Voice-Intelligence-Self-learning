"""
Language identification and normalization for the multilingual pipeline.

Faster-Whisper reports a single language code per audio segment (e.g. "en", "ur"),
which is NOT enough on its own for our use case, because:
  - Roman Urdu (Urdu written in Latin script) gets misclassified as English by
    Whisper's language ID, since it only looks at the script/acoustic signal,
    not the actual vocabulary.
  - Code-switched sentences (Urdu + English mixed in one utterance) have no
    single correct "language" label.

So we use Whisper's language guess as a starting signal, then run a lightweight
heuristic pass over the ROMANIZED TEXT to catch Roman Urdu and mixed cases.
This is intentionally simple (word-list based) for Phase 2 — it is good enough to
route text correctly downstream, and can be swapped for a trained classifier later
without changing any calling code, since callers only depend on `detect_language()`.
"""
import re

from app.models.conversation_message import DetectedLanguage

# Common Roman Urdu function words / markers. Not exhaustive by design —
# this only needs to catch ENOUGH signal to distinguish Roman Urdu from English,
# not to be a full language model.
ROMAN_URDU_MARKERS = {
    "hai", "hain", "ho", "hoon", "tha", "thi", "the", "kyun", "kyu", "kya",
    "nahi", "nahin", "mera", "meri", "mere", "aap", "tum", "hum", "main",
    "karo", "kro", "karna", "krna", "raha", "rahi", "rha", "rhi", "abhi",
    "kab", "kaha", "kahan", "kaise", "kese", "acha", "theek", "bilkul",
    "shukriya", "please", "plz", "sir", "madam", "bhai", "yaar",
}

URDU_SCRIPT_RE = re.compile(r"[\u0600-\u06FF]")


def detect_language(text: str, whisper_language_hint: str | None = None) -> DetectedLanguage:
    """
    Determine the DetectedLanguage for a piece of transcribed/typed text.

    `whisper_language_hint` is the language code Faster-Whisper itself reported
    (may be wrong for Roman Urdu, as noted above) — used as a fallback signal only.
    """
    if not text or not text.strip():
        return DetectedLanguage.unknown

    if URDU_SCRIPT_RE.search(text):
        # Contains native Urdu script characters.
        # If there's ALSO a meaningful amount of Latin text, call it mixed.
        latin_ratio = _latin_word_ratio(text)
        return DetectedLanguage.mixed if latin_ratio > 0.3 else DetectedLanguage.urdu

    words = _tokenize(text)
    if not words:
        return DetectedLanguage.unknown

    roman_urdu_hits = sum(1 for w in words if w in ROMAN_URDU_MARKERS)
    roman_urdu_ratio = roman_urdu_hits / len(words)

    if roman_urdu_ratio >= 0.35:
        return DetectedLanguage.roman_urdu
    if 0.08 <= roman_urdu_ratio < 0.35:
        # Some Roman Urdu markers mixed into otherwise-English sentence structure.
        return DetectedLanguage.mixed

    # No strong Roman Urdu signal — trust Whisper's hint if it's English,
    # otherwise default to english since Latin script with no markers is
    # most likely plain English.
    if whisper_language_hint and whisper_language_hint != "en":
        # Whisper thinks it's some other language but there's no Urdu script
        # and no roman-urdu markers — flag as unknown rather than guessing wrong.
        return DetectedLanguage.unknown
    return DetectedLanguage.english


def normalize_text(text: str, language: DetectedLanguage) -> str:
    """
    Produce a canonical normalized form used for intent classification, RAG
    embedding, and question clustering — WITHOUT discarding the original text
    (raw_text is always stored separately, this is only the derived field).

    Phase 2 normalization is intentionally light: whitespace/punctuation cleanup
    and lowercasing for Latin-script text. Deeper normalization (e.g. mapping
    Roman Urdu spelling variants like "kyun"/"kyu"/"q" to one canonical spelling)
    is a Phase 5+ concern once we have real conversation data to base a mapping on.
    """
    cleaned = re.sub(r"\s+", " ", text).strip()
    if language in (DetectedLanguage.english, DetectedLanguage.roman_urdu, DetectedLanguage.mixed):
        cleaned = cleaned.lower()
    return cleaned


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z]+", text.lower())


def _latin_word_ratio(text: str) -> float:
    total_chars = len(re.sub(r"\s", "", text))
    if total_chars == 0:
        return 0.0
    latin_chars = len(re.findall(r"[a-zA-Z]", text))
    return latin_chars / total_chars
