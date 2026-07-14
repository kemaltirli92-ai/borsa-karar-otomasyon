"""BLOK 8 - Dogrulama yardimcilari (validator.py).

Icerik:
- is_iso_date / is_iso_currency: format kontrolleri (YYYY-MM-DD, 3 harf ISO).
- validate_bar / is_valid_bar: bozuk bar reddi. Kurallar (SPEC bolum 3):
    * open/high/low/close pozitif sayi olmali (NEGATIVE_PRICE)
    * volume >= 0 (NEGATIVE_VOLUME)
    * high >= low (HIGH_LT_LOW)
    * high >= max(open, close) — esneklik yok (HIGH_LT_MAX_OC)
    * currency 3 harf ISO kodu olmali (BAD_CURRENCY)
    * trade_date ISO tarih olmali (BAD_DATE)
- close_diff_pct / within_close_tolerance: kaynaklar arasi kapanis farki
  tolerans hesabi. Fark, birincil kaynagin kapanisina gore yuzde olarak
  hesaplanir: abs(a - b) / a * 100.

Dis bagimlilik yoktur (stdlib: re, datetime, typing).
"""
from __future__ import annotations

import re
from datetime import date
from typing import List

NEGATIVE_PRICE = "NEGATIVE_PRICE"
NEGATIVE_VOLUME = "NEGATIVE_VOLUME"
HIGH_LT_LOW = "HIGH_LT_LOW"
HIGH_LT_MAX_OC = "HIGH_LT_MAX_OC"
BAD_CURRENCY = "BAD_CURRENCY"
BAD_DATE = "BAD_DATE"

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_iso_currency(code) -> bool:
    """Kod 3 buyuk harften olusan ISO para birimi mi? (or. TRY, USD)."""
    return isinstance(code, str) and bool(_CURRENCY_RE.match(code))


def is_iso_date(value) -> bool:
    """Deger gecerli bir ISO tarih (YYYY-MM-DD) mi?"""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _is_positive_number(value) -> bool:
    """bool haric, pozitif int/float mi?"""
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return value > 0


def validate_bar(bar) -> List[str]:
    """Bar'i kontrol eder; hata kodlari listesi doner (bos = gecerli).

    bar, open/high/low/close/volume/currency/trade_date niteliklerine
    sahip herhangi bir nesne olabilir (PriceBar dahil).
    """
    errors: List[str] = []

    prices_ok = all(
        _is_positive_number(getattr(bar, field, None))
        for field in ("open", "high", "low", "close")
    )
    if not prices_ok:
        errors.append(NEGATIVE_PRICE)

    volume = getattr(bar, "volume", None)
    if isinstance(volume, bool) or not isinstance(volume, int) or volume < 0:
        errors.append(NEGATIVE_VOLUME)

    if prices_ok:
        high = bar.high
        low = bar.low
        if high < low:
            errors.append(HIGH_LT_LOW)
        if high < max(bar.open, bar.close):
            errors.append(HIGH_LT_MAX_OC)

    if not is_iso_currency(getattr(bar, "currency", None)):
        errors.append(BAD_CURRENCY)

    if not is_iso_date(getattr(bar, "trade_date", None)):
        errors.append(BAD_DATE)

    return errors


def is_valid_bar(bar) -> bool:
    """Bar gecerli mi? (validate_bar bos liste donduruyor mu?)"""
    return not validate_bar(bar)


def close_diff_pct(primary_close: float, reference_close: float) -> float:
    """Iki kapanis arasindaki fark yuzdesi (birincil kapanisa gore).

    Ornek: close_diff_pct(100.0, 102.0) == 2.0
    primary_close pozitif olmalidir; aksi halde ValueError.
    """
    if not _is_positive_number(primary_close):
        raise ValueError("primary_close pozitif sayi olmali: %r" % (primary_close,))
    if isinstance(reference_close, bool) or not isinstance(reference_close, (int, float)):
        raise ValueError("reference_close sayi olmali: %r" % (reference_close,))
    return abs(float(primary_close) - float(reference_close)) / float(primary_close) * 100.0


def within_close_tolerance(primary_close: float, reference_close: float, tolerance_pct: float) -> bool:
    """Kapanis farki tolerans icinde mi? (sinir degeri DAHIL)."""
    return close_diff_pct(primary_close, reference_close) <= tolerance_pct
