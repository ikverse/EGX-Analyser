"""
Which Yahoo symbols carry a given EGX stock.

Yahoo moved EGX listings onto ISIN-form symbols on 30 July 2026. The legacy `SYMBOL.CA` series is
frozen at 29 July and the `EGS….CA` series begins at 30 July, so neither form alone covers a window
that spans that date, and asking for only the legacy one returns nothing at all for recent
sessions - silently, as an empty series rather than an error.

The mapping was built by price continuity rather than by name: a session's open equals the previous
session's close exactly, which identifies the pair even where the company names differ. Matching on
names alone produced eleven wrong mappings.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

LEGACY_SUFFIX = ".CA"
_MAPPING_PATH = Path(__file__).parent / "data" / "yahoo_symbols.json"


def normalize_ticker(value: object) -> str:
    """Sources quote the same company as both AMOC and AMOC.CA; they are one stock."""
    return str(value or "").strip().upper().removesuffix(LEGACY_SUFFIX)


@lru_cache(maxsize=1)
def _live_symbols() -> dict[str, str]:
    try:
        rows = json.loads(_MAPPING_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    mapping: dict[str, str] = {}
    for row in rows if isinstance(rows, list) else []:
        egx = normalize_ticker(row.get("egx"))
        yahoo = str(row.get("yahoo") or "").strip()
        if egx and yahoo:
            mapping[egx] = yahoo
    return mapping


def feeds_for(ticker: str) -> list[str]:
    """
    Every symbol that might carry this stock, live feed first.

    The caller reads them in order and lets the live feed win on any date both cover, so a window
    spanning the migration is continuous rather than split in two.
    """
    egx = normalize_ticker(ticker)
    if not egx:
        return []
    legacy = f"{egx}{LEGACY_SUFFIX}"
    live = _live_symbols().get(egx)
    return [legacy] if live is None or live == legacy else [live, legacy]
