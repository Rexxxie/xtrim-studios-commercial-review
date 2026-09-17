"""Strict money parser.

Returns (amount: float | None, currency: str | None, problem: str | None).
`problem` is set whenever a value cannot be read unambiguously, so the caller can
quarantine it instead of guessing.
"""
import re

NULLS = {"", "-", "--", "null", "none", "n/a", "na", "#n/a", "unknown", "tbd", "nan"}

CURRENCY_TOKENS = [
    ("NGN", "NGN"), ("USD", "USD"), ("GBP", "GBP"), ("EUR", "EUR"),
    ("₦", "NGN"),  # ₦
    ("$", "USD"), ("£", "GBP"), ("€", "EUR"),  # £ €
]

# digits with optional thousands groups (comma OR space) and optional decimal part
THOUSANDS_COMMA = re.compile(r"^\d{1,3}(,\d{3})+(\.\d+)?$")
THOUSANDS_SPACE = re.compile(r"^\d{1,3}( \d{3})+(\.\d+)?$")
PLAIN = re.compile(r"^\d+(\.\d+)?$")
SUFFIXED = re.compile(r"^(\d+(\.\d+)?)\s*([kKmMbB])$")
DECIMAL_COMMA = re.compile(r"^\d+,\d{1,2}$")  # e.g. 87635,35 (only valid where the file says so)

MULT = {"k": 1e3, "m": 1e6, "b": 1e9}


def is_null(v) -> bool:
    return v is None or str(v).strip().lower() in NULLS


def parse_money(value, allow_decimal_comma: bool = False):
    if value is None:
        return None, None, None
    if isinstance(value, (int, float)):
        if value != value:  # NaN
            return None, None, None
        return float(value), None, None

    s = str(value).strip().replace(" ", " ").replace(" ", " ")
    if s.lower() in NULLS:
        return None, None, None

    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1].strip()
    if s.startswith("-"):
        neg, s = (not neg), s[1:].strip()

    s = re.sub(r"/-$", "", s).strip()  # Nigerian accounting "NGN2,977,000.00/-"

    currency = None
    for token, code in CURRENCY_TOKENS:
        if token in s:
            if currency and currency != code:
                return None, None, f"conflicting currency tokens in {value!r}"
            currency = code
            s = s.replace(token, " ")
    s = re.sub(r"\s+", " ", s).strip()

    # a sign can also sit after the currency symbol: "₦-4,900.00"
    if s.startswith("-"):
        neg, s = (not neg), s[1:].strip()

    if (m := SUFFIXED.match(s)):
        amount = float(m.group(1)) * MULT[m.group(3).lower()]
    elif THOUSANDS_COMMA.match(s):
        amount = float(s.replace(",", ""))
    elif THOUSANDS_SPACE.match(s):
        amount = float(s.replace(" ", ""))
    elif PLAIN.match(s):
        amount = float(s)
    elif allow_decimal_comma and DECIMAL_COMMA.match(s):
        amount = float(s.replace(",", "."))
    else:
        return None, currency, f"unparseable amount {value!r}"

    return (-amount if neg else amount), currency, None
