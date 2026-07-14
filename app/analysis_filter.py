import re


_ARABIC_DIACRITICS = re.compile(r"[\u064B-\u065F\u0670\u0640]")
_PAST_RECOMMENDATION_MARKERS = (
    "السابق",
    "توصية سابقة",
    "توصيات سابقة",
    "التوصية السابقة",
    "التوصيات السابقة",
    "previous recommendation",
    "previous recommendations",
    "old recommendation",
    "old recommendations",
)


def has_past_recommendation_context(text: str) -> bool:
    """Detect a caption that identifies its attached signal as a past recommendation."""
    normalized = _ARABIC_DIACRITICS.sub("", text or "").lower()
    normalized = normalized.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"}))
    return any(marker in normalized for marker in _PAST_RECOMMENDATION_MARKERS)
