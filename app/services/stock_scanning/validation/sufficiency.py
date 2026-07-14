"""BLOK 9 - Veri yeterlilik siniflandirici (sufficiency.py).

SPEC BLOK 9 bolum 8. classify_sufficiency 6 durumdan birini dondurur:

- SUFFICIENT_DATA: >= bootstrap_days (vars. 260) gecerli bar
- LIMITED_DATA: 60 <= gecerli bar < 260
- NEW_LISTING: listing_date yakin (new_listing_days, vars. 60 gun) VE
  gecerli bar sayisi bootstrap esiginden az — eksik gecmis URETILMEZ
- INSUFFICIENT_FOR_TECHNICAL: 0 < gecerli bar < 60 (gostergeler isinamaz)
- PRICE_DATA_MISSING: 0 gecerli bar
- REVIEW_REQUIRED: seride cozulmemis REVIEW_REQUIRED durumlu bar var

Oncelik: toplam 0 -> PRICE_DATA_MISSING; cozulmemis inceleme ->
REVIEW_REQUIRED; gecerli 0 -> PRICE_DATA_MISSING; yeni halka arz ->
NEW_LISTING; yeterli -> SUFFICIENT_DATA; sinirli -> LIMITED_DATA;
aksi -> INSUFFICIENT_FOR_TECHNICAL.

"Gecerli bar" sayimi: giris ogeleri BarVerdict benzeri ise status
alanina bakilir (CLEAN/VALIDATED gecerli; REJECTED/RAW gecersiz;
REVIEW_REQUIRED inceleme). Ham bar nesneleri (status yok) gecerli sayilir.

Saat enjekte edilebilir (clock). stdlib only; deterministik.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Optional, Sequence

from .rules import LayerStatus

SUFFICIENT_DATA = "SUFFICIENT_DATA"
LIMITED_DATA = "LIMITED_DATA"
NEW_LISTING = "NEW_LISTING"
INSUFFICIENT_FOR_TECHNICAL = "INSUFFICIENT_FOR_TECHNICAL"
PRICE_DATA_MISSING = "PRICE_DATA_MISSING"
REVIEW_REQUIRED = "REVIEW_REQUIRED"

ALL_STATUSES = (
    SUFFICIENT_DATA,
    LIMITED_DATA,
    NEW_LISTING,
    INSUFFICIENT_FOR_TECHNICAL,
    PRICE_DATA_MISSING,
    REVIEW_REQUIRED,
)


@dataclass
class SufficiencyConfig:
    """Yeterlilik esikleri."""

    bootstrap_days: int = 260
    min_technical_days: int = 60
    new_listing_days: int = 60


@dataclass
class SufficiencyVerdict:
    """Siniflandirma + gerekce + sayimlar."""

    status: str
    valid_bars: int
    total_bars: int
    reason: str


def _coerce_date(value) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def _status_value(item) -> Optional[str]:
    """Ogenn katman durumu (yoksa None = ham bar, gecerli sayilir)."""
    status = getattr(item, "status", None)
    if status is None:
        return None
    if isinstance(status, LayerStatus):
        return status.value
    return str(status)


def classify_sufficiency(
    stock_id: str,
    bars: Sequence,
    config: Optional[SufficiencyConfig] = None,
    listing_date=None,
    clock: Optional[Callable] = None,
) -> SufficiencyVerdict:
    """Seri veri yeterliligini siniflandirir (6 durum).

    listing_date: ISO str veya date; clock: 'bugun' saglayici (date/
    datetime/ISO str). Yeni halka arz icin eksik gecmis URETILMEZ —
    siniflandirma mevcut barlarla yapilir.
    """
    cfg = config or SufficiencyConfig()
    items = list(bars)
    total = len(items)

    valid = 0
    review = 0
    for item in items:
        sv = _status_value(item)
        if sv is None or sv in (LayerStatus.CLEAN.value, LayerStatus.VALIDATED.value):
            valid += 1
        elif sv == LayerStatus.REVIEW_REQUIRED.value:
            review += 1

    def _verdict(status: str, reason: str) -> SufficiencyVerdict:
        return SufficiencyVerdict(
            status=status, valid_bars=valid, total_bars=total, reason=reason
        )

    if total == 0:
        return _verdict(PRICE_DATA_MISSING, "seride hic bar yok")
    if review > 0:
        return _verdict(
            REVIEW_REQUIRED,
            "%d bar cozulmemis inceleme bekliyor (REVIEW_REQUIRED)" % review,
        )
    if valid == 0:
        return _verdict(
            PRICE_DATA_MISSING, "gecerli bar yok (toplam %d bar)" % total
        )

    if listing_date is not None:
        ld = _coerce_date(listing_date)
        today = _coerce_date(clock()) if clock is not None else date.today()
        if ld is not None and today is not None:
            age = (today - ld).days
            if age <= cfg.new_listing_days and valid < cfg.bootstrap_days:
                return _verdict(
                    NEW_LISTING,
                    "halka arz uzerinden %d gun gecti (<= %d) ve %d gecerli bar "
                    "< %d esik; eksik gecmis uretilmez"
                    % (age, cfg.new_listing_days, valid, cfg.bootstrap_days),
                )

    if valid >= cfg.bootstrap_days:
        return _verdict(
            SUFFICIENT_DATA,
            "%d gecerli bar >= %d bootstrap esigi" % (valid, cfg.bootstrap_days),
        )
    if valid >= cfg.min_technical_days:
        return _verdict(
            LIMITED_DATA,
            "%d gecerli bar: %d <= n < %d (sinirli veri)"
            % (valid, cfg.min_technical_days, cfg.bootstrap_days),
        )
    return _verdict(
        INSUFFICIENT_FOR_TECHNICAL,
        "%d gecerli bar < %d: teknik gostergeler isinamaz"
        % (valid, cfg.min_technical_days),
    )
