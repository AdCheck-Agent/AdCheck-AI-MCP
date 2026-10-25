"""Month-day dates however they are spelled, for the judge guard and the suggestion checks."""

import re
import unicodedata

_DATE_SEPARATOR = r"[·.\-/‧・]"
_MONTH_DAY = re.compile(rf"(?<!\d)(\d{{1,2}})\s*(?:{_DATE_SEPARATOR}|월)\s*(\d{{1,2}})(?!\d)")
_DIGITS = re.compile(r"(?<!\d)\d{3,4}(?!\d)")


def _month_day(month: int, day: int) -> str | None:
    return f"{month}-{day}" if 1 <= month <= 12 and 1 <= day <= 31 else None


def date_keys(text: str) -> set[str]:
    """Month-day dates in any spelling (5월 18일, 5·18, 5.18, 518원) as one key such as '5-18'."""
    # NFKC turns the Hangul middle dot (ㆍ) into a different character, so swap it first.
    text = unicodedata.normalize("NFKC", text.replace("ㆍ", "·"))
    pairs = list(_MONTH_DAY.findall(text))
    pairs += [(run[:-2], run[-2:]) for run in _DIGITS.findall(text)]
    keys = {_month_day(int(month), int(day)) for month, day in pairs}
    return {key for key in keys if key}


def number_date_keys(text: str) -> set[str]:
    """Dates written only as a bare number (518원, 0518), with no 월·일 or separator.

    A reader of "5월 18일" sees a date and judges it as one; "518원" reads as a price, so a model
    can miss the date entirely.
    """
    text = unicodedata.normalize("NFKC", text)
    keys = {_month_day(int(run[:-2]), int(run[-2:])) for run in _DIGITS.findall(text)}
    return {key for key in keys if key}
