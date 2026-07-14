"""BLOK 13 - Kurumsal islem ve tedbir toplama zinciri (collector.py).

CorporateCollector(action_source=None, restriction_source=None,
                   action_registry=None, restriction_registry=None, clock=None):

- Kaynaklar ENJEKTE edilir (KAP/BIST uclari ileride baglanir). Sozlesme:
    action_source.fetch_actions(stock_id) -> list[CorporateActionRecord |
                                                  dict | (record, kap_notice_no)]
    restriction_source.fetch_restrictions(stock_id) -> list[TradingRestriction
                                                            | dict]
- Kaynak yok veya cagri hata verirse ilgili hisse SOURCE_UNAVAILABLE
  isaretlenir; toplama DURMAZ, diger hisseler devam eder; eksik hisse
  icin bos paket (FeedPacket) uretilir.
- collect(stock_ids) -> CollectionReport(collected, deduped, errors,
  source_status, packets)

PUAN KILIDI: Bu modul olumlu/olumsuz PUAN HESAPLAMAZ; sentiment/score/
impact/tone adinda alan veya fonksiyon TANIMLAMAZ.

Deterministik: clock enjekte (registry'lere aktarilir); gercek ag YOK.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from app.services.stock_scanning.corporate_actions.feed import CorporateFeed
from app.services.stock_scanning.corporate_actions.models import (
    CorporateActionRecord,
    FeedPacket,
    TradingRestriction,
)
from app.services.stock_scanning.corporate_actions.registry import (
    OUTCOME_CANCELLED,
    OUTCOME_DUPLICATE,
    OUTCOME_REVISION,
    OUTCOME_STORED,
    CorporateActionRegistry,
)
from app.services.stock_scanning.corporate_actions.restrictions import (
    RestrictionRegistry,
)
from app.services.stock_scanning.corporate_actions.suspension import (
    SuspensionPolicy,
)

SOURCE_OK = "OK"
SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"

_COLLECTED_OUTCOMES = {OUTCOME_STORED, OUTCOME_REVISION, OUTCOME_CANCELLED}

_ACTION_FIELDS = {
    "stock_id", "action_type", "announcement_date", "effective_date",
    "ratio", "amount", "currency", "source", "official_url", "status",
    "data_version",
}
_RESTRICTION_FIELDS = {
    "restriction_type", "start_date", "end_date", "is_active", "source",
    "official_url", "collected_at",
}


@dataclass
class CollectionReport:
    """collect() ciktisi (SPEC bolum 8).

    collected: yeni saklanan kayit sayisi (surum zinciri ve iptal kaydi
    dahil). deduped: cift kayit engeline takilan sayi. errors: kaynak
    hata/yokluk mesajlari. source_status: hisse -> OK | SOURCE_UNAVAILABLE.
    packets: kaynak sorunu olan (eksik) hisseler icin uretilen bos paketler.
    """

    collected: int = 0
    deduped: int = 0
    errors: List[str] = field(default_factory=list)
    source_status: Dict[str, str] = field(default_factory=dict)
    packets: Dict[str, FeedPacket] = field(default_factory=dict)


class CorporateCollector:
    """Enjekte kaynaklardan kurumsal islem/tedbir toplayan zincir."""

    def __init__(
        self,
        action_source=None,
        restriction_source=None,
        action_registry: Optional[CorporateActionRegistry] = None,
        restriction_registry: Optional[RestrictionRegistry] = None,
        clock: Optional[Callable[[], object]] = None,
    ):
        self.action_source = action_source
        self.restriction_source = restriction_source
        self.action_registry = action_registry or CorporateActionRegistry(clock=clock)
        self.restriction_registry = restriction_registry or RestrictionRegistry(
            clock=clock
        )
        self.feed = CorporateFeed(
            self.action_registry,
            self.restriction_registry,
            SuspensionPolicy(self.restriction_registry),
        )

    # ------------------------------------------------------------------ #
    # Donusum yardimcilari
    # ------------------------------------------------------------------ #
    @staticmethod
    def _normalize_action(item) -> Tuple[CorporateActionRecord, Optional[str]]:
        """Kaynak kalemini (record | dict | (record, kap_notice_no)) normalize eder."""
        if isinstance(item, tuple) and len(item) == 2:
            record, kap_notice_no = item
            return record, kap_notice_no
        if isinstance(item, CorporateActionRecord):
            return item, None
        data = {k: v for k, v in dict(item).items() if k in _ACTION_FIELDS}
        kap_notice_no = dict(item).get("kap_notice_no")
        return CorporateActionRecord(**data), kap_notice_no

    @staticmethod
    def _normalize_restriction(item) -> TradingRestriction:
        """Kaynak kalemini (record | dict) TradingRestriction'a cevirir."""
        if isinstance(item, TradingRestriction):
            return item
        data = {k: v for k, v in dict(item).items() if k in _RESTRICTION_FIELDS}
        return TradingRestriction(**data)

    # ------------------------------------------------------------------ #
    # Toplama
    # ------------------------------------------------------------------ #
    def collect(self, stock_ids: List[str]) -> CollectionReport:
        """Hisse listesi icin toplama; kaynak hatasi taramayi DURDURMAZ."""
        report = CollectionReport()
        for stock_id in stock_ids:
            failed = False

            # --- kurumsal islemler
            if self.action_source is None:
                report.errors.append(f"{stock_id}: action source tanimli degil")
                failed = True
            else:
                try:
                    items = self.action_source.fetch_actions(stock_id) or []
                except Exception as exc:  # kaynak hatasi -> kesinti sayilir
                    report.errors.append(
                        f"{stock_id}: action source hatasi: {exc}"
                    )
                    failed = True
                else:
                    for item in items:
                        record, kap_notice_no = self._normalize_action(item)
                        result = self.action_registry.register(
                            record, kap_notice_no=kap_notice_no
                        )
                        if result.outcome == OUTCOME_DUPLICATE:
                            report.deduped += 1
                        elif result.outcome in _COLLECTED_OUTCOMES:
                            report.collected += 1

            # --- aktif tedbirler
            if self.restriction_source is None:
                report.errors.append(f"{stock_id}: restriction source tanimli degil")
                failed = True
            else:
                try:
                    items = self.restriction_source.fetch_restrictions(stock_id) or []
                except Exception as exc:
                    report.errors.append(
                        f"{stock_id}: restriction source hatasi: {exc}"
                    )
                    failed = True
                else:
                    for item in items:
                        record = self._normalize_restriction(item)
                        result = self.restriction_registry.register(stock_id, record)
                        if result.outcome == OUTCOME_DUPLICATE:
                            report.deduped += 1
                        else:
                            report.collected += 1

            if failed:
                # Tarama DURMAZ; eksik hisse icin bos paket uretilir.
                report.source_status[stock_id] = SOURCE_UNAVAILABLE
                report.packets[stock_id] = self.feed.build_packet(stock_id)
            else:
                report.source_status[stock_id] = SOURCE_OK
        return report
