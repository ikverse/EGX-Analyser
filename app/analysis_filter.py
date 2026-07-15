"""Lightweight local filters used before and after model analysis."""

import re


_ARABIC_DIACRITICS = re.compile(r"[\u064B-\u065F\u0670\u0640]")
_PAST_RECOMMENDATION_MARKERS = (
    "\u0627\u0644\u0633\u0627\u0628\u0642",
    "\u062a\u0648\u0635\u064a\u0629 \u0633\u0627\u0628\u0642\u0629",
    "\u062a\u0648\u0635\u064a\u0627\u062a \u0633\u0627\u0628\u0642\u0629",
    "\u0627\u0644\u062a\u0648\u0635\u064a\u0629 \u0627\u0644\u0633\u0627\u0628\u0642\u0629",
    "\u0627\u0644\u062a\u0648\u0635\u064a\u0627\u062a \u0627\u0644\u0633\u0627\u0628\u0642\u0629",
    "previous recommendation",
    "previous recommendations",
    "old recommendation",
    "old recommendations",
)
_CLIENT_INQUIRY_MARKERS = (
    "\u0631\u062f\u064b\u0627 \u0639\u0644\u0649 \u0627\u0633\u062a\u0641\u0633\u0627\u0631\u0627\u062a \u0639\u0645\u0644\u0627\u0626\u0646\u0627",
    "\u0631\u062f\u0627 \u0639\u0644\u0649 \u0627\u0633\u062a\u0641\u0633\u0627\u0631\u0627\u062a \u0639\u0645\u0644\u0627\u0626\u0646\u0627",
    "\u0631\u062f \u0639\u0644\u0649 \u0627\u0633\u062a\u0641\u0633\u0627\u0631",
    "\u0627\u0633\u062a\u0641\u0633\u0627\u0631\u0627\u062a \u0627\u0644\u0639\u0645\u0644\u0627\u0621",
    "customer inquiry",
    "client inquiry",
)


def _normalize_arabic(text: str) -> str:
    normalized = _ARABIC_DIACRITICS.sub("", text or "").lower()
    return normalized.translate(
        str.maketrans({"\u0623": "\u0627", "\u0625": "\u0627", "\u0622": "\u0627", "\u0649": "\u064a", "\u0629": "\u0647"})
    )


def has_past_recommendation_context(text: str) -> bool:
    """Detect a caption that identifies its attached signal as a past recommendation."""
    normalized = _normalize_arabic(text)
    return any(_normalize_arabic(marker) in normalized for marker in _PAST_RECOMMENDATION_MARKERS)


def is_client_inquiry_context(text: str) -> bool:
    """Identify a client-question reply only for post-response validation."""
    normalized = _normalize_arabic(text)
    return any(_normalize_arabic(marker) in normalized for marker in _CLIENT_INQUIRY_MARKERS)
