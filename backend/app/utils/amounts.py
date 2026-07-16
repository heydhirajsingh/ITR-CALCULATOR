"""Money parsing helpers for Indian and international statement formats."""
from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation
from typing import Any

_AMOUNT_CLEAN_RE = re.compile(r"[^0-9.()\-]")


def parse_amount(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return Decimal("0")
        return Decimal(str(value)).quantize(Decimal("0.01"))
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null", "-", "--"}:
        return Decimal("0")
    negative = text.startswith("(") and text.endswith(")")
    text = _AMOUNT_CLEAN_RE.sub("", text.replace(",", ""))
    if text in {"", ".", "-"}:
        return Decimal("0")
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return Decimal("0")
    if negative:
        amount = -abs(amount)
    return amount.quantize(Decimal("0.01"))


def indian_currency(value: Decimal | float | int) -> str:
    amount = Decimal(str(value)).quantize(Decimal("0.01"))
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    whole, fraction = f"{amount:.2f}".split(".")
    if len(whole) > 3:
        last = whole[-3:]
        rest = whole[:-3]
        groups: list[str] = []
        while rest:
            groups.append(rest[-2:])
            rest = rest[:-2]
        whole = ",".join(reversed(groups)) + "," + last
    return f"{sign}₹{whole}.{fraction}"
