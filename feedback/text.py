"""
Text helpers shared by the guardrail, the policy and the rule classifier.

Why normalise Arabic?
---------------------
The same word is typed many ways: "إستلمت", "استلمت", "أستلمت"; "الحصة" /
"الحصه"; "مـصـاري" with tatweel. Before matching we remove diacritics and
tatweel, unify alef forms (أ إ آ -> ا), taa marbuta (ة -> ه) and alef
maqsura (ى -> ي), and turn Arabic-Indic digits into 0-9 (٥٠ -> 50).
Every pattern in this project is then written once, in normalised form.
"""
from __future__ import annotations

import re

_DIACRITICS = re.compile(r"[ً-ْٰـ]")      # harakat, shadda, superscript alef, tatweel
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_ARABIC_LETTER = re.compile(r"[؀-ۿ]")


def normalise(text: str) -> str:
    """Lower-case Latin, normalised Arabic, single spaces."""
    t = (text or "").translate(_ARABIC_DIGITS)
    t = _DIACRITICS.sub("", t)
    t = re.sub("[أإآٱ]", "ا", t).replace("ة", "ه").replace("ى", "ي")
    return re.sub(r"\s+", " ", t).strip().casefold()


def detect_language(text: str) -> str:
    """'ar' if most letters are Arabic, else 'en'. Decides the reply language.
    Distribution IDs, phone numbers and our own labels are ignored: they are
    not the person's language (a lesson from the previous version, where an
    English label turned an Arabic customer's reply into English)."""
    text = re.sub(r"\bDST[-\s]?\d{3}\b|\[Follow-up\]|\+?\d[\d\s-]{6,}", " ", text or "", flags=re.I)
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "ar"                       # most feedback in this context is Arabic
    arabic = sum(1 for c in letters if _ARABIC_LETTER.match(c))
    return "ar" if arabic / len(letters) >= 0.5 else "en"


def is_arabic(text: str) -> bool:
    return detect_language(text) == "ar"
