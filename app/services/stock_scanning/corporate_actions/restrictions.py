"""BLOK 13 - Aktif tedbir kayit defteri (restrictions.py).

RestrictionRegistry:
- register(stock_id, restriction) -> RestrictionResult(stored|duplicate)
  * DEDUPE: ayni (stock_id, restriction_type, start_date) tekrari
    reddedilir (duplicate++).
  * is_active OTOMATIK hesaplanir: start_date <= today <= end_date
    (end_date None -> acik uclu aktif). Saat ENJEKTE edilir.
  * Kayitla gelen is_active bayragi hesaplananla uyusmazsa kayit
    REVIEW_REQUIRED olarak isaretlenir (kayit yine de saklanir;
    hesaplanan deger esastir).
- SURESI BITEN TEDBIR: end_date < today -> is_active=False (saat
  ilerlediginde otomatik gecis); kayit KORUNUR (arsiv), silinmez.
- active_restrictions(stock_id), restriction_history(stock_id).
- MARKET_CHANGE: hedef pazar bilgisi source/official_url ile izlenir
  (ayri alan yok — TradingRestriction'in 7 alani korunur).

Deterministik: clock enjekte; gercek ag YOK.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Dict, List, Optional, Tuple

from app.services.stock_scanning.corporate_actions.models import (
    RestrictionType,
    TradingRestriction,
)

# Bayrak uyumsuzlugu isaret kodu (SPEC bolum 5)
REVIEW_REQUIRED = "REVIEW_REQUIRED"

OUTCOME_STORED = "stored"
OUTCOME_DUPLICATE = "duplicate"
REASON_DUPLICATE_KEY = "DUPLICATE_KEY"

# Tedbir anahtari: (stock_id, restriction_type, start_date)
RestrictionKey = Tuple[str, RestrictionType, str]


@dataclass
class RestrictionResult:
    """register() ciktisi.

    outcome: stored | duplicate
    review_required: kayitla gelen is_active bayragi hesaplananla
    uyusmuyorsa True (REVIEW_REQUIRED).
    """

    outcome: str
    record: Optional[TradingRestriction] = None
    review_required: bool = False
    reason: str = ""


class RestrictionRegistry:
    """Aktif tedbirlerin merkezi kayit defteri (saat enjekte)."""

    def __init__(self, clock: Optional[Callable[[], object]] = None):
        self._clock: Callable[[], object] = clock or date.today
        self._entries: Dict[RestrictionKey, Dict[str, object]] = {}
        self._order: List[RestrictionKey] = []  # ekleme sirasi
        self.duplicate_count = 0

    # ------------------------------------------------------------------ #
    # Saat / tarih yardimcilari
    # ------------------------------------------------------------------ #
    def _today(self) -> date:
        value = self._clock()
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value)[:10])

    @staticmethod
    def _parse(value) -> Optional[date]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value)[:10])

    def _compute_active(
        self, restriction: TradingRestriction, today: Optional[date] = None
    ) -> bool:
        """start_date <= today <= end_date; end_date None -> acik uclu."""
        ref = today or self._today()
        start = self._parse(restriction.start_date)
        end = self._parse(restriction.end_date)
        if start is None:
            return False
        if ref < start:
            return False
        if end is not None and ref > end:
            return False
        return True

    # ------------------------------------------------------------------ #
    # Kayit
    # ------------------------------------------------------------------ #
    def register(
        self, stock_id: str, restriction: TradingRestriction
    ) -> RestrictionResult:
        """Tedbir kaydi; dedupe + otomatik is_active + bayrak uyumu kontrolu."""
        key: RestrictionKey = (
            stock_id,
            restriction.restriction_type,
            str(restriction.start_date)[:10],
        )
        if key in self._entries:
            self.duplicate_count += 1
            return RestrictionResult(
                outcome=OUTCOME_DUPLICATE, reason=REASON_DUPLICATE_KEY
            )

        computed = self._compute_active(restriction)
        review = bool(restriction.is_active != computed)
        # Hesaplanan deger esastir (bayrak uyumsuzlugu REVIEW_REQUIRED).
        restriction.is_active = computed
        if not restriction.collected_at:
            restriction.collected_at = self._today().isoformat()

        self._entries[key] = {
            "record": restriction,
            "review": review,
            "reason": REVIEW_REQUIRED if review else "",
        }
        self._order.append(key)
        return RestrictionResult(
            outcome=OUTCOME_STORED,
            record=restriction,
            review_required=review,
            reason=REVIEW_REQUIRED if review else "",
        )

    # ------------------------------------------------------------------ #
    # Sorgular (okuma aninda saat ile yeniden hesap: otomatik pasiflesme)
    # ------------------------------------------------------------------ #
    def _records_for(self, stock_id: str) -> List[TradingRestriction]:
        out: List[TradingRestriction] = []
        for key in self._order:
            if key[0] != stock_id:
                continue
            record = self._entries[key]["record"]
            # Saat ilerlediyse suresi biten tedbir OTOMATIK pasiflesir;
            # kayit korunur (arsiv), silinmez.
            record.is_active = self._compute_active(record)
            out.append(record)
        return out

    def active_restrictions(self, stock_id: str) -> List[TradingRestriction]:
        """Anlik aktif tedbirler (saat enjekte ile hesaplanir)."""
        return [r for r in self._records_for(stock_id) if r.is_active]

    def restriction_history(self, stock_id: str) -> List[TradingRestriction]:
        """Tum tedbir kayitlari (aktif + suresi biten arsiv); kayit korunur."""
        return self._records_for(stock_id)

    def review_items(self, stock_id: Optional[str] = None) -> List[TradingRestriction]:
        """Bayrak uyumsuzlugu nedeniyle REVIEW_REQUIRED isaretli kayitlar."""
        out: List[TradingRestriction] = []
        for key in self._order:
            if stock_id is not None and key[0] != stock_id:
                continue
            entry = self._entries[key]
            if entry["review"]:
                out.append(entry["record"])
        return out

    def review_reason(self, stock_id: str, restriction: TradingRestriction) -> str:
        """Bir kaydin REVIEW_REQUIRED neden kodunu dondurur (yoksa '')."""
        key: RestrictionKey = (
            stock_id,
            restriction.restriction_type,
            str(restriction.start_date)[:10],
        )
        entry = self._entries.get(key)
        if not entry:
            return ""
        return str(entry["reason"])
