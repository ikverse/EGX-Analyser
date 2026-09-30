import re


_UNSUPPORTED_TARGET_RE = re.compile(
    r"(?:"
    r"\b(?:tp|t\.?p\.?|target|take\s*profit)\s*(?:#\s*)?(?:[3-9]|\d{2,}|three|third|four|fourth|five|fifth)\b|"
    r"\b(?:third|3rd|fourth|4th|fifth|5th)\s+(?:target|take\s*profit)\b|"
    r"(?:الهدف|هدف|المستهدف|مستهدف)\s+(?:الثالث|ثالث|الرابع|رابع|الخامس|خامس|رقم\s*[3-9])|"
    r"(?:ثالث|الثالث|رابع|الرابع|خامس|الخامس)\s+(?:هدف|مستهدف)"
    r")"
    r"(?:\s*(?:[:=@-]|is\b|at\b)?\s*[-+]?\d+(?:[.,]\d+)?%?)?",
    re.IGNORECASE,
)


def remove_unsupported_targets(value: object) -> str:
    """Remove TP3/third-target wording while retaining TP1, TP2, and surrounding insights."""
    text = _UNSUPPORTED_TARGET_RE.sub("", str(value or ""))
    text = re.sub(r"\s*([,;·])(?:\s*\1)+", r"\1", text)
    text = re.sub(r"(?:^|\s)[,;·]+\s*", " ", text)
    return re.sub(r"\s+", " ", text).strip(" -·;,")
