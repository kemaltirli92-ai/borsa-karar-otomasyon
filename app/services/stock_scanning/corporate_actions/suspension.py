"""BLOK 13 - Islem durdurma davranis kurallari (suspension.py).

SuspensionPolicy(restriction_registry):
- scan_status(stock_id) -> ScanStatus
- AKTIF TRADING_HALT varsa:
  * taramadan SILINMEZ (keep_in_scan=True her zaman)
  * gecmis grafik verisi KORUNUR (history_protected=True)
  * normal hisse gibi GOSTERILMEZ (show_as_normal=False)
  * scoring_ready=False
- TRADING_HALT bittiginde (saat ilerleyince tedbir pasiflesir)
  scoring_ready tekrar True olur.
- Diger tedbirler (GROSS_SETTLEMENT, SHORT_SELLING_BAN, ...) tek basina
  scoring_ready'yi KAPATMAZ; sadece risk notu olarak tasir.

Deterministik: saat, RestrictionRegistry'ye enjekte edilen clock uzerinden.
"""
from __future__ import annotations

from typing import List

from app.services.stock_scanning.corporate_actions.models import (
    RestrictionType,
    ScanStatus,
    TradingRestriction,
)
from app.services.stock_scanning.corporate_actions.restrictions import (
    RestrictionRegistry,
)

HALT_NOTE = (
    "TRADING_HALT aktif: hisse taramada korunur (silinmez), "
    "gecmis grafik verisi korunur, normal gosterilmez, skorlamaya hazir degil."
)
RISK_NOTE_PREFIX = "RISK_NOTE:"


class SuspensionPolicy:
    """Islem durdurmadaki sirketler icin tarama davranis politikasi."""

    def __init__(self, restriction_registry: RestrictionRegistry):
        self.restriction_registry = restriction_registry

    def scan_status(self, stock_id: str) -> ScanStatus:
        """Hisse icin tarama durumu (SPEC bolum 6)."""
        active: List[TradingRestriction] = self.restriction_registry.active_restrictions(
            stock_id
        )
        halts = [
            r for r in active if r.restriction_type == RestrictionType.TRADING_HALT
        ]
        others = [
            r for r in active if r.restriction_type != RestrictionType.TRADING_HALT
        ]

        if halts:
            return ScanStatus(
                keep_in_scan=True,          # ASLA taramadan silinmez
                history_protected=True,     # gecmis grafik verisi korunur
                show_as_normal=False,       # normal hisse gibi gosterilmez
                scoring_ready=False,        # skorlamaya hazir degil
                active_halts=tuple(halts),
                notes=(HALT_NOTE,),
            )

        # TRADING_HALT yok: diger tedbirler scoring_ready'yi kapatmaz;
        # risk notu olarak tasir.
        notes = tuple(
            f"{RISK_NOTE_PREFIX}{r.restriction_type.value}" for r in others
        )
        return ScanStatus(
            keep_in_scan=True,
            history_protected=True,
            show_as_normal=True,
            scoring_ready=True,
            active_halts=(),
            notes=notes,
        )
