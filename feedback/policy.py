"""
Priority policy: written rules (PROJECT_PLAN.md §7), executed by code.

The brief says: "assign priority using the policy you wrote before coding;
do not treat the Agent's unsupported guess as a policy." So the LLM only
supplies the CATEGORY. Priority is computed here from facts found in the
text and from the distribution's REAL status (looked up in stage 3), and
every result carries the ID of the rule that produced it, so an officer can
see why a case is High and a manager can change the policy in one place.

Policy v1
  S1  any confidential referral                               Critical  1 day
  H1  not received, and the distribution is Completed        High      3 days
  H2  access barrier for an older person, a person with a
      disability, a pregnant woman or a child                 High      3 days
  M1  other distribution problem                              Medium    7 days
  M2  staff conduct (not sensitive)                           Medium    7 days
  M3  other access problem                                    Medium    7 days
  L1  information request or appreciation                     Low      14 days
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import Category, Priority
from .text import normalise

POLICY: dict[str, tuple[Priority, int, str]] = {           # rule -> (priority, days to respond, text)
    "S1": (Priority.CRITICAL, 1, "Confidential referral: safeguarding focal point within 24 hours"),
    "H1": (Priority.HIGH, 3, "Not received from a completed distribution (possible exclusion or diversion)"),
    "H2": (Priority.HIGH, 3, "Access barrier for an older person, a person with a disability, a pregnant woman or a child"),
    "M1": (Priority.MEDIUM, 7, "Distribution problem (missing, damaged or expired item; pending or cancelled distribution)"),
    "M2": (Priority.MEDIUM, 7, "Staff conduct"),
    "M3": (Priority.MEDIUM, 7, "Access problem (distance, queue, timing)"),
    "L1": (Priority.LOW, 14, "Information request or appreciation"),
}

# Patterns on normalise() output (Arabic incl. Gaza dialect, and English).
_NOT_RECEIVED = re.compile(
    r"(ما|مش|لم)\s?(استلمت|استلمنا|وصلني|وصلنا|وصلتنا|اخذت|اخدت|اخذنا|اخدنا|اجاني|اجانا)"
    r"|(ما|مش)\s?(حد|حدا)\s(كان|موجود)|ولا حدا|ما لقينا حدا"
    r"|\b(didn'?t|did not|never|haven'?t|have not|not)\s(receive|received|get|got|gotten)\b"
    r"|\bnobody (was|came)\b|\bno one (was|came)\b", re.I)
_VULNERABLE = re.compile(
    r"(كبير\S* بالسن|كبيره بالسن|ختيار|ختياره|عجوز|مسن|كرسي متحرك|معاق|اعاقه|كفيف|اعمي|مبتور|حامل|طفل|اطفال|ولد صغير|بنت صغيره|رضيع|بيبي)"
    r"|\b(elderly|older (person|people|man|woman)|old (man|woman)|disab\w+|wheelchair|blind|pregnant|child|children|baby|infant)\b",
    re.I)


@dataclass
class Facts:
    """What the code found in the text. Separate from the decision, so tests
    can check extraction and policy independently."""
    not_received: bool = False
    vulnerable: bool = False


@dataclass
class Assessment:
    priority: Priority
    rule: str
    rule_text: str
    days: int
    missing: list[str] = field(default_factory=list)


def extract_facts(message: str) -> Facts:
    text = normalise(message)
    return Facts(not_received=bool(_NOT_RECEIVED.search(text)), vulnerable=bool(_VULNERABLE.search(text)))


def assess(category: Category | str, facts: Facts, distribution_status: str | None = None,
           distribution_found: bool = False, referred: bool = False) -> Assessment:
    """Apply the written policy. Order matters: the most urgent rule wins.

    distribution_status: 'Completed' / 'Pending' / 'Cancelled' from the lookup, or None.
    distribution_found:  True only when exactly ONE distribution matched.
    """
    category = Category(category)
    if referred:
        rule = "S1"
    elif category is Category.DISTRIBUTION and facts.not_received and distribution_status == "Completed":
        rule = "H1"
    elif category is Category.ACCESS and facts.vulnerable:
        rule = "H2"
    elif category is Category.DISTRIBUTION:
        rule = "M1"
    elif category is Category.CONDUCT:
        rule = "M2"
    elif category is Category.ACCESS:
        rule = "M3"
    else:
        rule = "L1"
    priority, days, text = POLICY[rule]
    # Only distribution problems need a distribution; a referral never waits for details.
    missing = ["distribution"] if (category is Category.DISTRIBUTION and not referred and not distribution_found) else []
    return Assessment(priority, rule, text, days, missing)
