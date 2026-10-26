"""어떻게 표기했든 월·일 날짜를 찾는다. 판정 안전장치와 수정안 검사에 쓴다."""

import re
import unicodedata

_DATE_SEPARATOR = r"[·.\-/‧・]"
_MONTH_DAY = re.compile(rf"(?<!\d)(\d{{1,2}})\s*(?:{_DATE_SEPARATOR}|월)\s*(\d{{1,2}})(?!\d)")
_DIGITS = re.compile(r"(?<!\d)\d{3,4}(?!\d)")


def _month_day(month: int, day: int) -> str | None:
    return f"{month}-{day}" if 1 <= month <= 12 and 1 <= day <= 31 else None


def date_keys(text: str) -> set[str]:
    """어떤 표기(5월 18일, 5·18, 5.18, 518원)든 '5-18' 같은 하나의 키로 바꾼다."""
    # NFKC가 한글 가운뎃점(ㆍ)을 다른 문자로 바꾸므로 먼저 바꿔 둔다.
    text = unicodedata.normalize("NFKC", text.replace("ㆍ", "·"))
    pairs = list(_MONTH_DAY.findall(text))
    pairs += [(run[:-2], run[-2:]) for run in _DIGITS.findall(text)]
    keys = {_month_day(int(month), int(day)) for month, day in pairs}
    return {key for key in keys if key}


def number_date_keys(text: str) -> set[str]:
    """월·일이나 구분자 없이 숫자로만 쓴 날짜(518원, 0518).

    "5월 18일"은 누구나 날짜로 읽고 판단하지만, "518원"은 가격으로 읽혀
    모델이 날짜라는 것을 아예 놓칠 수 있다.
    """
    text = unicodedata.normalize("NFKC", text)
    keys = {_month_day(int(run[:-2]), int(run[-2:])) for run in _DIGITS.findall(text)}
    return {key for key in keys if key}
