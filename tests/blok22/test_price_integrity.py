"""BLOK 22 - test_price_integrity: fiyat verisi butunlugu kabul testleri (8 test).

Kapsam: OHLC: high>=max(o,c,l), low<=min(o,c,h), bozuk bar reddi (3);
NULL/sifir: eksik gun None kalir, hacim 0 gercek sifir, None ASLA 0
olmaz (3); artimli: yalniz yeni gun eklenir, mevcut gun tekrar
eklenmez (2). GERCEK BLOK 8/9/10 modulleri; sahte yalniz fetcher.
"""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

from app.services.stock_scanning.price_collection import (
    HIGH_LT_MAX_OC,
    OK,
    PRICE_DATA_MISSING,
    LicensedSource,
    PriceCollectionConfig,
    PriceCollector,
    PriceStorage,
    is_valid_bar,
    validate_bar,
)
from app.services.stock_scanning.volume import VolumeStatus, classify_volume
from tests.blok22.conftest import make_bar, price_series

STOCK = "X001"
TODAY = date(2025, 6, 3)
ISO_CLOCK = "2025-06-03T08:00:00Z"


def _clock():
    return TODAY


def _iso_clock():
    return ISO_CLOCK


class _Fetcher:
    """Enjekte fetcher (blok8 MockFetcher deseni)."""

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


def _ns_bar(**kw):
    """validate_bar icin nitelikli bar (blok9 duck-typing deseni)."""
    base = dict(
        stock_id=STOCK, trade_date=TODAY.isoformat(), open=99.0, high=101.0,
        low=98.0, close=100.0, volume=1000, currency="TRY",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _collector(storage, fetcher, exc=None):
    if not isinstance(fetcher, _Fetcher):
        fetcher = _Fetcher(fetcher, exc)
    return PriceCollector(
        {"licensed": LicensedSource(fetcher=fetcher, clock=_iso_clock)},
        PriceCollectionConfig(source_priority=["licensed"]),
        storage,
        clock=_clock,
    )


# 1) OHLC kurallari -------------------------------------------------------------
def test_ohlc_high_covers_max_of_open_close_low():
    # high >= max(open, close, low) saglanan bar gecerlidir
    bar = _ns_bar(open=99.0, close=100.0, low=98.0, high=101.0)
    assert validate_bar(bar) == []
    assert is_valid_bar(bar) is True


def test_ohlc_low_below_min_of_open_close_high():
    # low <= min(open, close, high) saglanan bar gecerlidir
    bar = _ns_bar(open=100.5, close=100.0, high=101.0, low=97.5)
    assert is_valid_bar(bar) is True


def test_broken_bar_rejected_high_below_close():
    # high < close -> bozuk bar REDDEDILIR (gercek kural kodu)
    bar = _ns_bar(open=99.0, close=105.0, high=103.0, low=98.0)
    errors = validate_bar(bar)
    assert is_valid_bar(bar) is False
    assert HIGH_LT_MAX_OC in errors


# 2) NULL / sifir ayrimi ---------------------------------------------------------
def test_missing_price_day_stays_none_not_zero():
    # Kaynak bos -> PRICE_DATA_MISSING; hic bar yazilmaz (None, ASLA 0 degil)
    storage = PriceStorage(conn=None, clock=_iso_clock)
    col = _collector(storage, [], exc=None)
    res = col.bootstrap(STOCK)
    assert res.status == PRICE_DATA_MISSING
    assert storage.count_bars(STOCK) == 0


def test_volume_zero_is_real_zero_not_missing():
    # Hacim 0 GERCEK sifirdir: kural ihlali degildir, MISSING siniflanmaz
    bar = _ns_bar(volume=0)
    assert validate_bar(bar) == []
    status, reason = classify_volume(last_volume=0, avg20=100.0, ratio=0.0)
    assert status != VolumeStatus.MISSING
    assert status == VolumeStatus.REVIEW_REQUIRED  # aciklanmamis sifir


def test_none_volume_never_becomes_zero():
    # None hacim ASLA 0'a cevrilmez: MISSING siniflanir
    status, _ = classify_volume(last_volume=None, avg20=100.0)
    assert status == VolumeStatus.MISSING
    status_zero, _ = classify_volume(last_volume=0, avg20=100.0, ratio=0.0)
    assert status_zero != VolumeStatus.MISSING  # 0 gercek sifir, farkli sinif


# 3) Artimli guncelleme ----------------------------------------------------------
def test_incremental_only_new_day_written():
    storage = PriceStorage(conn=None, clock=_iso_clock)
    series = price_series(STOCK, TODAY - timedelta(days=1), n=5)
    fetcher = _Fetcher(list(series))
    col = _collector(storage, fetcher)
    col.bootstrap(STOCK)
    assert storage.count_bars(STOCK) == 5
    fetcher.records.append(make_bar(STOCK, TODAY, close=105.0))
    res = col.incremental_update(STOCK)
    assert res.status == OK
    assert res.bars_written == 1  # yalniz YENI gun eklendi
    assert storage.count_bars(STOCK) == 6


def test_incremental_existing_days_not_rewritten():
    storage = PriceStorage(conn=None, clock=_iso_clock)
    series = price_series(STOCK, TODAY - timedelta(days=1), n=5)
    fetcher = _Fetcher(list(series))
    col = _collector(storage, fetcher)
    col.bootstrap(STOCK)
    old_date = series[0]["date"]
    old_close = storage.get_bar(STOCK, old_date, "licensed").close
    fetcher.records.append(make_bar(STOCK, TODAY, close=105.0))
    col.incremental_update(STOCK)
    # mevcut gun tekrar EKLENMEZ/degistirilmez: surum ve kapanis ayni kalir
    assert storage.latest_version(STOCK, old_date, "licensed") == "1"
    assert storage.get_bar(STOCK, old_date, "licensed").close == old_close
