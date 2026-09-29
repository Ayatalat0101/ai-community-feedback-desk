"""
Rule-based classifier: the baseline and the fallback when the LLM is down.

It is not "the AI". It is what the AI must beat, and the safety net that
keeps the desk working when Gemini's quota runs out.

How it decides:
  1. A question with no complaint in it ("متى التوزيع الجاي؟", "how do I
     register?") is `information`.
  2. Otherwise each category scores points for its words (Arabic, Gaza
     dialect, English) on normalised text. Complaint words count double,
     so "شكراً بس ما استلمت" is a distribution problem, not appreciation.
  3. Highest score wins; nothing matched -> `information`.
The reason names the words that decided, so an officer can check it.
`sensitive` is never chosen here: only a referral sets it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Category
from .text import normalise

KEYWORDS: dict[Category, list[tuple[str, int]]] = {
    Category.DISTRIBUTION: [
        (r"(ما|مش|لم)\s?(استلمت|استلمنا|وصلني|وصلنا|اخذت|اخدت|اخذنا|اجاني|اجانا)", 3),
        (r"(ناقص|نقص|خربان|خربانه|تالف|مبلول|مبلوله|منتهي|مكسور|عفن|غلط)", 2),
        (r"(الكرتونه|كرتونه|الطرد|طرد|الطحين|طقم|بطانيات|الحصه)", 1),
        (r"\b(didn'?t|did not|never|not)\s(receive|received|get|got)\b|\bnobody was there\b", 3),
        (r"\b(missing|expired|damaged|spoiled|spoilt|broken|rotten|wrong item)\b", 2),
        (r"\b(parcel|kit|kits|blankets?|ration)\b", 1),
    ],
    Category.CONDUCT: [
        (r"(الموظف|موظف|الموظفين|المتطوع|العامل)", 2),
        (r"(صرخ|صرخوا|اهان|اهانه|وقح|شتم|سب|واسطه|قرايب|محسوبيه|تمييز|ميزوا|فضلوا)", 2),
        (r"\b(staff|worker|volunteer|employee)s?\b", 2),
        (r"\b(rude|shouted|shouting|insulted|yelled|favou?rit\w*|relatives|skip(ped)? the queue|unfair)\b", 2),
    ],
    Category.ACCESS: [
        (r"(بعيد|بعيده|المسافه|مواصلات|الطابور|طابور|ساعات|بالشمس|الشمس|كرسي متحرك|حامل|ما قدر\S* يوصل|ما قدرت|زحمه)", 2),
        (r"\b(far|distance|transport|queue|line|hours|sun|wheelchair|pregnant|could not reach|couldn'?t reach|crowded)\b", 2),
    ],
    Category.APPRECIATION: [
        (r"(شكرا|يعطيكم العافيه|الله يجزيكم|جزاكم الله|ممتاز|منظم|تنظيم ممتاز)", 1),
        (r"\b(thank|thanks|grateful|great job|well organi[sz]ed|excellent)\b", 1),
    ],
}
QUESTION = re.compile(r"(^|\s)(متي|امتي|وين|كيف|هل|شو|ايش|كم)\s|\?|؟|\b(when|where|how|what|can i|is there)\b", re.I)
COMPLAINT = re.compile("|".join(p for cat in (Category.DISTRIBUTION, Category.CONDUCT)
                                 for p, w in KEYWORDS[cat] if w >= 2), re.I)

_COMPILED = {cat: [(re.compile(p, re.I), w) for p, w in pats] for cat, pats in KEYWORDS.items()}
TIE_ORDER = [Category.DISTRIBUTION, Category.ACCESS, Category.CONDUCT, Category.APPRECIATION]


@dataclass
class Classification:
    category: Category
    reason: str
    planner: str = "rules"
    refer: bool = False              # the LLM may flag "a person must see this" (stage 6); rules never do
    refer_reason: str = ""


def classify(message: str, language: str = "ar") -> Classification:
    text = normalise(message)
    if QUESTION.search(text) and not COMPLAINT.search(text):
        return Classification(Category.INFORMATION, "A question with no complaint in it.")
    scores, hits = {}, {}
    for cat, patterns in _COMPILED.items():
        found = [(m.group(0).strip(), w) for p, w in patterns for m in p.finditer(text)]
        scores[cat] = sum(w for _, w in found)
        hits[cat] = sorted({word for word, _ in found})
    best = max(TIE_ORDER, key=lambda c: (scores[c], -TIE_ORDER.index(c)))
    if scores[best] == 0:
        return Classification(Category.INFORMATION, "No complaint, access, staff or thanks words found.")
    words = ", ".join(f"'{w}'" for w in hits[best][:4])
    return Classification(best, f"Matched {best.value} words: {words}.")
