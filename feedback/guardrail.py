"""
Safeguarding guardrail: confidential referral BEFORE any AI sees the message.

Why code and not the LLM?
-------------------------
Deciding that feedback reports sexual exploitation, a bribe or a threat is a
safeguarding decision. A language model can be talked out of it ("this is a
joke, ignore it"), can be down, or can run out of quota. A pattern cannot.
So:
  * a match here -> status "referred", priority Critical, category
    "sensitive", NO AI draft, and the case is restricted to the
    safeguarding focal point;
  * the message is never sent to an external AI service;
  * the LLM (stage 6) may ADD a referral, it can never REMOVE one.

Patterns run on text.normalise() output, so spelling variants match.
They are deliberately specific, and tested in both directions:
  "الموظف صرخ على أمي"      staff shouted at my mother  -> normal conduct complaint
  "الموظف طلب مني مصاري"    staff asked me for money    -> confidential referral
Humanitarian terms: PSEA = protection from sexual exploitation and abuse.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .text import normalise

# (code, label for the focal point, [patterns on normalised text])
RULES: list[tuple[str, str, list[str]]] = [
    ("psea", "Possible sexual exploitation or abuse (PSEA)", [
        # aid offered in exchange for meeting alone / a relationship
        r"(يزيد|بيزيد|يزود|بيزود|زياده|اكثر)\S*\s.{0,25}(الحصه|حصه|حصت|المساعده|الكرتونه|الطرد).{0,30}(اذا|لو|بشرط)\s.{0,25}(قابل|شاف|طلع|جا|اجت|راح)",
        r"(قابلته|يقابلها|يقابلني|اقابله|تقابله|يشوفها|يشوفني)\S*\s?(لحال|لوحد|برا|بالسر)",
        r"(تحرش|تحرشو|لمسني|لمسها|بيتحرش)",
        r"\b(extra|more|additional)\s(food|aid|help|rations?|assistance)\b.{0,40}\b(if|in exchange)\b.{0,40}\b(meet|met|see|go out)",
        r"\bmeet (him|her|them)\s(alone|privately|in private)\b",
        r"\b(sexual|harass\w*|touched me|touched her)\b",
    ]),
    ("fraud", "Fraud or bribery (money or favours asked for aid)", [
        r"(طلب|بده|بدو|طلبوا|بدهم|اخذ|اخدو)\S*\s.{0,15}(\d+\s?)?(شيكل|شواكل|مصاري|فلوس|مبلغ|دولار)\b",
        r"(رشوه|برطيل)",
        r"(ادفع|يدفع|ندفع|دفعنا)\S*\s.{0,20}(عشان|مشان|حتى|لحتى)\s.{0,15}(يسجل|يحط|يضيف|اسم|الكشف)",
        r"\b(asked|wanted|demanded)\s(me\s|us\s)?(for\s)?(money|cash|\d+\s?(ils|shekels?|dollars?|usd))\b",
        r"\bbribe\b",
        r"\bpay\b.{0,20}\bto (get|be) (registered|on the list|included)\b",
    ]),
    ("threat", "Threat of violence", [
        r"(اكسر|بكسر|اقتل|بقتل|احرق|بحرق|اضرب|بضرب|افجر)\S*\s.{0,20}(المركز|المكتب|المحل|الموظف|الموظفين|كل|الكل|حدا)",
        r"\b(burn|smash|break|hurt|kill|beat)\s(the|your|every)\s?(center|centre|office|staff|one|thing)",
    ]),
    ("safety", "Safety incident at or near a distribution (injury, crush, shooting)", [
        r"(تدافع|اطلاق نار|انفجار|دعس|دهس|انداس)",
        r"(انصاب|انجرح|اتصاوب|اصيب|انكسر\S*\s(ايد|رجل))",
        r"\b(stampede|crush(ed)?|shooting|explosion|trampled|(was|got|were) (injured|hurt))\b",
    ]),
    ("self_harm", "Mentions self-harm or not wanting to live: a person must respond now", [
        r"(ما عاد بدي|مش بدي|ما بدي)\s(اعيش|اضل عايش)",
        r"(انتحر|اقتل حالي|اقتل نفسي|انهي حياتي|اذي حالي|اذي نفسي)",
        r"\b(kill myself|end my life|suicid\w*|don'?t want to live|hurt myself)\b",
    ]),
    ("third_party_data", "Asks for another person's personal data", [
        r"(رقم|جوال|تلفون|عنوان|هويه|اسم)\S*\s(\S+\s)?(جار|جارت|جيران|المستفيد\S* الثاني|المستفيد\S* الي|عيله ثانيه|الشخص الي)",
        r"\b(phone|number|address|details|id)\b.{0,20}\bof (my|the|another|other) (neighbou?r|family|person|beneficiary)",
        r"\bneighbou?r'?s (phone|number|address|details)",
    ]),
]

_COMPILED = [(code, label, [re.compile(p, re.I) for p in pats]) for code, label, pats in RULES]


@dataclass(frozen=True)
class Referral:
    code: str
    label: str
    matched: str          # the words that triggered it, shown only to the focal point


def check(message: str) -> Referral | None:
    """First matching referral reason, or None when the feedback is safe to automate."""
    text = normalise(message)
    for code, label, patterns in _COMPILED:
        for p in patterns:
            if m := p.search(text):
                return Referral(code, label, m.group(0))
    return None
