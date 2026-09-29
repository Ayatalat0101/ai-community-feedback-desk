"""
The agent's TOOL: find the distribution a piece of feedback is about,
in the same aid_distributions.csv that Project 1 analyses.

Why a tool, and why code?
-------------------------
"Which distribution?" is a FACT, not an opinion. If a language model guessed
"DST-029", the officer would investigate the wrong partner. So the agent
calls this function, which only returns distributions that exist in the file,
and the answer is one of:

  found         exactly one distribution         -> link it, use its status
  multiple      several match (e.g. 5 blanket    -> ask ONE question and offer
                distributions in North Gaza)        them as options
  not_found_id  a DST number that does not exist -> ask to check the number
  no_match      place / item given, nothing fits -> ask for the number
  no_info       nothing to search with           -> ask for the number or place + item

People say places, partners and items in Arabic, dialect or English
("بطانيات بالشمال", "سند", "blankets in North Gaza"), so each value has a
list of names, matched on normalised text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pandas as pd

from .models import normalise_dst
from .text import normalise

DATA = Path(__file__).parent.parent / "data" / "aid_distributions.csv"
MAX_OPTIONS = 6          # more than this is not a useful multiple-choice question

# value in the CSV -> names people use (normalised Arabic + English). Longest names first.
GOVERNORATE_NAMES = {
    "North Gaza": ["شمال غزه", "الشمال", "بالشمال", "جباليا", "بيت لاهيا", "north gaza", "jabalia"],
    "Gaza City": ["مدينه غزه", "غزه المدينه", "الرمال", "الشجاعيه", "gaza city"],
    "Deir al-Balah": ["دير البلح", "deir al-balah", "deir al balah", "deir el-balah", "deir el balah"],
    "Khan Younis": ["خان يونس", "خانيونس", "khan younis", "khan yunis", "khan younes"],
    "Rafah": ["رفح", "rafah"],
}
PARTNER_NAMES = {
    "Nour Relief": ["نور للاغاثه", "نور", "nour relief", "nour"],
    "Sanad Aid": ["سند", "sanad aid", "sanad"],
    "Amal Foundation": ["مؤسسه امل", "امل", "amal foundation", "amal"],
    "Rahma Network": ["شبكه رحمه", "رحمه", "rahma network", "rahma"],
}
ITEM_NAMES = {
    "Food Parcel": ["طرد غذائي", "طرد الغذاء", "طرود غذائيه", "طرد", "طرود", "الكرتونه", "كرتونه", "طحين",
                    "food parcels", "food parcel", "food"],
    "Blanket": ["بطانيات", "بطانيه", "حرامات", "حرام", "blankets", "blanket"],
    "Winter Kit": ["حقيبه شتويه", "حقائب شتويه", "كسوه شتاء", "شتويه", "winter kits", "winter kit", "winter"],
    "Kitchen Set": ["طقم المطبخ", "طقم مطبخ", "ادوات مطبخ", "ادوات المطبخ", "kitchen sets", "kitchen set", "kitchen"],
    "Hygiene Kit": ["حقيبه نظافه", "مواد نظافه", "نظافه", "hygiene kits", "hygiene kit", "hygiene"],
}
_FUTURE = re.compile(r"(متي|امتي|الجاي|القادم|الجايه|القادمه|رح يصير|بيصير)|\b(when|next|upcoming|will it)\b", re.I)

# Arabic words for the options and templates
AR = {
    "North Gaza": "شمال غزة", "Gaza City": "مدينة غزة", "Deir al-Balah": "دير البلح",
    "Khan Younis": "خان يونس", "Rafah": "رفح",
    "Nour Relief": "نور للإغاثة", "Sanad Aid": "مؤسسة سند", "Amal Foundation": "مؤسسة أمل",
    "Rahma Network": "شبكة رحمة",
    "Food Parcel": "طرد غذائي", "Blanket": "بطانيات", "Winter Kit": "حقيبة شتوية",
    "Kitchen Set": "طقم مطبخ", "Hygiene Kit": "حقيبة نظافة",
    "Completed": "مكتمل", "Pending": "لم يتم بعد", "Cancelled": "ملغى",
}


def _pattern(names: list[str]) -> re.Pattern:
    # Arabic words often carry a one-letter prefix: "بالشمال", "لسند", "والطرد"
    alts = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:و|ب|ل|ف|ال|لل|بال)?(?:{alts})(?!\w)", re.I)


_GOV = {v: _pattern(n) for v, n in GOVERNORATE_NAMES.items()}
_PARTNER = {v: _pattern(n) for v, n in PARTNER_NAMES.items()}
_ITEM = {v: _pattern(n) for v, n in ITEM_NAMES.items()}


@lru_cache(maxsize=4)
def load(path: str = str(DATA)) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str)
    df["date"] = pd.to_datetime(df["date"])
    return df


def _find(patterns: dict[str, re.Pattern], text: str) -> list[str]:
    return [value for value, p in patterns.items() if p.search(text)]


@dataclass
class Hints:
    """What the text says about place, partner and item (may be empty or ambiguous)."""
    governorates: list[str] = field(default_factory=list)
    partners: list[str] = field(default_factory=list)
    items: list[str] = field(default_factory=list)

    def one(self, name: str) -> str | None:
        values = getattr(self, name)
        return values[0] if len(values) == 1 else None


@dataclass
class Lookup:
    outcome: str                                   # found | multiple | not_found_id | no_match | no_info
    matches: list[dict] = field(default_factory=list)
    hints: Hints = field(default_factory=Hints)
    asked_id: str | None = None

    @property
    def distribution(self) -> dict | None:
        return self.matches[0] if self.outcome == "found" else None

    def summary(self) -> str:
        if self.outcome == "found":
            d = self.distribution
            return f"found {d['distribution_id']} ({d['status']})"
        if self.outcome == "multiple":
            return f"{len(self.matches)} matches: " + ", ".join(m["distribution_id"] for m in self.matches[:MAX_OPTIONS])
        return self.outcome + (f" {self.asked_id}" if self.asked_id else "")


def extract_hints(message: str) -> Hints:
    text = normalise(message)
    # A bare "غزه" is not matched on purpose: it could mean Gaza City or the whole Strip.
    return Hints(_find(_GOV, text), _find(_PARTNER, text), _find(_ITEM, text))


def _row(r: pd.Series) -> dict:
    return {"distribution_id": r["distribution_id"], "date": r["date"].strftime("%Y-%m-%d"),
            "governorate": r["governorate"], "partner": r["partner"], "item": r["item"], "status": r["status"]}


def lookup(message: str, distribution_id: str | None = None, governorate: str | None = None,
           path: str = str(DATA), id_from_text: bool = True) -> Lookup:
    """Find the distribution this feedback is about. Never invents one.
    id_from_text=False: use only the ticket's distribution_id field (the agent
    does this, so a wrong number corrected in a follow-up is not read again)."""
    df = load(path)
    hints = extract_hints(message)
    if governorate and governorate not in hints.governorates:
        hints.governorates = [governorate]           # the form field wins over the text
    dst = distribution_id or (normalise_dst(message) if id_from_text else None)
    if dst:
        hit = df[df["distribution_id"] == dst]
        if hit.empty:
            return Lookup("not_found_id", hints=hints, asked_id=dst)
        return Lookup("found", [_row(hit.iloc[0])], hints)

    if not (hints.governorates or hints.items):      # a partner alone is too broad to ask about
        return Lookup("no_info", hints=hints)
    rows = df
    for col, values in (("governorate", hints.governorates), ("partner", hints.partners), ("item", hints.items)):
        if values:
            rows = rows[rows[col].isin(values)]
    if _FUTURE.search(normalise(message)) and (rows["status"] == "Pending").any():
        rows = rows[rows["status"] == "Pending"]      # "when is the next one?" -> planned distributions
    rows = rows.sort_values("date")
    if rows.empty:
        return Lookup("no_match", hints=hints)
    matches = [_row(r) for _, r in rows.iterrows()]
    return Lookup("found" if len(matches) == 1 else "multiple", matches, hints)


def option_label(d: dict, language: str) -> str:
    """One line per option, in the person's language: 'DST-029 · نور للإغاثة · 2026-03-09 · مكتمل'."""
    if language == "ar":
        return f"{d['distribution_id']} · {AR[d['partner']]} · {AR[d['item']]} · {d['date']} · {AR[d['status']]}"
    return f"{d['distribution_id']} · {d['partner']} · {d['item']} · {d['date']} · {d['status']}"
