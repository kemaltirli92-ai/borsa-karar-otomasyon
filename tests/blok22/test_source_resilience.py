"""BLOK 22 - test_source_resilience: kaynak dayanikliligi kabul testleri (5 test).

Kapsam: kaynak gecisi: ana kaynak hata -> yedek kaynak + fallback kaydi
(2); kaynak fiyat farki: esik ustu fark tespiti + hangi kaynak secildi
(3). GERCEK BLOK 8 collector; sahte yalniz fetcher seviyesinde.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.services.stock_scanning.price_collection import (
    FAILED,
    OK,
    PRICE_DATA_MISSING,
    PRICE_SOURCE_DIVERGENCE,
    SOURCE_SWITCHED,
    LicensedSource,
    PriceCollectionConfig,
    PriceCollector,
    PriceStorage,
    YFinanceSource,
    close_diff_pct,
    within_close_tolerance,
)
from tests.blok22.conftest import price_series

STOCK = "X001"
TODAY = date(2025, 6, 3)
ISO_CLOCK = "2025-06-03T08:00:00Z"


def _clock():
    return TODAY


def _iso_clock():
    return ISO_CLOCK


class _Fetcher:
    def __init__(self, records=None, exc=None):
        self.records = list(records or [])
        self.exc = exc

    def __call__(self, stock_id, days=None, date=None):
        if self.exc is not None:
            raise self.exc
        recs = sorted(self.records, key=lambda r: r["date"])
        if days is not None:
            return recs[-days:] if days > 0 else []
        return recs


def _storage():
    return PriceStorage(conn=None, clock=_iso_clock)


def _two_source_collector(storage, primary, secondary):
    return PriceCollector(
        {
            "licensed": LicensedSource(fetcher=primary, clock=_iso_clock),
            "yfinance": YFinanceSource(fetcher=secondary, clock=_iso_clock),
        },
        PriceCollectionConfig(source_priority=["licensed", "yfinance"]),
        storage,
        clock=_clock,
    )


# 1) kaynak gecisi: ana hata -> yedek --------------------------------------------
def test_primary_error_switches_to_backup_source():
    storage = _storage()
    feed = price_series(STOCK, TODAY, n=5)
    col = _two_source_collector(
        storage,
        _Fetcher(exc=RuntimeError("ana kaynak cevap vermedi")),
        _Fetcher(feed),
    )
    res = col.bootstrap(STOCK)
    assert res.status == OK
    assert res.source_used == "yfinance"
    assert res.bars_written == 5


def test_fallback_switch_recorded_with_reason():
    storage = _storage()
    col = _two_source_collector(
        storage,
        _Fetcher(exc=RuntimeError("ana kaynak cevap vermedi")),
        _Fetcher(price_series(STOCK, TODAY, n=3)),
    )
    col.bootstrap(STOCK)
    switches = col.events_by_code(SOURCE_SWITCHED)
    assert len(switches) == 1
    assert switches[0]["from_source"] == "licensed"
    assert switches[0]["to_source"] == "yfinance"
    assert "ana kaynak" in switches[0]["reason"]


# 2) kaynak fiyat farki -----------------------------------------------------------
def test_both_sources_fail_price_missing_no_write():
    storage = _storage()
    col = _two_source_collector(
        storage,
        _Fetcher(exc=RuntimeError("ana hata")),
        _Fetcher(exc=RuntimeError("yedek hata")),
    )
    res = col.bootstrap(STOCK)
    assert res.status in (FAILED, PRICE_DATA_MISSING)
    assert storage.count_bars(STOCK) == 0  # hic yazim yok


def test_source_price_divergence_above_threshold_detected():
    # Esik ustu kapanis farki: close_diff_pct gercek fonksiyonla tespit
    assert close_diff_pct(100.0, 105.0) == 5.0
    assert within_close_tolerance(100.0, 105.0, 2.0) is False
    # Collector: dogrulama kaynagi kapanisi tolerans disi -> DIVERGENCE.
    # blok8 kalibi: gercek capraz-kaynak API'si validate_against'tir
    # (bootstrap karsilastirma YAPMAZ; validation_source ile dogrulanir).
    storage = _storage()
    diverged = price_series(STOCK, TODAY, n=3, close=100.0)
    diverged[-1]["close"] = 130.0  # bugunun barinda %30 fark (esik 2.0)
    diverged[-1]["open"] = 129.0
    diverged[-1]["high"] = 131.0
    diverged[-1]["low"] = 128.0
    col = PriceCollector(
        {
            "licensed": LicensedSource(
                fetcher=_Fetcher(price_series(STOCK, TODAY, n=3)),
                clock=_iso_clock,
            ),
            "yfinance": YFinanceSource(
                fetcher=_Fetcher(diverged), clock=_iso_clock
            ),
        },
        PriceCollectionConfig(
            source_priority=["licensed", "yfinance"],
            validation_source="yfinance",
            close_tolerance_pct=2.0,
        ),
        storage,
        clock=_clock,
    )
    primary_bar = SimpleNamespace(close=100.0, source="licensed")
    res = col.validate_against(STOCK, TODAY.isoformat(), primary_bar)
    assert res.status == PRICE_SOURCE_DIVERGENCE
    assert res.diff_pct == 30.0
    assert res.reference_source == "yfinance"


def test_within_tolerance_primary_source_selected():
    # Tolerans icinde fark: ana kaynak secilir, gecis/divergence YOK
    storage = _storage()
    primary_feed = price_series(STOCK, TODAY, n=4, close=100.0)
    secondary_feed = price_series(STOCK, TODAY, n=4, close=100.5)
    col = _two_source_collector(
        storage, _Fetcher(primary_feed), _Fetcher(secondary_feed)
    )
    res = col.bootstrap(STOCK)
    assert res.status == OK
    assert res.source_used == "licensed"  # ana kaynak secildi
    assert col.events_by_code(SOURCE_SWITCHED) == []
    assert within_close_tolerance(100.0, 100.5, 2.0) is True
