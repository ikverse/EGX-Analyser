"""
Whether a recommendation belongs to the session being analysed.

A source belongs to the session printed on it, and to no other. Channels re-post screenshots of old
cards, and the model has dated them to the target session with the real date left in
`visible_source_date` - a 13 July card counted as a 30 July call. The prompt forbids exactly that
and was ignored twice, so the check is arithmetic here rather than an instruction there.

The T+1 card needs no exception. A card published after Sunday's close for Monday's session is
printed `27 JULY 2026`, so it passes the plain rule on Monday's report and fails it everywhere else.
Accepting the neighbouring session as well would count every such card twice: once in the report for
the day it was published, once in the report for the day it names.

A date that cannot be read is rejected. It cannot be shown to belong here, and the model has already
been told to exclude an undated card - one arriving anyway means its own gate did not hold, which is
not the moment to be lenient.
"""

from __future__ import annotations

import re
from datetime import date

_ISO = re.compile(r"(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)")
_NUMERIC = re.compile(r"(?<!\d)(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})(?!\d)")
_WORDS = re.compile(r"[^\W\d_]+|\d+", re.UNICODE)

_MONTHS = {
    "jan": 1, "january": 1, "يناير": 1,
    "feb": 2, "february": 2, "فبراير": 2,
    "mar": 3, "march": 3, "مارس": 3,
    "apr": 4, "april": 4, "ابريل": 4, "أبريل": 4,
    "may": 5, "مايو": 5,
    "jun": 6, "june": 6, "يونيو": 6, "يونيه": 6,
    "jul": 7, "july": 7, "يوليو": 7, "يوليه": 7,
    "aug": 8, "august": 8, "اغسطس": 8, "أغسطس": 8,
    "sep": 9, "sept": 9, "september": 9, "سبتمبر": 9,
    "oct": 10, "october": 10, "اكتوبر": 10, "أكتوبر": 10,
    "nov": 11, "november": 11, "نوفمبر": 11,
    "dec": 12, "december": 12, "ديسمبر": 12,
}

_DIGITS = {
    **{chr(0x0660 + n): str(n) for n in range(10)},  # Arabic-Indic
    **{chr(0x06F0 + n): str(n) for n in range(10)},  # Eastern Arabic-Indic
}


def accepts(visible_source_date: object, target_date: date | None) -> bool:
    if target_date is None:
        return True
    return parse(visible_source_date) == target_date


def parse(value: object) -> date | None:
    """
    Reads a date as a source printed it.

    Sources write `13/7/2026`, `29/07/2026`, `30 JULY 2026` and `٢٨ يوليو ٢٠٢٦` interchangeably, so
    all of them have to be understood; anything else is left unparsed rather than guessed.
    """
    text = "".join(_DIGITS.get(character, character) for character in str(value or "")).strip()
    if not text:
        return None

    match = _ISO.search(text)
    if match:
        return _date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    match = _NUMERIC.search(text)
    if match:
        return _date(int(match.group(3)), int(match.group(2)), int(match.group(1)))

    words = _WORDS.findall(text.lower())
    month_at = next((index for index, word in enumerate(words) if word in _MONTHS), None)
    if month_at is None:
        return None
    month = _MONTHS[words[month_at]]
    neighbours = [words[index] for index in (month_at - 1, month_at + 1) if 0 <= index < len(words)]
    day = next((int(word) for word in neighbours if word.isdigit() and 1 <= int(word) <= 31), None)
    year = next((int(word) for word in words if word.isdigit() and 1900 <= int(word) <= 2999), None)
    if day is None or year is None:
        return None
    return _date(year, month, day)


def _date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None
