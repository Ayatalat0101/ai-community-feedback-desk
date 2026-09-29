"""
Data contracts: what a valid feedback form looks like, and the fixed
vocabularies (channel, status, category, priority) every other module uses.

Why enums?
----------
If status is a free string, one module writes "Referred" and another checks
for "referred", and a safeguarding case silently disappears from the focal
point's list. With an Enum, a typo is a crash in the tests, not a lost case.

Why validate here?
------------------
Validation is written once, with messages a community member understands
(in Arabic and English), and the UI only displays them.
"""
from __future__ import annotations

import re
import secrets
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, ValidationError, field_validator

MIN_MESSAGE, MAX_MESSAGE = 10, 2000
DST_RE = re.compile(r"\bDST[-\s]?(\d{3})\b", re.I)            # DST-017, dst 017, DST017
PHONE_RE = re.compile(r"^\+?\d[\d\s-]{6,15}\d$")

# The five governorates in data/aid_distributions.csv (Project 1).
GOVERNORATES = ["Rafah", "Khan Younis", "Deir al-Balah", "Gaza City", "North Gaza"]

MSG_SHORT = "Please describe what happened in a sentence or two. / اكتب ما حدث بجملة أو جملتين."
MSG_LONG = f"Please keep the message under {MAX_MESSAGE} characters. / الرسالة طويلة جداً."
MSG_PHONE = "Enter a valid phone number, or leave it empty. / رقم الهاتف غير صحيح، أو اتركه فارغاً."
MSG_DST = "Distribution numbers look like DST-017. / رقم التوزيع يكون مثل DST-017."


class Channel(str, Enum):
    WEB = "web"
    HOTLINE = "hotline"
    IN_PERSON = "in_person"


class Status(str, Enum):
    NEW = "new"
    WAITING_FOR_INFO = "waiting_for_info"
    DRAFT_READY = "draft_ready"
    REFERRED = "referred"              # confidential referral to the safeguarding focal point
    NEEDS_REWORK = "needs_rework"
    APPROVED = "approved"              # a person approved the reply; the person has not heard it yet
    DELIVERED = "delivered"            # the person received the reply (call, in person, or read it online)
    CLOSED = "closed"


class Category(str, Enum):
    DISTRIBUTION = "distribution"      # not received, missing, damaged, expired
    INFORMATION = "information"        # when / where / how to register
    CONDUCT = "conduct"                # staff behaviour (not sensitive)
    ACCESS = "access"                  # distance, queue, disability, pregnancy
    APPRECIATION = "appreciation"      # thanks
    SENSITIVE = "sensitive"            # set ONLY by a referral, never by the classifier


class DeliveryMethod(str, Enum):
    PHONE_CALL = "phone_call"          # hotline operator called back and read the reply
    IN_PERSON = "in_person"            # a volunteer told the person at a distribution point
    WEB = "web"                        # the person read it on the Track page
    CONFIDENTIAL = "confidential"      # the safeguarding focal point contacted the person


class Priority(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


def normalise_dst(text: str | None) -> Optional[str]:
    """'dst 17' is not valid (3 digits needed); 'dst 017' -> 'DST-017'. None if absent."""
    if not text:
        return None
    m = DST_RE.search(text)
    return f"DST-{m.group(1)}" if m else None


class Submission(BaseModel):
    """One feedback form. Invalid input raises ValidationError with messages
    written for the person giving feedback, not for a developer."""
    channel: Channel = Channel.WEB
    name: str = Field("", max_length=60)
    phone: str = ""
    distribution_id: str = ""
    governorate: str = ""
    message: str

    @field_validator("name", "phone", "distribution_id", "governorate", "message", mode="before")
    @classmethod
    def _strip(cls, v):
        return (v or "").strip()

    @field_validator("message")
    @classmethod
    def _message_length(cls, v: str) -> str:
        if len(v) < MIN_MESSAGE:
            raise ValueError(MSG_SHORT)
        if len(v) > MAX_MESSAGE:
            raise ValueError(MSG_LONG)
        return v

    @field_validator("phone")
    @classmethod
    def _phone_format(cls, v: str) -> str:
        if v and not PHONE_RE.match(v):
            raise ValueError(MSG_PHONE)
        return v

    @field_validator("distribution_id")
    @classmethod
    def _dst_format(cls, v: str) -> str:
        if not v:
            return v
        norm = normalise_dst(v)
        if not norm or len(re.sub(r"[\s-]", "", v)) != 6:
            raise ValueError(MSG_DST)
        return norm

    @field_validator("governorate")
    @classmethod
    def _governorate(cls, v: str) -> str:
        if v and v not in GOVERNORATES:
            raise ValueError(f"Choose one of: {', '.join(GOVERNORATES)}")
        return v

    @property
    def person_ref(self) -> str:
        """The name, or an anonymous reference: feedback must be possible without a name."""
        return self.name or f"anon-{secrets.token_hex(2)}"


def validate_form(**fields) -> tuple[Optional[Submission], dict[str, str]]:
    """Form helper for the UI: (submission, {}) or (None, {field: message})."""
    try:
        return Submission(**fields), {}
    except ValidationError as err:
        errors: dict[str, str] = {}
        for e in err.errors():
            field = str(e["loc"][0]) if e["loc"] else "form"
            msg = e["msg"].removeprefix("Value error, ")
            if e["type"] == "string_too_long" and field == "name":
                msg = "Please keep the name under 60 characters. / الاسم طويل جداً."
            if e["type"] == "enum" and field == "channel":
                msg = "Choose web, hotline or in person."
            errors.setdefault(field, msg)
        return None, errors
