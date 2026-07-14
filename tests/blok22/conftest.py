"""BLOK 22 - Ortak test yardimcilari (deterministik; gercek ag YOK).

Tum yardimcilar enjekte clock/fetcher/duration desenini kullanir; hicbir
yerde gercek ag, subprocess veya datetime.now() cagrisi YOKTUR.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.acceptance.universe import UniverseBook
from app.services.stock_scanning.symbol_identity import SymbolIdentityService

FIXED_NOW = datetime(2025, 6, 3, 12, 0, 0)
FIXED_DAY = "2025-06-03"  # Sali (islem gunu)
ISO_NOW = "2025-06-03T08:00:00"


@pytest.fixture
def clock():
    return lambda: FIXED_NOW


@pytest.fixture
def identity(clock):
    return SymbolIdentityService(clock=clock)


def make_universe(identity, symbols, day=FIXED_DAY):
    """Enjekte 'resmi liste' provider'i ile UniverseBook kurar.

    Resmi liste test disindan verilir (UniverseBook liste URETMEZ).
    """
    book = UniverseBook(identity, clock=lambda: FIXED_NOW)
    book.load_official(list(symbols), day)
    return book


def universe_symbols(n=100, prefix="X"):
    """n adet test sembolu uretir (sirket ADI uretmez; yalniz test kodlari)."""
    return [f"{prefix}{i:03d}" for i in range(1, n + 1)]


def make_bar(symbol, day, close=100.0, volume=1000, currency="TRY"):
    """Gecerli OHLC bar sozlugu (blok8 make_raw deseni)."""
    return {
        "date": str(day),
        "open": float(close) - 0.5,
        "high": float(close) + 1.0,
        "low": float(close) - 1.5,
        "close": float(close),
        "volume": volume,
        "currency": currency,
        "stock_id": symbol,
    }


def price_series(symbol, day=FIXED_DAY, n=3, close=100.0, volume=1000):
    """Geriye dogru n gunluk gecerli bar serisi.

    day: str ("YYYY-MM-DD"), date veya datetime olabilir; her uc tip de
    desteklenir (testler FIXED_DAY str ve date nesnesi ile cagirir).
    """
    if isinstance(day, datetime):
        end = day.date()
    elif isinstance(day, date):
        end = day
    else:
        end = date.fromisoformat(day)
    return [
        make_bar(symbol, end - timedelta(days=i), close + i, volume)
        for i in range(n - 1, -1, -1)
    ]
