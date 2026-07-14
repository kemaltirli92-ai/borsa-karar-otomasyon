"""BLOK 8 - Fiyat Verisi Toplama: TAM 100 pytest testi.

Kategoriler (toplam = 100, SPEC BLOK 8 bolum 8):
1. Coklu kaynak + kaynak gecisi (16): ana basarisiz -> yedek; gecis logu;
   yedek de basarisiz -> sonraki.
2. Iki kaynak da bos (10): PRICE_DATA_MISSING + NULL, hic yazim yok.
3. Bootstrap 260+ gun (12): dogru sayida bar, tarih sirasi, eksik gun eleme.
4. Artimli guncelleme (14): son tarihten sonrasini cek, var olanlara dokunma.
5. Son 10 gun tekrar kontrol (12): degisen bar guncellenir, ayni bar atlanir.
6. Kopya engeli (12): ayni veri tekrar gelirse unique anahtarla yazilmaz.
7. Kaynaklar arasi fark (12): tolerans icinde/disinda,
   VALIDATION_SOURCE_UNAVAILABLE.
8. Eski veri + yanlis para birimi + bozuk bar reddi + config/yonetici
   onceligi (12).

Hicbir test ag erisimi yapmaz: tum kaynaklar mock fetcher ile enjekte
edilir. Her test temiz calisir: bellek ici storage veya tmp_path uzerinde
bos gecici DB (BLOK 7 migration'lari uygulanmis). Saat enjekte edilir
(deterministik).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

import pytest

from app.services.stock_scanning.db import MigrationRunner
from app.services.stock_scanning.price_collection import (
    BAR_SKIPPED,
    ConfigError,
    GoogleFinanceSource,
    HIGH_LT_LOW,
    HIGH_LT_MAX_OC,
    LicensedSource,
    NEGATIVE_PRICE,
    BAD_CURRENCY,
    OK,
    PARTIAL,
    FAILED,
    PRICE_DATA_MISSING,
    PRICE_SOURCE_DIVERGENCE,
    RECHECK_UPDATED,
    SOURCE_SWITCHED,
    STALE_PRICE_DATA,
    VALIDATION_SOURCE_UNAVAILABLE,
    WRONG_CURRENCY,
    PriceBar,
    PriceCollectionConfig,
    PriceCollector,
    PriceStorage,
    SourceUnavailableError,
    YFinanceSource,
    close_diff_pct,
    is_valid_bar,
    validate_bar,
    within_close_tolerance,
)

STOCK = "THYAO"
FIXED_TODAY = date(2024, 6, 30)
ISO_CLOCK = "2024-06-30T08:00:00Z"


def fixed_clock():
    """Deterministik 'bugun' (collector icin, date nesnesi doner)."""
    return FIXED_TODAY


def fixed_iso_clock():
    """Deterministik ISO damgasi (kaynak/storage icin)."""
    return ISO_CLOCK


# ---------------------------------------------------------------------- #
# Yardimcilar
# ---------------------------------------------------------------------- #
class MockFetcher:
    """Enjekte edilen sahte kaynak fetcher'i (gercek ag YOK).

    Sozlesme: fetcher(stock_id, days=None, date=None) -> list[dict].
    exc verilirse her cagrida firlatilir (kaynak hatasi simulasyonu).
    """

    def __init__(self, records=None, exc=None):
        self.records = list(records or [])
        self.exc = exc
        self.calls = []

    def __call__(self, stock_id, days=None, date=None):
        self.calls.append({"stock_id": stock_id, "days": days, "date": date})
        if self.exc is not None:
            raise self.exc
        recs = [r for r in self.records if r.get("stock_id") in (None, stock_id)]
        recs = sorted(recs, key=lambda r: r["date"])
        if date is not None:
            return [r for r in recs if r["date"] == str(date)]
        if days is not None:
            return recs[-days:] if days > 0 else []
        return recs


def make_raw(day, close=100.0, *, open_=None, high=None, low=None,
             volume=1000, currency="TRY", stock_id=None, extra=None):
    """Gecerli (veya istenirse bozuk) ham kayit sozlugu uretir."""
    if isinstance(day, date):
        day = day.isoformat()
    o = open_ if open_ is not None else close
    h = high if high is not None else close + 1.0
    l = low if low is not None else close - 1.0
    rec = {
        "date": day,
        "open": float(o),
        "high": float(h),
        "low": float(l),
        "close": float(close),
        "volume": int(volume),
        "currency": currency,
    }
    if stock_id is not None:
        rec["stock_id"] = stock_id
    if extra:
        rec.update(extra)
    return rec


def make_series(end_day, n, close=100.0, step=0.5, **kw):
    """end_day (dahil) geriye dogru n gunluk ham kayit serisi (artan)."""
    start = end_day - timedelta(days=n - 1)
    return [
        make_raw(start + timedelta(days=i), close=round(close + i * step, 4), **kw)
        for i in range(n)
    ]


def with_change(records, day, *, close=None, volume=None):
    """Serinin kopyasini dondurur; verilen gunun close/volume'unu degistirir
    (bar gecerliligi korunur: high/low/open yeniden ayarlanir)."""
    if isinstance(day, date):
        day = day.isoformat()
    out = [dict(r) for r in records]
    for rec in out:
        if rec["date"] == day:
            if close is not None:
                rec["close"] = float(close)
                rec["open"] = float(close)
                rec["high"] = float(close) + 1.0
                rec["low"] = float(close) - 1.0
            if volume is not None:
                rec["volume"] = int(volume)
    return out


def make_bar(stock_id, trade_date, close=100.0, *, source="licensed",
             volume=1000, currency="TRY"):
    """Dogrudan PriceBar uretir (storage seed icin)."""
    if isinstance(trade_date, date):
        trade_date = trade_date.isoformat()
    return PriceBar(
        stock_id=stock_id,
        trade_date=trade_date,
        open=float(close),
        high=float(close) + 1.0,
        low=float(close) - 1.0,
        close=float(close),
        volume=int(volume),
        currency=currency,
        source=source,
        collected_timestamp=ISO_CLOCK,
    )


def seed_storage(storage, stock_id, records, source="licensed"):
    """Ham kayitlari PriceBar'a cevirip storage'a yazar (surum '1')."""
    bars = [
        make_bar(
            stock_id,
            r["date"],
            close=r["close"],
            source=source,
            volume=r["volume"],
            currency=r.get("currency", "TRY"),
        )
        for r in records
    ]
    return storage.write_bars(stock_id, bars)


# ---------------------------------------------------------------------- #
# Fixture'lar
# ---------------------------------------------------------------------- #
@pytest.fixture
def spy():
    """Liste tabanli log yakalayici: (code, payload) ciftleri."""
    events = []

    def logger(code, payload):
        events.append((code, payload))

    return events, logger


@pytest.fixture
def mem_storage():
    return PriceStorage(conn=None, clock=fixed_iso_clock)


@pytest.fixture
def db_conn(tmp_path):
    """BLOK 7 migration'lari uygulanmis bos gecici DB baglantisi."""
    db_path = str(tmp_path / "blok8.db")
    MigrationRunner(db_path, clock=fixed_iso_clock).apply_all()
    conn = sqlite3.connect(db_path)
    yield conn
    conn.close()


@pytest.fixture
def db_storage(db_conn):
    return PriceStorage(conn=db_conn, clock=fixed_iso_clock)


def make_collector(sources, *, config=None, storage=None, logger=None):
    return PriceCollector(
        sources,
        config or PriceCollectionConfig(),
        storage if storage is not None else PriceStorage(conn=None, clock=fixed_iso_clock),
        logger=logger,
        clock=fixed_clock,
    )


# ====================================================================== #
# Kategori 1: Coklu kaynak + kaynak gecisi (16 test)
# ====================================================================== #
class TestSourceSwitching:
    def test_primary_success_no_switch(self, mem_storage):
        feed = make_series(FIXED_TODAY, 5)
        col = make_collector(
            {"licensed": LicensedSource(fetcher=MockFetcher(feed), clock=fixed_iso_clock)},
            config=PriceCollectionConfig(source_priority=["licensed", "yfinance"]),
            storage=mem_storage,
        )
        res = col.bootstrap(STOCK)
        assert res.status == OK
        assert res.source_used == "licensed"
        assert col.events_by_code(SOURCE_SWITCHED) == []

    def test_primary_fetcher_none_switches_to_yfinance(self, mem_storage):
        feed = make_series(FIXED_TODAY, 5)
        col = make_collector(
            {
                "licensed": LicensedSource(fetcher=None),
                "yfinance": YFinanceSource(fetcher=MockFetcher(feed), clock=fixed_iso_clock),
            },
            storage=mem_storage,
        )
        res = col.bootstrap(STOCK)
        assert res.status == OK
        assert res.source_used == "yfinance"
        switches = col.events_by_code(SOURCE_SWITCHED)
        assert len(switches) == 1
        assert switches[0]["from_source"] == "licensed"
        assert switches[0]["to_source"] == "yfinance"

    def test_primary_exception_switches_to_backup(self, mem_storage):
        feed = make_series(FIXED_TODAY, 5)
        col = make_collector(
            {
                "licensed": LicensedSource(fetcher=MockFetcher(exc=RuntimeError("boom"))),
                "yfinance": YFinanceSource(fetcher=MockFetcher(feed), clock=fixed_iso_clock),
            },
            storage=mem_storage,
        )
        res = col.bootstrap(STOCK)
        assert res.status == OK
        assert res.source_used == "yfinance"
        assert res.bars_written == 5

    def test_switch_log_has_from_to_reason(self, mem_storage):
        feed = make_series(FIXED_TODAY, 3)
        col = make_collector(
            {
                "licensed": LicensedSource(fetcher=MockFetcher(exc=RuntimeError("boom"))),
                "yfinance": YFinanceSource(fetcher=MockFetcher(feed), clock=fixed_iso_clock),
            },
            storage=mem_storage,
        )
        col.bootstrap(STOCK)
        event = col.events_by_code(SOURCE_SWITCHED)[0]
        assert event["from_source"] == "licensed"
        assert event["to_source"] == "yfinance"
        assert "boom" in event["reason"]
        assert event["stock_id"] == STOCK

    def test_priority_order_respected_yfinance_first(self, mem_storage):
        feed = make_series(FIXED_TODAY, 4)
        col = make_collector(
            {
                "licensed": LicensedSource(fetcher=None),
                "yfinance": YFinanceSource(fetcher=MockFetcher(feed), clock=fixed_iso_clock),
            },
            config=PriceCollectionConfig(source_priority=["yfinance", "licensed"]),
            storage=mem_storage,
        )
        res = col.bootstrap(STOCK)
        assert res.status == OK
        assert res.source_used == "yfinance"
        assert col.events_by_code(SOURCE_SWITCHED) == []

    def test_first_source_empty_switches_to_second(self, mem_storage):
        feed = make_series(FIXED_TODAY, 4)
        col = make_collector(
            {
                "licensed": LicensedSource(fetcher=MockFetcher([])),
                "yfinance": YFinanceSource(fetcher=MockFetcher(feed), clock=fixed_iso_clock),
            },
            storage=mem_storage,
        )
        res = col.bootstrap(STOCK)
        assert res.source_used == "yfinance"
        event = col.events_by_code(SOURCE_SWITCHED)[0]
        assert event["reason"] == "empty"

    def test_all_bars_rejected_wrong_currency_switches(self, mem_storage):
        usd_feed = [make_raw(FIXED_TODAY, currency="USD")]
        try_feed = make_series(FIXED_TODAY, 3)
        col = make_collector(
            {
                "licensed": LicensedSource(fetcher=MockFetcher(usd_feed), clock=fixed_iso_clock),
                "yfinance": YFinanceSource(fetcher=MockFetcher(try_feed), clock=fixed_iso_clock),
            },
            storage=mem_storage,
        )
        res = col.bootstrap(STOCK)
        assert res.source_used == "yfinance"
        assert res.status == PARTIAL
        assert WRONG_CURRENCY in res.warnings
        event = col.events_by_code(SOURCE_SWITCHED)[0]
        assert event["reason"] == "all_rejected"

    def test_unregistered_source_skipped_with_switch_log(self, mem_storage):
        feed = make_series(FIXED_TODAY, 3)
        col = make_collector(
            {"licensed": LicensedSource(fetcher=MockFetcher(feed), clock=fixed_iso_clock)},
            config=PriceCollectionConfig(source_priority=["google", "licensed"]),
            storage=mem_storage,
        )
        res = col.bootstrap(STOCK)
        assert res.status == OK
        assert res.source_used == "licensed"
        event = col.events_by_code(SOURCE_SWITCHED)[0]
        assert event["from_source"] == "google"
        assert event["reason"] == "not_registered"

    def test_three_sources_two_failures_two_switch_logs(self, mem_storage):
        feed = make_series(FIXED_TODAY, 3)
        col = make_collector(
            {
                "licensed": LicensedSource(fetcher=MockFetcher(exc=RuntimeError("e1"))),
                "yfinance": YFinanceSource(fetcher=MockFetcher(exc=RuntimeError("e2"))),
                "google": GoogleFinanceSource(fetcher=MockFetcher(feed), clock=fixed_iso_clock),
            },
            config=PriceCollectionConfig(source_priority=["licensed", "yfinance", "google"]),
            storage=mem_storage,
        )
        res = col.bootstrap(STOCK)
        assert res.status == OK
        assert res.source_used == "google"
        switches = col.events_by_code(SOURCE_SWITCHED)
        assert len(switches) == 2
        assert switches[0]["from_source"] == "licensed"
        assert switches[1]["from_source"] == "yfinance"

    def test_incremental_switches_on_failure(self, mem_storage):
        seed_feed = make_series(FIXED_TODAY - timedelta(days=1), 5)
        seed_col = make_collector(
            {"yfinance": YFinanceSource(fetcher=MockFetcher(seed_feed), clock=fixed_iso_clock)},
            config=PriceCollectionConfig(source_priority=["yfinance"]),
            storage=mem_storage,
        )
        seed_col.bootstrap(STOCK)

        new_feed = make_series(FIXED_TODAY, 6)
        col = make_collector(
            {
                "yfinance": YFinanceSource(fetcher=MockFetcher(exc=RuntimeError("down"))),
                "licensed": LicensedSource(fetcher=MockFetcher(new_feed), clock=fixed_iso_clock),
            },
            config=PriceCollectionConfig(source_priority=["yfinance", "licensed"]),
            storage=mem_storage,
        )
        res = col.incremental_update(STOCK)
        assert res.source_used == "licensed"
        assert res.bars_written == 1
        assert col.events_by_code(SOURCE_SWITCHED)

    def test_incremental_switch_log_reason_recorded(self, mem_storage):
        seed_feed = make_series(FIXED_TODAY - timedelta(days=1), 5)
        seed_col = make_collector(
            {"yfinance": YFinanceSource(fetcher=MockFetcher(seed_feed), clock=fixed_iso_clock)},
            config=PriceCollectionConfig(source_priority=["yfinance"]),
            storage=mem_storage,
        )
        seed_col.bootstrap(STOCK)

        col = make_collector(
            {
                "yfinance": YFinanceSource(fetcher=MockFetcher(exc=RuntimeError("boom"))),
                "licensed": LicensedSource(
                    fetcher=MockFetcher(make_series(FIXED_TODAY, 6)), clock=fixed_iso_clock
                ),
            },
            config=PriceCollectionConfig(source_priority=["yfinance", "licensed"]),
            storage=mem_storage,
        )
        col.incremental_update(STOCK)
        event = col.events_by_code(SOURCE_SWITCHED)[0]
        assert "boom" in event["reason"]

    def test_result_source_used_after_switch(self, mem_storage):
        feed = make_series(FIXED_TODAY, 4)
        col = make_collector(
            {
                "licensed": LicensedSource(fetcher=None),
                "yfinance": YFinanceSource(fetcher=MockFetcher(feed), clock=fixed_iso_clock),
            },
            storage=mem_storage,
        )
        res = col.bootstrap(STOCK)
        assert res.source_used == "yfinance"

    def test_no_events_on_primary_success(self, mem_storage):
        feed = make_series(FIXED_TODAY, 5)
        col = make_collector(
            {"licensed": LicensedSource(fetcher=MockFetcher(feed), clock=fixed_iso_clock)},
            config=PriceCollectionConfig(source_priority=["licensed"]),
            storage=mem_storage,
        )
        res = col.bootstrap(STOCK)
        assert res.status == OK
        assert col.events == []

    def test_fetch_history_raises_when_fetcher_none(self):
        src = YFinanceSource(fetcher=None)
        with pytest.raises(SourceUnavailableError):
            src.fetch_history(STOCK, 5)

    def test_licensed_source_without_fetcher_unavailable(self):
        src = LicensedSource(fetcher=None)
        with pytest.raises(SourceUnavailableError):
            src.fetch_latest(STOCK)

    def test_google_source_without_fetcher_unavailable(self):
        src = GoogleFinanceSource(fetcher=None)
        with pytest.raises(SourceUnavailableError):
            src.fetch_date(STOCK, FIXED_TODAY.isoformat())


# ====================================================================== #
# Kategori 2: Iki kaynak da bos (10 test)
# ====================================================================== #
class TestBothSourcesEmpty:
    def _collector(self, storage, licensed_exc=False):
        lic_fetcher = MockFetcher(exc=RuntimeError("down")) if licensed_exc else MockFetcher([])
        return make_collector(
            {
                "licensed": LicensedSource(fetcher=lic_fetcher),
                "yfinance": YFinanceSource(fetcher=MockFetcher([])),
            },
            storage=storage,
        )

    def test_both_empty_status_price_data_missing(self, mem_storage):
        res = self._collector(mem_storage).bootstrap(STOCK)
        assert res.status == PRICE_DATA_MISSING

    def test_both_empty_nothing_written(self, mem_storage):
        self._collector(mem_storage).bootstrap(STOCK)
        assert mem_storage.count_bars(STOCK) == 0

    def test_both_empty_event_logged(self, mem_storage):
        col = self._collector(mem_storage)
        col.bootstrap(STOCK)
        assert col.events_by_code(PRICE_DATA_MISSING)

    def test_both_empty_bars_written_zero(self, mem_storage):
        res = self._collector(mem_storage).bootstrap(STOCK)
        assert res.bars_written == 0

    def test_both_empty_source_used_none(self, mem_storage):
        res = self._collector(mem_storage).bootstrap(STOCK)
        assert res.source_used is None

    def test_both_empty_errors_contain_code(self, mem_storage):
        res = self._collector(mem_storage).bootstrap(STOCK)
        assert PRICE_DATA_MISSING in res.errors

    def test_one_raises_one_empty_missing(self, mem_storage):
        res = self._collector(mem_storage, licensed_exc=True).bootstrap(STOCK)
        assert res.status == PRICE_DATA_MISSING
        assert mem_storage.count_bars(STOCK) == 0

    def test_incremental_both_empty_failed_status(self, mem_storage):
        seed = make_collector(
            {"yfinance": YFinanceSource(fetcher=MockFetcher(make_series(FIXED_TODAY, 5)), clock=fixed_iso_clock)},
            config=PriceCollectionConfig(source_priority=["yfinance"]),
            storage=mem_storage,
        )
        seed.bootstrap(STOCK)
        res = self._collector(mem_storage).incremental_update(STOCK)
        assert res.status == FAILED

    def test_incremental_both_empty_existing_untouched(self, mem_storage):
        seed = make_collector(
            {"yfinance": YFinanceSource(fetcher=MockFetcher(make_series(FIXED_TODAY, 5)), clock=fixed_iso_clock)},
            config=PriceCollectionConfig(source_priority=["yfinance"]),
            storage=mem_storage,
        )
        seed.bootstrap(STOCK)
        last_before = mem_storage.get_last_trade_date(STOCK)
        self._collector(mem_storage).incremental_update(STOCK)
        assert mem_storage.count_bars(STOCK) == 5
        assert mem_storage.get_last_trade_date(STOCK) == last_before

    def test_missing_result_object_not_none_with_stock_id(self, mem_storage):
        res = self._collector(mem_storage).bootstrap(STOCK)
        assert res is not None
        assert res.stock_id == STOCK
        assert res.bars_written == 0
        assert res.source_used is None


# ====================================================================== #
# Kategori 3: Bootstrap 260+ gun (12 test)
# ====================================================================== #
class TestBootstrap:
    def test_bootstrap_writes_exact_260(self, mem_storage):
        feed = make_series(FIXED_TODAY, 260)
        col = make_collector(
            {"licensed": LicensedSource(fetcher=MockFetcher(feed), clock=fixed_iso_clock)},
            config=PriceCollectionConfig(source_priority=["licensed"]),
            storage=mem_storage,
        )
        res = col.bootstrap(STOCK)
        assert res.bars_written == 260
        assert mem_storage.count_bars(STOCK) == 260

    def test_bootstrap_days_limit_respected(self, mem_storage):
        feed = make_series(FIXED_TODAY, 300)
        col = make_collector(
            {"licensed": LicensedSource(fetcher=MockFetcher(feed), clock=fixed_iso_clock)},
            config=PriceCollectionConfig(source_priority=["licensed"]),
            storage=mem_storage,
        )
        res = col.bootstrap(STOCK)
        assert res.bars_written == 260
        bars = mem_storage.get_bars(STOCK)
        assert bars[0].trade_date == (FIXED_TODAY - timedelta(days=259)).isoformat()
        assert bars[-1].trade_date == FIXED_TODAY.isoformat()

    def test_bootstrap_trade_dates_ascending(self, mem_storage):
        feed = make_series(FIXED_TODAY, 20)
        col = make_collector(
            {"licensed": LicensedSource(fetcher=MockFetcher(feed), clock=fixed_iso_clock)},
            config=PriceCollectionConfig(source_priority=["licensed"]),
            storage=mem_storage,
        )
        col.bootstrap(STOCK)
        dates = [b.trade_date for b in mem_storage.get_bars(STOCK)]
        assert dates == sorted(dates)
        assert len(dates) == len(set(dates))

    def test_bootstrap_db_mode_rows_written(self, db_storage, db_conn):
        feed = make_series(FIXED_TODAY, 5)
        col = make_collector(
            {"licensed": LicensedSource(fetcher=MockFetcher(feed), clock=fixed_iso_clock)},
            config=PriceCollectionConfig(source_priority=["licensed"]),
            storage=db_storage,
        )
        res = col.bootstrap(STOCK)
        assert res.bars_written == 5
        n = db_conn.execute(
            "SELECT COUNT(*) FROM stock_prices_daily WHERE stock_id = ?", (STOCK,)
        ).fetchone()[0]
        assert n == 5

    def test_bootstrap_db_data_layer_raw(self, db_storage, db_conn):
        feed = make_series(FIXED_TODAY, 5)
        col = make_collector(
            {"licensed": LicensedSource(fetcher=MockFetcher(feed), clock=fixed_iso_clock)},
            config=PriceCollectionConfig(source_priority=["licensed"]),
            storage=db_storage,
        )
        col.bootstrap(STOCK)
        rows = db_conn.execute(
            "SELECT DISTINCT data_layer FROM stock_prices_daily WHERE stock_id = ?",
            (STOCK,),
        ).fetchall()
        assert {r[0] for r in rows} == {"raw"}

    def test_bootstrap_gap_days_only_provided_written(self, mem_storage):
        days = [FIXED_TODAY - timedelta(days=d) for d in (4, 3, 1, 0)]
        feed = [make_raw(d) for d in days]
        col = make_collector(
            {"licensed": LicensedSource(fetcher=MockFetcher(feed), clock=fixed_iso_clock)},
            config=PriceCollectionConfig(source_priority=["licensed"]),
            storage=mem_storage,
        )
        res = col.bootstrap(STOCK)
        assert res.bars_written == 4
        written_dates = {b.trade_date for b in mem_storage.get_bars(STOCK)}
        assert written_dates == {d.isoformat() for d in days}

    def test_bootstrap_broken_record_skipped_logged(self, mem_storage, spy):
        events, logger = spy
        feed = make_series(FIXED_TODAY, 5)
        bad = {"date": (FIXED_TODAY - timedelta(days=10)).isoformat(),
               "open": 1.0, "high": 2.0, "low": 1.0, "volume": 10}
        src = LicensedSource(
            fetcher=MockFetcher(feed + [bad]), clock=fixed_iso_clock, logger=logger
        )
        col = make_collector(
            {"licensed": src},
            config=PriceCollectionConfig(source_priority=["licensed"]),
            storage=mem_storage,
        )
        res = col.bootstrap(STOCK)
        assert res.bars_written == 5
        assert any(code == BAR_SKIPPED for code, _ in events)

    def test_bootstrap_non_numeric_record_skipped(self, mem_storage):
        feed = make_series(FIXED_TODAY, 5)
        bad = make_raw(FIXED_TODAY - timedelta(days=10))
        bad["close"] = "abc"
        col = make_collector(
            {"licensed": LicensedSource(fetcher=MockFetcher(feed + [bad]), clock=fixed_iso_clock)},
            config=PriceCollectionConfig(source_priority=["licensed"]),
            storage=mem_storage,
        )
        res = col.bootstrap(STOCK)
        assert res.bars_written == 5
        assert mem_storage.count_bars(STOCK) == 5

    def test_bootstrap_result_source_used_first(self, mem_storage):
        feed = make_series(FIXED_TODAY, 3)
        col = make_collector(
            {"licensed": LicensedSource(fetcher=MockFetcher(feed), clock=fixed_iso_clock)},
            config=PriceCollectionConfig(source_priority=["licensed"]),
            storage=mem_storage,
        )
        res = col.bootstrap(STOCK)
        assert res.source_used == "licensed"

    def test_bootstrap_collected_timestamp_from_clock(self, mem_storage):
        feed = make_series(FIXED_TODAY, 3)
        col = make_collector(
            {"licensed": LicensedSource(fetcher=MockFetcher(feed), clock=fixed_iso_clock)},
            config=PriceCollectionConfig(source_priority=["licensed"]),
            storage=mem_storage,
        )
        col.bootstrap(STOCK)
        bar = mem_storage.get_bars(STOCK)[0]
        assert bar.collected_timestamp == ISO_CLOCK

    def test_bootstrap_data_version_one(self, db_storage, db_conn):
        feed = make_series(FIXED_TODAY, 5)
        col = make_collector(
            {"licensed": LicensedSource(fetcher=MockFetcher(feed), clock=fixed_iso_clock)},
            config=PriceCollectionConfig(source_priority=["licensed"]),
            storage=db_storage,
        )
        col.bootstrap(STOCK)
        rows = db_conn.execute(
            "SELECT DISTINCT data_version FROM stock_prices_daily WHERE stock_id = ?",
            (STOCK,),
        ).fetchall()
        assert {r[0] for r in rows} == {"1"}

    def test_bootstrap_ok_status_no_warnings(self, mem_storage):
        feed = make_series(FIXED_TODAY, 10)
        col = make_collector(
            {"licensed": LicensedSource(fetcher=MockFetcher(feed), clock=fixed_iso_clock)},
            config=PriceCollectionConfig(source_priority=["licensed"]),
            storage=mem_storage,
        )
        res = col.bootstrap(STOCK)
        assert res.status == OK
        assert res.warnings == []
        assert res.errors == []


# ====================================================================== #
# Kategori 4: Artimli guncelleme (14 test)
# ====================================================================== #
class TestIncrementalUpdate:
    def _seed_collector(self, storage, feed, source_name="licensed"):
        """Bootstrap ile seed eder; (collector, fetcher) doner — fetcher
        kayitlari sonradan genisletilebilir."""
        fetcher = MockFetcher(list(feed))
        cls = {"licensed": LicensedSource, "yfinance": YFinanceSource}[source_name]
        col = make_collector(
            {source_name: cls(fetcher=fetcher, clock=fixed_iso_clock)},
            config=PriceCollectionConfig(source_priority=[source_name]),
            storage=storage,
        )
        col.bootstrap(STOCK)
        return col, fetcher

    def test_incremental_writes_new_bars_after_last(self, mem_storage):
        feed = make_series(FIXED_TODAY - timedelta(days=3), 10)
        col, fetcher = self._seed_collector(mem_storage, feed)
        fetcher.records.extend(
            make_raw(FIXED_TODAY - timedelta(days=d)) for d in (2, 1, 0)
        )
        res = col.incremental_update(STOCK)
        assert res.bars_written == 3
        assert mem_storage.count_bars(STOCK) == 13

    def test_incremental_existing_bars_untouched(self, mem_storage):
        feed = make_series(FIXED_TODAY - timedelta(days=3), 10)
        col, fetcher = self._seed_collector(mem_storage, feed)
        old_date = feed[0]["date"]
        old_close = mem_storage.get_bar(STOCK, old_date, "licensed").close
        fetcher.records.extend(
            make_raw(FIXED_TODAY - timedelta(days=d)) for d in (2, 1, 0)
        )
        col.incremental_update(STOCK)
        assert mem_storage.latest_version(STOCK, old_date, "licensed") == "1"
        assert mem_storage.get_bar(STOCK, old_date, "licensed").close == old_close

    def test_incremental_last_trade_date_advances(self, mem_storage):
        feed = make_series(FIXED_TODAY - timedelta(days=3), 10)
        col, fetcher = self._seed_collector(mem_storage, feed)
        assert mem_storage.get_last_trade_date(STOCK) == (FIXED_TODAY - timedelta(days=3)).isoformat()
        fetcher.records.extend(
            make_raw(FIXED_TODAY - timedelta(days=d)) for d in (2, 1, 0)
        )
        col.incremental_update(STOCK)
        assert mem_storage.get_last_trade_date(STOCK) == FIXED_TODAY.isoformat()

    def test_incremental_old_dates_not_rewritten(self, mem_storage):
        feed = make_series(FIXED_TODAY - timedelta(days=2), 10)
        col, fetcher = self._seed_collector(mem_storage, feed)
        fetcher.records.extend(
            make_raw(FIXED_TODAY - timedelta(days=d)) for d in (1, 0)
        )
        res = col.incremental_update(STOCK)
        assert res.bars_skipped == 0
        # Eski 10 gun hala tek surum; toplam 12 satir.
        assert mem_storage.count_bars(STOCK) == 12

    def test_incremental_no_new_data_zero_written_ok(self, mem_storage):
        feed = make_series(FIXED_TODAY, 10)
        col, _ = self._seed_collector(mem_storage, feed)
        res = col.incremental_update(STOCK)
        assert res.bars_written == 0
        assert res.status == OK

    def test_incremental_uses_first_priority_source(self, mem_storage):
        fetcher_lic = MockFetcher(make_series(FIXED_TODAY - timedelta(days=1), 5))
        fetcher_yf = MockFetcher(make_series(FIXED_TODAY - timedelta(days=1), 5))
        col = make_collector(
            {
                "licensed": LicensedSource(fetcher=fetcher_lic, clock=fixed_iso_clock),
                "yfinance": YFinanceSource(fetcher=fetcher_yf, clock=fixed_iso_clock),
            },
            storage=mem_storage,
        )
        col.bootstrap(STOCK)
        fetcher_lic.records.append(make_raw(FIXED_TODAY))
        fetcher_yf.records.append(make_raw(FIXED_TODAY))
        calls_before = len(fetcher_lic.calls)
        col.incremental_update(STOCK)
        assert len(fetcher_lic.calls) == calls_before + 1
        assert fetcher_yf.calls == []

    def test_incremental_result_source_used(self, mem_storage):
        feed = make_series(FIXED_TODAY - timedelta(days=1), 5)
        col, fetcher = self._seed_collector(mem_storage, feed)
        fetcher.records.append(make_raw(FIXED_TODAY))
        res = col.incremental_update(STOCK)
        assert res.source_used == "licensed"

    def test_incremental_fetch_days_covers_gap_and_recheck(self, mem_storage):
        feed = make_series(FIXED_TODAY - timedelta(days=5), 10)
        col, fetcher = self._seed_collector(mem_storage, feed)
        fetcher.calls.clear()
        col.incremental_update(STOCK)
        # gap=5, recheck=10, buffer=2 -> 17
        assert fetcher.calls[-1]["days"] == 5 + 10 + 2

    def test_incremental_wrong_currency_new_bar_rejected(self, mem_storage):
        feed = make_series(FIXED_TODAY - timedelta(days=2), 8)
        col, fetcher = self._seed_collector(mem_storage, feed)
        fetcher.records.append(make_raw(FIXED_TODAY - timedelta(days=1)))
        fetcher.records.append(make_raw(FIXED_TODAY, currency="USD"))
        res = col.incremental_update(STOCK)
        assert res.bars_written == 1
        assert mem_storage.count_bars(STOCK) == 9
        assert col.events_by_code(WRONG_CURRENCY)

    def test_incremental_partial_status_on_rejection(self, mem_storage):
        feed = make_series(FIXED_TODAY - timedelta(days=2), 8)
        col, fetcher = self._seed_collector(mem_storage, feed)
        fetcher.records.append(make_raw(FIXED_TODAY - timedelta(days=1)))
        fetcher.records.append(make_raw(FIXED_TODAY, currency="USD"))
        res = col.incremental_update(STOCK)
        assert res.status == PARTIAL
        assert WRONG_CURRENCY in res.warnings

    def test_incremental_stale_warning_when_newest_old(self, mem_storage):
        feed = make_series(FIXED_TODAY - timedelta(days=20), 10)
        col, _ = self._seed_collector(mem_storage, feed)
        res = col.incremental_update(STOCK)
        assert STALE_PRICE_DATA in res.warnings
        assert col.events_by_code(STALE_PRICE_DATA)

    def test_incremental_empty_storage_falls_back_to_bootstrap(self, mem_storage):
        feed = make_series(FIXED_TODAY, 10)
        col = make_collector(
            {"licensed": LicensedSource(fetcher=MockFetcher(feed), clock=fixed_iso_clock)},
            config=PriceCollectionConfig(source_priority=["licensed"]),
            storage=mem_storage,
        )
        res = col.incremental_update(STOCK)
        assert res.status == OK
        assert res.bars_written == 10
        assert res.source_used == "licensed"

    def test_incremental_db_mode_writes_rows(self, db_storage):
        feed = make_series(FIXED_TODAY - timedelta(days=2), 5)
        col, fetcher = self._seed_collector(db_storage, feed)
        fetcher.records.extend(
            make_raw(FIXED_TODAY - timedelta(days=d)) for d in (1, 0)
        )
        res = col.incremental_update(STOCK)
        assert res.bars_written == 2
        assert db_storage.count_bars(STOCK) == 7

    def test_incremental_get_bars_includes_new(self, mem_storage):
        feed = make_series(FIXED_TODAY - timedelta(days=2), 5)
        col, fetcher = self._seed_collector(mem_storage, feed)
        fetcher.records.extend(
            make_raw(FIXED_TODAY - timedelta(days=d)) for d in (1, 0)
        )
        col.incremental_update(STOCK)
        bars = mem_storage.get_bars(STOCK)
        assert bars[-1].trade_date == FIXED_TODAY.isoformat()
        assert len(bars) == 7


# ====================================================================== #
# Kategori 5: Son 10 gun tekrar kontrol (12 test)
# ====================================================================== #
class TestRecheckLast10:
    def _recheck_collector(self, storage, feed):
        return make_collector(
            {"licensed": LicensedSource(fetcher=MockFetcher(feed), clock=fixed_iso_clock)},
            config=PriceCollectionConfig(source_priority=["licensed"]),
            storage=storage,
        )

    def test_recheck_changed_close_creates_new_version(self, mem_storage):
        series = make_series(FIXED_TODAY, 10)
        seed_storage(mem_storage, STOCK, series)
        d1 = FIXED_TODAY - timedelta(days=1)
        feed = with_change(series, d1, close=109.0)
        self._recheck_collector(mem_storage, feed).incremental_update(STOCK)
        assert mem_storage.get_bar(STOCK, d1, "licensed").close == 109.0
        assert mem_storage.count_bars(STOCK) == 11

    def test_recheck_new_version_is_two(self, mem_storage):
        series = make_series(FIXED_TODAY, 10)
        seed_storage(mem_storage, STOCK, series)
        d1 = FIXED_TODAY - timedelta(days=1)
        feed = with_change(series, d1, close=109.0)
        self._recheck_collector(mem_storage, feed).incremental_update(STOCK)
        assert mem_storage.latest_version(STOCK, d1.isoformat(), "licensed") == "2"

    def test_recheck_get_bars_returns_updated_close(self, mem_storage):
        series = make_series(FIXED_TODAY, 10)
        seed_storage(mem_storage, STOCK, series)
        d1 = FIXED_TODAY - timedelta(days=1)
        feed = with_change(series, d1, close=109.0)
        self._recheck_collector(mem_storage, feed).incremental_update(STOCK)
        bars = {b.trade_date: b for b in mem_storage.get_bars(STOCK)}
        assert bars[d1.isoformat()].close == 109.0
        assert len(bars) == 10

    def test_recheck_unchanged_bars_no_new_version(self, mem_storage):
        series = make_series(FIXED_TODAY, 10)
        seed_storage(mem_storage, STOCK, series)
        col = self._recheck_collector(mem_storage, list(series))
        res = col.incremental_update(STOCK)
        assert res.bars_updated == 0
        assert mem_storage.count_bars(STOCK) == 10

    def test_recheck_only_changed_date_updated(self, mem_storage):
        series = make_series(FIXED_TODAY, 10)
        seed_storage(mem_storage, STOCK, series)
        d3 = FIXED_TODAY - timedelta(days=3)
        feed = with_change(series, d3, close=150.0)
        self._recheck_collector(mem_storage, feed).incremental_update(STOCK)
        assert mem_storage.latest_version(STOCK, d3.isoformat(), "licensed") == "2"
        for rec in series:
            if rec["date"] != d3.isoformat():
                assert mem_storage.latest_version(STOCK, rec["date"], "licensed") == "1"

    def test_recheck_window_excludes_older_dates(self, mem_storage):
        series = make_series(FIXED_TODAY, 15)
        seed_storage(mem_storage, STOCK, series)
        d11 = FIXED_TODAY - timedelta(days=11)  # cekildi ama recheck penceresi disi
        d2 = FIXED_TODAY - timedelta(days=2)    # recheck penceresi icinde
        feed = with_change(series, d11, close=111.0)
        feed = with_change(feed, d2, close=122.0)
        self._recheck_collector(mem_storage, feed).incremental_update(STOCK)
        # d-11: pencere disinda -> dokunulmadi
        assert mem_storage.latest_version(STOCK, d11.isoformat(), "licensed") == "1"
        assert mem_storage.get_bar(STOCK, d11, "licensed").close != 111.0
        # d-2: guncellendi
        assert mem_storage.latest_version(STOCK, d2.isoformat(), "licensed") == "2"
        assert mem_storage.get_bar(STOCK, d2, "licensed").close == 122.0

    def test_recheck_updated_event_logged(self, mem_storage):
        series = make_series(FIXED_TODAY, 10)
        seed_storage(mem_storage, STOCK, series)
        d1 = FIXED_TODAY - timedelta(days=1)
        feed = with_change(series, d1, close=109.0)
        col = self._recheck_collector(mem_storage, feed)
        col.incremental_update(STOCK)
        events = col.events_by_code(RECHECK_UPDATED)
        assert len(events) == 1
        assert events[0]["trade_date"] == d1.isoformat()
        assert events[0]["old_version"] == "1"
        assert events[0]["new_version"] == "2"

    def test_recheck_multiple_changes_multiple_updates(self, mem_storage):
        series = make_series(FIXED_TODAY, 10)
        seed_storage(mem_storage, STOCK, series)
        feed = list(series)
        changed_days = [FIXED_TODAY - timedelta(days=d) for d in (1, 3, 5)]
        for i, day in enumerate(changed_days):
            feed = with_change(feed, day, close=200.0 + i)
        res = self._recheck_collector(mem_storage, feed).incremental_update(STOCK)
        assert res.bars_updated == 3
        assert mem_storage.count_bars(STOCK) == 13
        for day in changed_days:
            assert mem_storage.latest_version(STOCK, day.isoformat(), "licensed") == "2"

    def test_recheck_db_mode_row_count_increases(self, db_storage):
        series = make_series(FIXED_TODAY, 10)
        seed_storage(db_storage, STOCK, series)
        d1 = FIXED_TODAY - timedelta(days=1)
        feed = with_change(series, d1, close=109.0)
        self._recheck_collector(db_storage, feed).incremental_update(STOCK)
        assert db_storage.count_bars(STOCK) == 11
        assert db_storage.get_bar(STOCK, d1, "licensed").close == 109.0

    def test_recheck_db_mode_unchanged_row_count_same(self, db_storage):
        series = make_series(FIXED_TODAY, 10)
        seed_storage(db_storage, STOCK, series)
        res = self._recheck_collector(db_storage, list(series)).incremental_update(STOCK)
        assert res.bars_updated == 0
        assert db_storage.count_bars(STOCK) == 10

    def test_recheck_volume_change_triggers_update(self, mem_storage):
        series = make_series(FIXED_TODAY, 10)
        seed_storage(mem_storage, STOCK, series)
        d1 = FIXED_TODAY - timedelta(days=1)
        feed = with_change(series, d1, volume=series[-2]["volume"] + 500)
        res = self._recheck_collector(mem_storage, feed).incremental_update(STOCK)
        assert res.bars_updated == 1
        assert mem_storage.get_bar(STOCK, d1, "licensed").volume == series[-2]["volume"] + 500

    def test_recheck_result_bars_updated_count(self, mem_storage):
        series = make_series(FIXED_TODAY, 10)
        seed_storage(mem_storage, STOCK, series)
        d1 = FIXED_TODAY - timedelta(days=1)
        feed = with_change(series, d1, close=109.0)
        res = self._recheck_collector(mem_storage, feed).incremental_update(STOCK)
        assert res.bars_updated == 1
        assert res.status == OK


# ====================================================================== #
# Kategori 6: Kopya engeli (12 test)
# ====================================================================== #
class TestDuplicatePrevention:
    def test_write_bars_twice_second_all_skipped(self, mem_storage):
        bars = [make_bar(STOCK, FIXED_TODAY - timedelta(days=i)) for i in range(5)]
        wr1 = mem_storage.write_bars(STOCK, bars)
        wr2 = mem_storage.write_bars(STOCK, bars)
        assert wr1.written == 5
        assert wr2.written == 0

    def test_write_bars_skipped_count_returned(self, mem_storage):
        bars = [make_bar(STOCK, FIXED_TODAY - timedelta(days=i)) for i in range(5)]
        mem_storage.write_bars(STOCK, bars)
        wr2 = mem_storage.write_bars(STOCK, bars)
        assert wr2.skipped == 5

    def test_bootstrap_twice_second_writes_zero(self, mem_storage):
        feed = make_series(FIXED_TODAY, 5)
        col = make_collector(
            {"licensed": LicensedSource(fetcher=MockFetcher(feed), clock=fixed_iso_clock)},
            config=PriceCollectionConfig(source_priority=["licensed"]),
            storage=mem_storage,
        )
        res1 = col.bootstrap(STOCK)
        res2 = col.bootstrap(STOCK)
        assert res1.bars_written == 5
        assert res2.bars_written == 0
        assert res2.bars_skipped == 5
        assert res2.status == OK

    def test_unique_key_allows_different_source(self, mem_storage):
        day = FIXED_TODAY
        bars = [
            make_bar(STOCK, day, source="licensed"),
            make_bar(STOCK, day, source="yfinance"),
        ]
        wr = mem_storage.write_bars(STOCK, bars)
        assert wr.written == 2
        assert mem_storage.count_bars(STOCK) == 2

    def test_unique_key_allows_new_version(self, mem_storage):
        bar = make_bar(STOCK, FIXED_TODAY, close=100.0, source="licensed")
        mem_storage.write_bars(STOCK, [bar])
        new_bar = make_bar(STOCK, FIXED_TODAY, close=105.0, source="licensed")
        inserted = mem_storage.update_bar(STOCK, FIXED_TODAY.isoformat(), "licensed", new_bar, "2")
        assert inserted is True
        assert mem_storage.count_bars(STOCK) == 2

    def test_two_collectors_shared_storage_no_duplicates(self, mem_storage):
        feed = make_series(FIXED_TODAY, 5)
        sources = {
            "licensed": LicensedSource(fetcher=MockFetcher(feed), clock=fixed_iso_clock)
        }
        cfg = PriceCollectionConfig(source_priority=["licensed"])
        c1 = make_collector(sources, config=cfg, storage=mem_storage)
        c2 = make_collector(sources, config=cfg, storage=mem_storage)
        c1.bootstrap(STOCK)
        res2 = c2.bootstrap(STOCK)
        assert res2.bars_written == 0
        assert res2.bars_skipped == 5
        assert mem_storage.count_bars(STOCK) == 5

    def test_db_mode_dedup_on_rewrite(self, db_storage):
        bars = [make_bar(STOCK, FIXED_TODAY - timedelta(days=i)) for i in range(5)]
        db_storage.write_bars(STOCK, bars)
        db_storage.write_bars(STOCK, bars)
        assert db_storage.count_bars(STOCK) == 5

    def test_db_mode_skipped_count(self, db_storage):
        bars = [make_bar(STOCK, FIXED_TODAY - timedelta(days=i)) for i in range(5)]
        db_storage.write_bars(STOCK, bars)
        wr2 = db_storage.write_bars(STOCK, bars)
        assert wr2.written == 0
        assert wr2.skipped == 5

    def test_memory_row_count_unchanged_after_dup(self, mem_storage):
        bars = [make_bar(STOCK, FIXED_TODAY - timedelta(days=i)) for i in range(4)]
        mem_storage.write_bars(STOCK, bars)
        assert mem_storage.count_bars(STOCK) == 4
        mem_storage.write_bars(STOCK, bars)
        assert mem_storage.count_bars(STOCK) == 4

    def test_incremental_twice_second_writes_zero(self, mem_storage):
        feed = make_series(FIXED_TODAY, 10)
        col = make_collector(
            {"licensed": LicensedSource(fetcher=MockFetcher(feed), clock=fixed_iso_clock)},
            config=PriceCollectionConfig(source_priority=["licensed"]),
            storage=mem_storage,
        )
        col.bootstrap(STOCK)
        res1 = col.incremental_update(STOCK)
        res2 = col.incremental_update(STOCK)
        assert res1.bars_written == 0
        assert res2.bars_written == 0
        assert mem_storage.count_bars(STOCK) == 10

    def test_update_bar_same_version_skipped(self, mem_storage):
        bar = make_bar(STOCK, FIXED_TODAY, close=100.0, source="licensed")
        mem_storage.write_bars(STOCK, [bar])
        new_bar = make_bar(STOCK, FIXED_TODAY, close=105.0, source="licensed")
        first = mem_storage.update_bar(STOCK, FIXED_TODAY.isoformat(), "licensed", new_bar, "2")
        second = mem_storage.update_bar(STOCK, FIXED_TODAY.isoformat(), "licensed", new_bar, "2")
        assert first is True
        assert second is False
        assert mem_storage.count_bars(STOCK) == 2

    def test_write_bars_mixed_new_and_dup_counts(self, mem_storage):
        b1 = make_bar(STOCK, FIXED_TODAY - timedelta(days=2))
        b2 = make_bar(STOCK, FIXED_TODAY - timedelta(days=1))
        b3 = make_bar(STOCK, FIXED_TODAY)
        wr1 = mem_storage.write_bars(STOCK, [b1, b2])
        wr2 = mem_storage.write_bars(STOCK, [b2, b3])
        assert wr1.written == 2
        assert wr2.written == 1
        assert wr2.skipped == 1


# ====================================================================== #
# Kategori 7: Kaynaklar arasi fark (12 test)
# ====================================================================== #
class TestCrossSourceDivergence:
    DATE = FIXED_TODAY.isoformat()

    def _primary_bar(self, close=100.0):
        return make_bar(STOCK, FIXED_TODAY, close=close, source="licensed")

    def _collector(self, google_source, storage=None):
        return make_collector({"google": google_source}, storage=storage)

    def test_validate_within_tolerance_ok(self, mem_storage):
        g = GoogleFinanceSource(
            fetcher=MockFetcher([make_raw(FIXED_TODAY, close=100.3)]), clock=fixed_iso_clock
        )
        col = self._collector(g, mem_storage)
        res = col.validate_against(STOCK, self.DATE, self._primary_bar())
        assert res.status == OK
        assert res.diff_pct == pytest.approx(0.3)

    def test_validate_exact_boundary_ok(self, mem_storage):
        g = GoogleFinanceSource(
            fetcher=MockFetcher([make_raw(FIXED_TODAY, close=100.5)]), clock=fixed_iso_clock
        )
        col = self._collector(g, mem_storage)
        res = col.validate_against(STOCK, self.DATE, self._primary_bar())
        # Sinir degeri (0.5) tolerans icinde kabul edilir.
        assert res.status == OK
        assert res.diff_pct == pytest.approx(0.5)

    def test_validate_above_tolerance_divergence(self, mem_storage):
        g = GoogleFinanceSource(
            fetcher=MockFetcher([make_raw(FIXED_TODAY, close=101.0)]), clock=fixed_iso_clock
        )
        col = self._collector(g, mem_storage)
        res = col.validate_against(STOCK, self.DATE, self._primary_bar())
        assert res.status == PRICE_SOURCE_DIVERGENCE
        assert res.diff_pct == pytest.approx(1.0)

    def test_divergence_event_logged_with_diff(self, mem_storage):
        g = GoogleFinanceSource(
            fetcher=MockFetcher([make_raw(FIXED_TODAY, close=101.0)]), clock=fixed_iso_clock
        )
        col = self._collector(g, mem_storage)
        col.validate_against(STOCK, self.DATE, self._primary_bar())
        events = col.events_by_code(PRICE_SOURCE_DIVERGENCE)
        assert len(events) == 1
        assert events[0]["diff_pct"] == pytest.approx(1.0)
        assert events[0]["tolerance_pct"] == 0.5
        assert events[0]["primary_close"] == 100.0
        assert events[0]["reference_close"] == 101.0
        assert events[0]["reference_source"] == "google"

    def test_validation_source_fetcher_none_unavailable(self, mem_storage):
        col = self._collector(GoogleFinanceSource(fetcher=None), mem_storage)
        res = col.validate_against(STOCK, self.DATE, self._primary_bar())
        assert res.status == VALIDATION_SOURCE_UNAVAILABLE
        assert col.events_by_code(VALIDATION_SOURCE_UNAVAILABLE)

    def test_validation_source_exception_unavailable(self, mem_storage):
        g = GoogleFinanceSource(fetcher=MockFetcher(exc=RuntimeError("down")))
        col = self._collector(g, mem_storage)
        res = col.validate_against(STOCK, self.DATE, self._primary_bar())
        assert res.status == VALIDATION_SOURCE_UNAVAILABLE

    def test_validation_source_no_bar_unavailable(self, mem_storage):
        other_day = FIXED_TODAY - timedelta(days=30)
        g = GoogleFinanceSource(
            fetcher=MockFetcher([make_raw(other_day)]), clock=fixed_iso_clock
        )
        col = self._collector(g, mem_storage)
        res = col.validate_against(STOCK, self.DATE, self._primary_bar())
        assert res.status == VALIDATION_SOURCE_UNAVAILABLE
        event = col.events_by_code(VALIDATION_SOURCE_UNAVAILABLE)[0]
        assert event["reason"] == "no_bar"

    def test_validation_source_not_registered_unavailable(self, mem_storage):
        col = make_collector({}, storage=mem_storage)
        res = col.validate_against(STOCK, self.DATE, self._primary_bar())
        assert res.status == VALIDATION_SOURCE_UNAVAILABLE
        event = col.events_by_code(VALIDATION_SOURCE_UNAVAILABLE)[0]
        assert event["reason"] == "not_registered"

    def test_close_diff_pct_unit(self):
        assert close_diff_pct(100.0, 102.0) == pytest.approx(2.0)
        assert close_diff_pct(200.0, 201.0) == pytest.approx(0.5)

    def test_within_close_tolerance_unit(self):
        assert within_close_tolerance(100.0, 100.4, 0.5) is True
        assert within_close_tolerance(100.0, 101.0, 0.5) is False

    def test_close_diff_pct_absolute(self):
        assert close_diff_pct(100.0, 98.0) == pytest.approx(2.0)
        assert close_diff_pct(100.0, 102.0) == close_diff_pct(100.0, 98.0)

    def test_validation_result_fields(self, mem_storage):
        g = GoogleFinanceSource(
            fetcher=MockFetcher([make_raw(FIXED_TODAY, close=100.1)]), clock=fixed_iso_clock
        )
        col = self._collector(g, mem_storage)
        res = col.validate_against(STOCK, self.DATE, self._primary_bar())
        assert res.stock_id == STOCK
        assert res.trade_date == self.DATE
        assert res.reference_source == "google"
        assert res.status == OK


# ====================================================================== #
# Kategori 8: Eski veri + yanlis para birimi + bozuk bar + config (12)
# ====================================================================== #
class TestStaleCurrencyBrokenConfig:
    def test_bootstrap_stale_warning(self, mem_storage):
        feed = make_series(FIXED_TODAY - timedelta(days=30), 10)
        col = make_collector(
            {"licensed": LicensedSource(fetcher=MockFetcher(feed), clock=fixed_iso_clock)},
            config=PriceCollectionConfig(source_priority=["licensed"]),
            storage=mem_storage,
        )
        res = col.bootstrap(STOCK)
        assert res.bars_written == 10
        assert STALE_PRICE_DATA in res.warnings
        assert col.events_by_code(STALE_PRICE_DATA)

    def test_stale_boundary_not_stale(self, mem_storage):
        # stale_days_limit=7: tam 7 gun eski -> sinirda, STALE degil.
        feed = make_series(FIXED_TODAY - timedelta(days=7), 10)
        col = make_collector(
            {"licensed": LicensedSource(fetcher=MockFetcher(feed), clock=fixed_iso_clock)},
            config=PriceCollectionConfig(source_priority=["licensed"]),
            storage=mem_storage,
        )
        res = col.bootstrap(STOCK)
        assert STALE_PRICE_DATA not in res.warnings
        assert col.events_by_code(STALE_PRICE_DATA) == []

    def test_wrong_currency_rejected_logged_not_written(self, mem_storage):
        feed = [make_raw(FIXED_TODAY, currency="USD")]
        col = make_collector(
            {"licensed": LicensedSource(fetcher=MockFetcher(feed), clock=fixed_iso_clock)},
            config=PriceCollectionConfig(source_priority=["licensed"]),
            storage=mem_storage,
        )
        res = col.bootstrap(STOCK)
        assert res.status == PRICE_DATA_MISSING
        assert mem_storage.count_bars(STOCK) == 0
        events = col.events_by_code(WRONG_CURRENCY)
        assert len(events) == 1
        assert events[0]["currency"] == "USD"

    def test_allowed_usd_currency_accepted(self, mem_storage):
        feed = [make_raw(FIXED_TODAY, currency="USD")]
        cfg = PriceCollectionConfig(
            source_priority=["licensed"], allowed_currencies={"TRY", "USD"}
        )
        col = make_collector(
            {"licensed": LicensedSource(fetcher=MockFetcher(feed), clock=fixed_iso_clock)},
            config=cfg,
            storage=mem_storage,
        )
        res = col.bootstrap(STOCK)
        assert res.status == OK
        assert res.bars_written == 1

    def test_validate_bar_high_lt_low_invalid(self):
        bar = PriceBar(
            stock_id=STOCK, trade_date=FIXED_TODAY.isoformat(),
            open=99.0, high=98.0, low=99.0, close=98.5, volume=100,
        )
        errors = validate_bar(bar)
        assert HIGH_LT_LOW in errors
        assert is_valid_bar(bar) is False

    def test_validate_bar_negative_price_invalid(self):
        bar = PriceBar(
            stock_id=STOCK, trade_date=FIXED_TODAY.isoformat(),
            open=99.0, high=101.0, low=98.0, close=-5.0, volume=100,
        )
        errors = validate_bar(bar)
        assert NEGATIVE_PRICE in errors
        assert is_valid_bar(bar) is False

    def test_validate_bar_high_lt_open_invalid(self):
        bar = PriceBar(
            stock_id=STOCK, trade_date=FIXED_TODAY.isoformat(),
            open=105.0, high=102.0, low=99.0, close=100.0, volume=100,
        )
        errors = validate_bar(bar)
        assert HIGH_LT_MAX_OC in errors
        assert is_valid_bar(bar) is False

    def test_validate_bar_currency_format(self):
        bad = make_bar(STOCK, FIXED_TODAY, currency="TR")
        assert BAD_CURRENCY in validate_bar(bad)
        good = make_bar(STOCK, FIXED_TODAY, currency="TRY")
        assert validate_bar(good) == []
        assert is_valid_bar(good) is True

    def test_set_priority_changes_bootstrap_order(self, mem_storage):
        feed = make_series(FIXED_TODAY, 5)
        sources_default = {
            "licensed": LicensedSource(fetcher=MockFetcher([]), clock=fixed_iso_clock),
            "yfinance": YFinanceSource(fetcher=MockFetcher(feed), clock=fixed_iso_clock),
        }
        col1 = make_collector(sources_default, storage=mem_storage)
        col1.bootstrap(STOCK)
        assert col1.events_by_code(SOURCE_SWITCHED)  # licensed bos -> gecis oldu

        cfg = PriceCollectionConfig()
        cfg.set_priority(["yfinance", "licensed"])
        storage2 = PriceStorage(conn=None, clock=fixed_iso_clock)
        sources2 = {
            "licensed": LicensedSource(fetcher=MockFetcher([]), clock=fixed_iso_clock),
            "yfinance": YFinanceSource(fetcher=MockFetcher(feed), clock=fixed_iso_clock),
        }
        col2 = make_collector(sources2, config=cfg, storage=storage2)
        res2 = col2.bootstrap(STOCK)
        assert res2.source_used == "yfinance"
        assert col2.events_by_code(SOURCE_SWITCHED) == []  # oncelik degisti, gecis yok

    def test_set_priority_unknown_source_rejected(self):
        cfg = PriceCollectionConfig()
        original = list(cfg.source_priority)
        with pytest.raises(ConfigError):
            cfg.set_priority(["bogus"])
        assert cfg.source_priority == original
        with pytest.raises(ConfigError):
            PriceCollectionConfig.from_dict({"source_priority": ["bogus"]})

    def test_config_dict_round_trip(self):
        cfg = PriceCollectionConfig()
        cfg.set_priority(["yfinance", "licensed"])
        data = cfg.to_dict()
        json.dumps(data)  # JSON'a yazilabilir olmali
        cfg2 = PriceCollectionConfig.from_dict(data)
        assert cfg2.source_priority == ["yfinance", "licensed"]
        assert cfg2.validation_source == cfg.validation_source
        assert cfg2.close_tolerance_pct == cfg.close_tolerance_pct
        assert cfg2.bootstrap_days == cfg.bootstrap_days
        assert cfg2.recheck_days == cfg.recheck_days
        assert cfg2.allowed_currencies == cfg.allowed_currencies
        assert cfg2.stale_days_limit == cfg.stale_days_limit

    def test_config_bootstrap_days_min_260_and_defaults(self):
        with pytest.raises(ConfigError):
            PriceCollectionConfig(bootstrap_days=100)
        cfg = PriceCollectionConfig()
        assert cfg.bootstrap_days == 260
        assert cfg.recheck_days == 10
        assert cfg.allowed_currencies == {"TRY"}
