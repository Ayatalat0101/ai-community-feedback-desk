"""
Replies and questions (template version: the MVP and the fallback), plus the
safety check every draft must pass, template or LLM.

Rules for every draft:
  * In the language of the feedback: Arabic gets Arabic, English gets English.
  * Built on the distribution's REAL status from the lookup:
      Completed -> "we will check the distribution list with {partner}"
      Pending   -> "this distribution has not taken place yet"
      Cancelled -> "this distribution was cancelled"
  * NEVER promises aid, inclusion on a list or compensation: those are
    decisions for the partner. Drafts say what the team WILL CHECK.
  * NEVER asks for an ID number or bank details.
  * Always a draft: a person approves it (stage 4 labels it clearly).
"""
from __future__ import annotations

import re

from .distributions import AR, Lookup, MAX_OPTIONS, option_label
from .models import Category
from .text import normalise

TEAM = {"en": "Community Feedback Team", "ar": "فريق ملاحظات المجتمع"}
GREETING = {"en": "Hello, thank you for contacting the Community Feedback Desk.",
            "ar": "مرحباً، شكراً لتواصلك مع مكتب ملاحظات المجتمع."}
CLOSING = {"en": "With respect,\n{team}", "ar": "مع الاحترام،\n{team}"}


def _d(dist: dict | None, lang: str) -> dict:
    """Distribution fields for a template, in the reply's language."""
    if not dist:
        return {}
    tr = (lambda v: AR.get(v, v)) if lang == "ar" else (lambda v: v)
    return {"dst": dist["distribution_id"], "partner": tr(dist["partner"]), "item": tr(dist["item"]),
            "gov": tr(dist["governorate"]), "date": dist["date"]}


BODY = {
    "not_received_completed": {
        "en": "We are sorry you did not receive the {item} from distribution {dst} ({gov}, {date}). We have asked "
              "{partner} to check the distribution list for this distribution, and we will update you on this reference.",
        "ar": "نأسف لأنك لم تستلم {item} من توزيع {dst} ({gov}، {date}). طلبنا من {partner} مراجعة كشف هذا التوزيع، "
              "وسنبلغك بما نصل إليه على نفس الرقم المرجعي."},
    "problem_completed": {
        "en": "We are sorry about the problem with the {item} from distribution {dst} ({gov}, {date}). We have shared "
              "your report with {partner} so they can check it, and we will update you on this reference.",
        "ar": "نأسف للمشكلة في {item} من توزيع {dst} ({gov}، {date}). شاركنا ملاحظتك مع {partner} للتحقق منها، "
              "وسنبلغك بما نصل إليه على نفس الرقم المرجعي."},
    "pending": {
        "en": "Distribution {dst} ({item}, {gov}, with {partner}) has not taken place yet. {partner} will announce "
              "the date and place. We have recorded your message.",
        "ar": "توزيع {dst} ({item}، {gov}، مع {partner}) لم يتم بعد، وستعلن {partner} موعده ومكانه. "
              "سجّلنا رسالتك."},
    "cancelled": {
        "en": "We are sorry for the trouble. Distribution {dst} ({item}, {gov}, planned for {date}) was cancelled, "
              "so it did not take place. We will share information about any replacement distribution once it is confirmed.",
        "ar": "نعتذر عن التعب. توزيع {dst} ({item}، {gov}، المخطط في {date}) أُلغي ولم يتم. "
              "سنشارك أي معلومات عن توزيع بديل عندما يتأكد."},
    "info_pending": {
        "en": "The next planned {item} distribution in {gov} is {dst}, with {partner}. It has not taken place yet, "
              "and {partner} will announce the date and place.",
        "ar": "التوزيع القادم المخطط لـ{item} في {gov} هو {dst} مع {partner}. لم يتم بعد، "
              "وستعلن {partner} موعده ومكانه."},
    "info_register": {
        "en": "Registration is done by the partner organisations in each area. A team member will reply with the "
              "steps for your area. Please do not share ID numbers in this form.",
        "ar": "التسجيل يتم عن طريق المؤسسات الشريكة في كل منطقة. سيرد عليك أحد أفراد الفريق بالخطوات الخاصة بمنطقتك. "
              "لا ترسل أرقام الهوية في هذا النموذج."},
    "info_general": {
        "en": "Thank you for your question. A team member will reply to you with the information.",
        "ar": "شكراً على سؤالك. سيرد عليك أحد أفراد الفريق بالمعلومات."},
    "conduct": {
        "en": "Thank you for telling us. Every report about staff behaviour is reviewed by a supervisor, and we have "
              "shared it with {partner_or_team}. We will update you on this reference.",
        "ar": "شكراً لإخبارنا. كل ملاحظة عن سلوك الموظفين يراجعها مشرف، وقد شاركناها مع {partner_or_team}. "
              "سنبلغك بما نصل إليه على نفس الرقم المرجعي."},
    "access": {
        "en": "Thank you for telling us. We have shared this with {partner_or_team} so that people who cannot wait "
              "long or travel far can be reached. A team member will follow up with you on this reference.",
        "ar": "شكراً لإخبارنا. شاركنا هذا مع {partner_or_team} حتى يتم الوصول للأشخاص الذين لا يستطيعون الانتظار "
              "طويلاً أو قطع مسافة بعيدة. سيتابع معك أحد أفراد الفريق على نفس الرقم المرجعي."},
    "appreciation": {
        "en": "Thank you for your kind words. We will share them with {partner_or_team}.",
        "ar": "شكراً على كلماتك الطيبة، سننقلها إلى {partner_or_team}."},
}

QUESTIONS = {
    "no_info": {
        "en": "Which distribution is this about? Please send the distribution number (it looks like DST-017), "
              "or the area and the item (for example: blankets in North Gaza).",
        "ar": "عن أي توزيع تتحدث؟ أرسل رقم التوزيع (يكون مثل DST-017)، أو المنطقة والمادة "
              "(مثلاً: بطانيات في شمال غزة)."},
    "no_match": {
        "en": "We could not find a distribution that matches. Please send the distribution number (it looks like "
              "DST-017), or the partner and the date.",
        "ar": "لم نجد توزيعاً مطابقاً. أرسل رقم التوزيع (يكون مثل DST-017)، أو اسم المؤسسة والتاريخ."},
    "not_found_id": {
        "en": "We could not find distribution {asked}. Please check the number (it looks like DST-017), "
              "or tell us the area and the item.",
        "ar": "لم نجد التوزيع {asked}. تأكد من الرقم (يكون مثل DST-017)، أو أخبرنا بالمنطقة والمادة."},
    "multiple": {
        "en": "{n} distributions match. Which one do you mean?",
        "ar": "يوجد {n} توزيعات مطابقة. أيّها تقصد؟"},
    "too_many": {
        "en": "{n} distributions match. Please add the partner, the item or the date, or send the distribution number.",
        "ar": "يوجد {n} توزيعاً مطابقاً. أضف اسم المؤسسة أو المادة أو التاريخ، أو أرسل رقم التوزيع."},
}
_REGISTER = re.compile(r"(اسجل|بسجل|تسجيل|سجل|الكشف|كشوفات)|\bregist\w*", re.I)
_PROBLEM = re.compile(r"(ناقص|نقص|خربان|تالف|مبلول|منتهي|مكسور|عفن)|\b(missing|expired|damaged|spoil\w*|broken|rotten)\b", re.I)


def question_for(lookup: Lookup, language: str) -> tuple[str, list[str]]:
    """ONE question when the distribution is unclear, plus the options to choose from."""
    lang = language if language in ("en", "ar") else "ar"
    if lookup.outcome == "multiple":
        n = len(lookup.matches)
        if n > MAX_OPTIONS:
            return QUESTIONS["too_many"][lang].format(n=n), []
        return QUESTIONS["multiple"][lang].format(n=n), [option_label(m, lang) for m in lookup.matches]
    key = lookup.outcome if lookup.outcome in QUESTIONS else "no_info"
    return QUESTIONS[key][lang].format(asked=lookup.asked_id or ""), []


def body_key(category: Category, rule: str, lookup: Lookup, message: str) -> str:
    dist = lookup.distribution
    category = Category(category)
    if category is Category.DISTRIBUTION and dist:
        if dist["status"] == "Cancelled":
            return "cancelled"
        if dist["status"] == "Pending":
            return "pending"
        return "not_received_completed" if rule == "H1" or not _PROBLEM.search(normalise(message)) else "problem_completed"
    if category is Category.INFORMATION:
        if dist and dist["status"] == "Pending":
            return "info_pending"
        return "info_register" if _REGISTER.search(normalise(message)) else "info_general"
    return {Category.CONDUCT: "conduct", Category.ACCESS: "access", Category.APPRECIATION: "appreciation"}.get(
        category, "info_general")


def template_draft(message: str, category: Category, rule: str, language: str, lookup: Lookup) -> str:
    lang = language if language in ("en", "ar") else "ar"
    fields = _d(lookup.distribution, lang)
    partner = lookup.hints.one("partners")
    team = {"en": "the distribution team", "ar": "فريق التوزيع"}[lang]
    fields["partner_or_team"] = fields.get("partner") or (AR.get(partner, partner) if lang == "ar" else partner) or team
    body = BODY[body_key(category, rule, lookup, message)][lang].format(**fields)
    return f"{GREETING[lang]}\n\n{body}\n\n{CLOSING[lang].format(team=TEAM[lang])}"


# --- safety check applied to EVERY draft (templates now, LLM in stage 6) --------------------
FORBIDDEN = [
    ("asks for ID or bank details", re.compile(
        r"\b(send|share|give|provide|confirm|tell us)\b[^.?!]{0,40}\b(id|identity|passport|bank|account|card) (number|details|card)\b"
        r"|(ارسل|ابعث|اعطنا|زودنا|اكتب لنا|ارفق)[^.؟!]{0,30}(رقم الهويه|صوره الهويه|الهويه|حساب|رقم الحساب|البنك)", re.I)),
    ("promises aid or inclusion", re.compile(
        r"\b(we will|we'll|you will|you'll)\s(give you|send you|deliver|receive|get (a|your|the)|add you|include you|replace)"
        r"|\b(guarantee\w*|compensat\w*)\b"
        r"|(سنعطيك|سنرسل لك|ستستلم|ستحصل|سنضيفك|سنضمك|سنعوضك|نضمن|سيتم تعويضك|سيتم اضافتك)", re.I)),
]
NEGATION = re.compile(r"(\bnot|\bnever|n't|\bno|لا|لن|ما)\s*$")
DST_IN_TEXT = re.compile(r"\bDST[-\s]?(\d{3})\b", re.I)
PLACEHOLDER = re.compile(r"\[[^\]]{1,30}\]|\{[^}]{1,30}\}|<[^>]{1,30}>")
ARABIC_LETTER = re.compile(r"[ء-ي]")
MAX_DRAFT_CHARS = 1200


def check_draft(text: str, language: str | None = None, distribution_id: str | None = None) -> list[str]:
    """Problems found in a draft; an empty list means it can go to a reviewer.
    A negated match ("do NOT send ID numbers") is the safe advice we want, so
    the 15 characters before each match are checked for a negation."""
    t = normalise(text)
    problems: list[str] = []
    for name, pattern in FORBIDDEN:
        for m in pattern.finditer(t):
            if not NEGATION.search(t[max(0, m.start() - 15):m.start()]):
                problems.append(name)
                break
    if not t:
        return problems + ["empty"]
    if language in ("ar", "en"):
        letters = [c for c in text if c.isalpha()]
        arabic_share = sum(bool(ARABIC_LETTER.match(c)) for c in letters) / max(len(letters), 1)
        if (language == "ar" and arabic_share < 0.6) or (language == "en" and arabic_share > 0.2):
            problems.append("wrong language")
        mentioned = {m for m in DST_IN_TEXT.findall(text)}
        allowed = {distribution_id[-3:]} if distribution_id else set()
        if mentioned - allowed:
            problems.append("mentions a distribution that is not this one")
    if PLACEHOLDER.search(text):
        problems.append("contains a placeholder")
    if len(text) > MAX_DRAFT_CHARS:
        problems.append("too long")
    return problems
