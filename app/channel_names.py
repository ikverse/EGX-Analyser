from __future__ import annotations

import re


_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"
    "\U0001FC00-\U0001FFFF"
    "\U00002600-\U000027BF"
    "\U0000FE00-\U0000FE0F"
    "\U0001F3FB-\U0001F3FF"
    "\U000E0020-\U000E007F"
    "\u200d\u20e3"
    "]+"
)
_WHITESPACE_RE = re.compile(r"\s+")


def clean_channel_name(value: object, fallback: str = "Unknown chat") -> str:
    """Return a stable, emoji-free channel label without changing stored Telegram data."""
    cleaned = _EMOJI_RE.sub("", str(value or ""))
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip(" \t\r\n-|•·")
    return cleaned or fallback
