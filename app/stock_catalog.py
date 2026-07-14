"""Local EGX stock-name catalog with safe automatic refresh and alias resolution."""

from __future__ import annotations

import re
import json
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Stock


_ARABIC_DIACRITICS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed\u0640]")
_NON_ALPHANUMERIC = re.compile(r"[^0-9a-z\u0621-\u064a]+")
_TICKER = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")

# High-frequency EGX names used by the selected channels. The remote catalog extends
# this baseline automatically; aliases learned from confirmed model results persist.
_SEED_STOCKS: tuple[dict[str, str], ...] = (
    {"ticker": "ABUK", "name_en": "Abu Qir Fertilizers and Chemicals", "name_ar": "أبو قير للأسمدة والصناعات الكيماوية"},
    {"ticker": "ALUM", "name_en": "Aluminium Arabia", "name_ar": "الألومنيوم العربية"},
    {"ticker": "AMER", "name_en": "Amer Group Holding", "name_ar": "عامر جروب"},
    {"ticker": "BTFH", "name_en": "Beltone Holding", "name_ar": "بلتون القابضة"},
    {"ticker": "CCAP", "name_en": "Qalaa Holdings", "name_ar": "القلعة للاستثمارات المالية"},
    {"ticker": "CICH", "name_en": "CI Capital Holding", "name_ar": "سي آي كابيتال القابضة"},
    {"ticker": "CIRA", "name_en": "Cairo for Investment and Real Estate Development", "name_ar": "القاهرة للاستثمار والتنمية العقارية"},
    {"ticker": "COMI", "name_en": "Commercial International Bank Egypt", "name_ar": "البنك التجاري الدولي", "aliases": "CIB|Commercial International Bank|التجاري الدولي|البنك التجاري"},
    {"ticker": "DSCW", "name_en": "Dice Sport and Casual Wear", "name_ar": "دايس للملابس الجاهزة"},
    {"ticker": "EAST", "name_en": "Eastern Company", "name_ar": "الشرقية للدخان"},
    {"ticker": "EGAL", "name_en": "Egypt Aluminum", "name_ar": "مصر للألومنيوم"},
    {"ticker": "EPCO", "name_en": "Egyptian Petrochemicals", "name_ar": "المصرية للبتروكيماويات"},
    {"ticker": "FWRY", "name_en": "Fawry for Banking and Payment Technology Services", "name_ar": "فوري لتكنولوجيا البنوك والمدفوعات الإلكترونية"},
    {"ticker": "HDBK", "name_en": "Housing and Development Bank", "name_ar": "بنك التعمير والإسكان"},
    {"ticker": "HRHO", "name_en": "EFG Holding", "name_ar": "إي إف جي القابضة"},
    {"ticker": "MASR", "name_en": "Madinet Masr for Housing and Development", "name_ar": "مدينة مصر للإسكان والتعمير"},
    {"ticker": "MFPC", "name_en": "Misr Fertilizers Production Company", "name_ar": "مصر لإنتاج الأسمدة موبكو", "aliases": "MOPCO|موبكو"},
    {"ticker": "MPCI", "name_en": "Memphis Pharmaceuticals and Chemical Industries", "name_ar": "ممفيس للأدوية والصناعات الكيماوية"},
    {"ticker": "OCDI", "name_en": "Six of October Development and Investment", "name_ar": "السادس من أكتوبر للتنمية والاستثمار سوديك"},
    {"ticker": "ORWE", "name_en": "Oriental Weavers", "name_ar": "النساجون الشرقيون"},
    {"ticker": "PHDC", "name_en": "Palm Hills Development", "name_ar": "بالم هيلز للتعمير"},
    {"ticker": "SWDY", "name_en": "Elsewedy Electric", "name_ar": "السويدي إليكتريك"},
    {"ticker": "TMGH", "name_en": "Talaat Moustafa Group Holding", "name_ar": "مجموعة طلعت مصطفى القابضة"},
    {"ticker": "ZMID", "name_en": "Zahraa Maadi Investment and Development", "name_ar": "زهراء المعادي للاستثمار والتعمير"},
)


def normalize_stock_name(value: str | None) -> str:
    """Normalize Arabic and English aliases without altering the stored display name."""
    normalized = _ARABIC_DIACRITICS.sub("", str(value or "").strip().casefold())
    normalized = normalized.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ؤ": "و", "ئ": "ي"}))
    return _NON_ALPHANUMERIC.sub("", normalized)


def _clean_ticker(value: object) -> str | None:
    ticker = str(value or "").strip().upper().removesuffix(".CA")
    return ticker if _TICKER.fullmatch(ticker) else None


def _stock_aliases(stock: Stock) -> set[str]:
    values = [stock.ticker, stock.name_en, stock.name_ar or "", *(stock.aliases or [])]
    return {normalized for value in values if (normalized := normalize_stock_name(value))}


def _match_stock(value: str, aliases: dict[str, Stock]) -> Stock | None:
    normalized = normalize_stock_name(value)
    if not normalized:
        return None
    exact = aliases.get(normalized)
    if exact is not None:
        return exact
    matches = {stock.ticker: stock for alias, stock in aliases.items() if len(alias) >= 6 and (alias in normalized or normalized in alias)}
    return next(iter(matches.values())) if len(matches) == 1 else None


def _remote_entries(payload: object) -> list[dict[str, str]]:
    values: object = payload
    if isinstance(payload, dict):
        values = payload.get("stocks") or payload.get("data") or payload.get("results") or []
    if not isinstance(values, list):
        return []
    entries: list[dict[str, str]] = []
    for item in values:
        if isinstance(item, str):
            ticker = _clean_ticker(item)
            if ticker:
                entries.append({"ticker": ticker, "name_en": ticker})
            continue
        if not isinstance(item, dict):
            continue
        ticker = _clean_ticker(item.get("ticker") or item.get("symbol") or item.get("code"))
        if not ticker:
            continue
        name_en = str(item.get("name_en") or item.get("company") or item.get("name") or ticker).strip()
        name_ar = str(item.get("name_ar") or item.get("arabic_name") or "").strip()
        entries.append({"ticker": ticker, "name_en": name_en or ticker, "name_ar": name_ar})
    return entries


class EGXStockCatalog:
    """Keeps a local catalog available even when its public source is offline."""

    def __init__(self, session: AsyncSession, source_url: str, state_root: Path = Path("storage"), refresh_days: int = 7) -> None:
        self.session = session
        self.source_url = source_url
        self.state_path = state_root / "egx_catalog_state.json"
        self.refresh_days = refresh_days

    def _state(self) -> dict[str, str]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def _save_state(self, state: dict[str, str]) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.state_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self.state_path)
        except OSError:
            pass

    @staticmethod
    def _as_datetime(value: str | None) -> datetime | None:
        try:
            return datetime.fromisoformat(value or "").astimezone(timezone.utc)
        except ValueError:
            return None

    def _refresh_due(self, state: dict[str, str], force: bool) -> bool:
        if force:
            return True
        now = datetime.now(timezone.utc)
        successful = self._as_datetime(state.get("last_successful_refresh"))
        if successful and now - successful < timedelta(days=self.refresh_days):
            return False
        attempted = self._as_datetime(state.get("last_refresh_attempt"))
        return attempted is None or now - attempted >= timedelta(days=1)

    async def status(self) -> dict[str, object]:
        state = self._state()
        count = len((await self.session.scalars(select(Stock.id))).all())
        return {
            "stock_count": count,
            "last_successful_refresh": state.get("last_successful_refresh"),
            "last_refresh_attempt": state.get("last_refresh_attempt"),
            "refresh_days": self.refresh_days,
        }

    async def ensure(self, force: bool = False) -> dict[str, object]:
        """Seed locally and only download a fresh public catalog when the cache is due."""
        entries = list(_SEED_STOCKS)
        changed = await self._upsert(entries)
        state = self._state()
        refreshed = False
        if self._refresh_due(state, force):
            state["last_refresh_attempt"] = datetime.now(timezone.utc).isoformat()
            try:
                async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
                    response = await client.get(self.source_url)
                    response.raise_for_status()
                    changed += await self._upsert(_remote_entries(response.json()))
                state["last_successful_refresh"] = datetime.now(timezone.utc).isoformat()
                refreshed = True
            except (httpx.HTTPError, ValueError):
                pass
            self._save_state(state)
        return {"changed": changed, "refreshed": refreshed, **(await self.status())}

    async def _upsert(self, entries: Iterable[dict[str, str]]) -> int:
        stocks = {stock.ticker: stock for stock in (await self.session.scalars(select(Stock))).all()}
        changed = 0
        for entry in entries:
            ticker = _clean_ticker(entry.get("ticker"))
            if not ticker:
                continue
            name_en = str(entry.get("name_en") or ticker).strip()
            name_ar = str(entry.get("name_ar") or "").strip()
            stock = stocks.get(ticker)
            if stock is None:
                stock = Stock(ticker=ticker, name_en=name_en, name_ar=name_ar or None, aliases=[])
                self.session.add(stock)
                stocks[ticker] = stock
                changed += 1
            elif stock.name_en == stock.ticker and name_en and name_en != ticker:
                stock.name_en = name_en
                changed += 1
            if name_ar and not stock.name_ar:
                stock.name_ar = name_ar
                changed += 1
            aliases = list(stock.aliases or [])
            for alias in (name_en, name_ar, *str(entry.get("aliases") or "").split("|")):
                if alias and alias not in aliases:
                    aliases.append(alias)
                    changed += 1
            stock.aliases = aliases
        if changed:
            await self.session.flush()
        return changed

    async def enrich_consolidated_output(self, payload: dict[str, Any]) -> None:
        """Fill only missing model identities from the local EGX mapping."""
        stocks = (await self.session.scalars(select(Stock))).all()
        by_ticker = {stock.ticker: stock for stock in stocks}
        by_alias = {alias: stock for stock in stocks for alias in _stock_aliases(stock)}

        def items() -> Iterable[dict[str, Any]]:
            for key in ("top_consolidated_recommendations", "achieved_targets", "client_inquiry_responses"):
                values = payload.get(key)
                for item in values if isinstance(values, list) else []:
                    if isinstance(item, dict):
                        yield item
            for values in (payload.get("text_based_categories") or {}).values():
                for item in values if isinstance(values, list) else []:
                    if isinstance(item, dict):
                        yield item

        for item in items():
            ticker = _clean_ticker(item.get("stock_code"))
            name_en = str(item.get("stock_name_en") or "").strip()
            name_ar = str(item.get("stock_name_ar") or "").strip()
            stock = by_ticker.get(ticker) if ticker else None
            if stock is None:
                stock = _match_stock(name_ar, by_alias) or _match_stock(name_en, by_alias)
            if stock is None:
                continue
            if not ticker:
                item["stock_code"] = stock.ticker
            if not name_en and stock.name_en:
                item["stock_name_en"] = stock.name_en
            if not name_ar and stock.name_ar:
                item["stock_name_ar"] = stock.name_ar
