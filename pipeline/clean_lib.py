"""Shared normalisers for the Xtrim cleaning pipeline.

Design rule: every categorical mapping is explicit. An unmapped value raises
instead of falling into a default bucket, so nothing is ever silently misfiled.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta

import pandas as pd

NULLS = {"", "-", "--", "null", "none", "n/a", "na", "#n/a", "unknown", "tbd", "nan", "nat"}


class UnmappedValue(ValueError):
    pass


def is_null(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and v != v:
        return True
    return str(v).strip().lower() in NULLS


def clean_text(v):
    """Trim, collapse internal whitespace, null-spellings -> None. Case is kept."""
    if is_null(v):
        return None
    return re.sub(r"\s+", " ", str(v)).strip()


def _norm_key(v):
    return re.sub(r"[^0-9a-zÀ-ɏ]+", " ", str(v).lower()).strip()


def key(v):
    """Lookup key: lowercase, accents kept, punctuation/space runs -> single space."""
    if is_null(v):
        return None
    return _norm_key(v)


def mapper(name: str, table: dict[str, str | None]):
    """Build a strict mapping function. Table keys are normalised without the null check,
    so a real category spelled like a null word (e.g. medium '(none)') still maps."""
    norm = {_norm_key(k): v for k, v in table.items()}

    def f(v):
        if is_null(v):
            return None
        k = key(v)
        if k not in norm:
            raise UnmappedValue(f"{name}: no mapping for {v!r} (key {k!r})")
        return norm[k]

    f.table = norm
    return f


# ------------------------------------------------------------------ booleans
TRUE = {"true", "t", "yes", "y", "1", "1.0"}
FALSE = {"false", "f", "no", "n", "0", "0.0"}


def to_bool(v):
    if is_null(v):
        return None
    s = str(v).strip().lower()
    if s in TRUE:
        return True
    if s in FALSE:
        return False
    raise UnmappedValue(f"boolean: no mapping for {v!r}")


# ----------------------------------------------------------------------- ids
def norm_prefixed_id(v, prefix: str, width: int = 5):
    if is_null(v):
        return None
    digits = re.sub(r"\D", "", str(v))
    if not digits:
        raise UnmappedValue(f"id: no digits in {v!r}")
    return f"{prefix}-{int(digits):0{width}d}"


def norm_order_id(v):
    if is_null(v):
        return None
    digits = re.sub(r"\D", "", str(v))
    if not digits:
        raise UnmappedValue(f"order id: no digits in {v!r}")
    return f"ORD{int(digits):06d}"


def norm_sku(v):
    if is_null(v):
        return None
    s = re.sub(r"[^A-Za-z0-9]", "", str(v)).upper()
    m = re.match(r"^XT([A-Z]{3})(\d{1,3})$", s)
    if not m:
        raise UnmappedValue(f"sku: unparseable {v!r}")
    return f"XT-{m.group(1)}-{int(m.group(2)):03d}"


def id_number(v):
    if is_null(v):
        return None
    d = re.sub(r"\D", "", str(v))
    return int(d) if d else None


# --------------------------------------------------------------------- dates
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
EXCEL_EPOCH = datetime(1899, 12, 30)


def parse_date(v, slash_order: str | None, allow_excel_serial: bool = False, dotted_order: str = "DMY"):
    """Parse one date value.

    slash_order: 'DMY' or 'MDY' for a/b/YYYY strings — required when slash dates can
    appear, because the convention differs by file and must be proven, not guessed.
    Returns a python date or None. Raises UnmappedValue on anything unrecognised.
    """
    if is_null(v):
        return None
    if isinstance(v, (datetime, pd.Timestamp)):
        return pd.Timestamp(v).date()
    if isinstance(v, (int, float)):
        if not allow_excel_serial:
            raise UnmappedValue(f"date: unexpected number {v!r}")
        return (EXCEL_EPOCH + timedelta(days=int(v))).date()

    s = str(v).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return datetime.strptime(s, "%Y-%m-%d").date()
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if slash_order == "DMY":
            return datetime(y, b, a).date()
        if slash_order == "MDY":
            return datetime(y, a, b).date()
        raise UnmappedValue(f"date: slash date {s!r} with no proven convention")
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{2})$", s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), 2000 + int(m.group(3))
        return datetime(y, b, a).date() if dotted_order == "DMY" else datetime(y, a, b).date()
    m = re.match(r"^(\d{1,2})-([A-Za-z]{3})-(\d{2,4})$", s)
    if m:
        y = int(m.group(3))
        y = y + 2000 if y < 100 else y
        return datetime(y, MONTHS[m.group(2).lower()], int(m.group(1))).date()
    m = re.match(r"^([A-Za-z]+) (\d{1,2}), (\d{4})$", s)
    if m:
        return datetime.strptime(s, "%B %d, %Y").date()
    if allow_excel_serial and re.match(r"^\d{5}(\.0+)?$", s):
        return (EXCEL_EPOCH + timedelta(days=int(float(s)))).date()
    raise UnmappedValue(f"date: unrecognised {s!r}")


# ------------------------------------------------------------------- names
def fold(v):
    """Accent-insensitive, letters only — used purely for similarity scoring."""
    if is_null(v):
        return ""
    s = unicodedata.normalize("NFKD", str(v)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]", "", s)


def title_name(v):
    """Tidy a person/company name without mangling particles or acronyms we know about."""
    t = clean_text(v)
    if t is None:
        return None
    keep_upper = {"PLC", "NGO", "LTD", "TVC", "UK", "USA", "UAE", "FCT"}
    out = []
    for w in t.split(" "):
        u = w.upper().strip(".,")
        if u in keep_upper:
            out.append(w.upper())
        elif "'" in w:
            out.append("'".join(p[:1].upper() + p[1:].lower() for p in w.split("'")))
        elif "-" in w:
            out.append("-".join(p[:1].upper() + p[1:].lower() for p in w.split("-")))
        else:
            out.append(w[:1].upper() + w[1:].lower())
    return " ".join(out)


def norm_email(v):
    if is_null(v):
        return None
    s = str(v).strip().lower()
    return s if re.match(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", s) else None


def base_email(v):
    e = norm_email(v)
    return re.sub(r"\+[^@]*@", "@", e) if e else None


def norm_phone(v):
    """Return (+234XXXXXXXXXX, status). Never invents a digit."""
    if is_null(v):
        return None, "missing"
    d = re.sub(r"\D", "", str(v))
    if d.startswith("234"):
        d = d[3:]
    if d.startswith("0"):
        d = d[1:]
    if len(d) == 10 and d[0] in "789":
        return f"+234{d}", "ok"
    return None, f"invalid_length_{len(d)}"


# ------------------------------------------------------------------ mojibake
_CP1252_CONT = "".join(bytes([b]).decode("cp1252", errors="ignore") for b in range(0x80, 0xC0))
_MOJI = re.compile("[ÂÃâã][" + re.escape(_CP1252_CONT) + "]{1,2}")


def fix_mojibake(s):
    """Undo UTF-8 text that was decoded as Windows-1252 (e.g. 'â€™' -> '’', 'Ã©' -> 'é').

    Also handles copies that were later case-changed ('Â€™', 'ã©'), by retrying with
    the lead character's case flipped. A candidate is only accepted if it decodes as
    valid UTF-8, so genuine accented text is never touched.
    """
    if not isinstance(s, str) or not s:
        return s

    def rep(m):
        t = m.group()
        flips = {"Â": "â", "ã": "Ã"}
        candidates = [t] + ([flips[t[0]] + t[1:]] if t[0] in flips else [])
        # Longest sequence first ACROSS every case variant. Trying the 2-char decode of
        # the original before the 3-char decode of the flipped variant turns 'Â€™' into
        # U+0080 + '™' — a decode that is technically valid UTF-8 and silently wrong.
        for n in (3, 2):
            for cand in candidates:
                chunk = cand[:n]
                if len(chunk) < n:
                    continue
                try:
                    out = chunk.encode("cp1252").decode("utf-8")
                except (UnicodeEncodeError, UnicodeDecodeError):
                    continue
                if any(0x80 <= ord(ch) <= 0x9F for ch in out):
                    continue  # C1 control characters are never real text: wrong decode
                return out + cand[n:]
        return t

    prev = None
    while prev != s:  # repeat in case one fix exposes another
        prev, s = s, _MOJI.sub(rep, s)
    return s


def decode_mixed(raw: bytes) -> str:
    """Each maximal run of non-ASCII bytes: UTF-8 if valid, otherwise Windows-1252."""
    out, i = [], 0
    for m in re.finditer(rb"[\x80-\xFF]+", raw):
        out.append(raw[i:m.start()].decode("ascii"))
        run = m.group()
        try:
            out.append(run.decode("utf-8"))
        except UnicodeDecodeError:
            out.append(run.decode("cp1252"))
        i = m.end()
    out.append(raw[i:].decode("ascii"))
    return "".join(out)
