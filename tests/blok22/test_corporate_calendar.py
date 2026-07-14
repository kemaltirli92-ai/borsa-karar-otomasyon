"""BLOK 22 - test_corporate_calendar: kurumsal islem + takvim kabul testleri (9 test).

Kapsam: kurumsal islem: bolunme duzeltmesi fiyat serisine uygulanir +
versiyon zinciri (3); yeni halka arz: IPO gunu eklenir, oncesi None
(URETILMEZ) (2); tatil gunu: islem gunu degil -> bar uretilmez/tarama
atlanir (2); islem durdurma: TRADING_HALT taramada kalir +
scoring_ready=false (2). GERCEK BLOK 9/13 modulleri kullanilir.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.acceptance.universe import UniverseBook
from app.services.stock_scanning.corporate_actions.models import (
    RestrictionType,
    TradingRestriction,
)
from app.services.stock_scanning.corporate_actions.restrictions import (
    RestrictionRegistry,
)
from app.services.stock_scanning.corporate_actions.suspension import (
    SuspensionPolicy,
)
from app.services.stock_scanning.validation import (
    HOLIDAY,
    NEW_LISTING,
    WEEKEND,
    CorporateAction,
    CorporateActionAdjuster,
    TradingCalendar,
)
from app.services.stock_scanning.validation.sufficiency import classify_sufficiency
from tests.blok22.conftest import FIXED_NOW, make_universe, universe_symbols

STOCK = "X001"
DAY = date(2025, 6, 3)


def _bar(day, close):
    return SimpleNamespace(
        stock_id=STOCK, trade_date=str(day), open=close, high=close + 1.0,
        low=close - 1.0, close=float(close), volume=1000, currency="TRY",
    )


def _adjuster():
    return CorporateActionAdjuster(clock=lambda: "2025-06-03T08:00:00Z")


def _split_action(effective="2025-06-03", notice="KAP-2025-001"):
    return CorporateAction(
        stock_id=STOCK,
        action_type="split",
        announcement_date="2025-05-20",
        effective_date=effective,
        ratio="2:1",
        kap_notice_no=notice,
        source="KAP",
    )


# 1) kurumsal islem: bolunme duzeltmesi + versiyon zinciri ----------------------
def test_split_adjustment_applied_to_price_series():
    bars = [_bar("2025-06-02", 200.0), _bar("2025-06-03", 100.0)]
    series = _adjuster().adjust_series(STOCK, bars, [_split_action()])
    by_date = {b.trade_date: b for b in series.bars}
    # effective_date ONCESI bar duzeltilir (2:1 -> faktor 0.5)
    assert by_date["2025-06-02"].adj_close == 100.0
    assert by_date["2025-06-02"].raw_close == 200.0
    # effective_date ve sonrasi etkilenmez
    assert by_date["2025-06-03"].adj_close == 100.0
    assert by_date["2025-06-03"].adj_factor == 1.0


def test_adjustment_raw_bars_preserved():
    bars = [_bar("2025-06-02", 200.0)]
    _adjuster().adjust_series(STOCK, bars, [_split_action()])
    assert bars[0].close == 200.0  # ham seri HICBIR ZAMAN degismez


def test_adjustment_version_chain_old_version_kept():
    adj = _adjuster()
    bars = [_bar("2025-06-02", 200.0)]
    s1 = adj.adjust_series(STOCK, bars, [_split_action()])
    s2 = adj.adjust_series(STOCK, bars, [_split_action(notice="KAP-2025-002")])
    assert s1.data_version == "adj-v1"
    assert s2.data_version == "adj-v2"
    assert adj.list_versions(STOCK) == ["adj-v1", "adj-v2"]
    # eski surum SILINMEZ, okunabilir
    assert adj.get_series(STOCK, "adj-v1").data_version == "adj-v1"


# 2) yeni halka arz --------------------------------------------------------------
def test_ipo_day_added_to_universe(identity):
    book = make_universe(identity, universe_symbols(100))
    book.enter("IPOX", "Halka Arz Sirketi", "2025-06-03")
    assert book.is_member("IPOX", "2025-06-03") is True
    assert book.active_count("2025-06-03") == 101


def test_ipo_before_listing_none_not_generated(identity):
    book = make_universe(identity, universe_symbols(100))
    book.enter("IPOX", "Halka Arz Sirketi", "2025-06-03")
    # IPO oncesi gun: uye DEGIL ve gecmis URETILMEZ
    assert book.is_member("IPOX", "2025-06-02") is False
    assert book.history("IPOX")[0].entered == "2025-06-03"
    # gercek yeterlilik siniflandirici: yakin listing -> NEW_LISTING
    verdict = classify_sufficiency(
        "IPOX",
        [SimpleNamespace(status="VALIDATED", trade_date="2025-06-03")],
        listing_date="2025-06-03",
        clock=lambda: DAY,
    )
    assert verdict.status == NEW_LISTING


# 3) tatil gunu ------------------------------------------------------------------
def test_holiday_is_not_trading_day():
    cal = TradingCalendar(holidays={"2025-06-03"}, clock=lambda: DAY)
    assert cal.is_trading_day("2025-06-03") is False
    assert cal.non_trading_reason("2025-06-03") == HOLIDAY


def test_non_trading_day_scan_skipped_no_bar():
    # Hafta sonu + tatil: islem gunu degil -> bar URETILMEZ, tarama atlanir.
    # Takvim saati sorgulanan gunden (2025-06-07) SONRA kurulur; aksi
    # halde gun "gelecek" (FUTURE_DATE) sayilir (blok9 takvim kalibi).
    cal = TradingCalendar(
        holidays={"2025-06-03"}, clock=lambda: date(2025, 6, 9)
    )
    assert cal.is_trading_day("2025-06-07") is False  # Cumartesi
    assert cal.non_trading_reason("2025-06-07") == WEEKEND
    # staging karar noktasi: islem gunu degilse fetch cagrilmaz (bar yok)
    trading_days = [
        d for d in ("2025-06-02", "2025-06-03", "2025-06-07")
        if cal.is_trading_day(d)
    ]
    assert trading_days == ["2025-06-02"]


# 4) islem durdurma (TRADING_HALT) -----------------------------------------------
def _halt_registry(halt=True):
    registry = RestrictionRegistry(clock=lambda: DAY)
    if halt:
        registry.register(
            STOCK,
            TradingRestriction(
                restriction_type=RestrictionType.TRADING_HALT,
                start_date="2025-06-03",
                end_date=None,
                is_active=True,
                source="VBTS",
                official_url="https://borsa.example.tr/vbts",
                collected_at="2025-06-03T08:00:00",
            ),
        )
    return registry


def test_trading_halt_keeps_stock_in_scan():
    status = SuspensionPolicy(_halt_registry()).scan_status(STOCK)
    assert status.keep_in_scan is True        # taramadan SILINMEZ
    assert status.history_protected is True   # gecmis grafik korunur
    assert status.show_as_normal is False     # normal gosterilmez


def test_trading_halt_scoring_ready_false():
    status = SuspensionPolicy(_halt_registry()).scan_status(STOCK)
    assert status.scoring_ready is False
    # tedbir yoksa scoring_ready True (karsit kanit)
    normal = SuspensionPolicy(_halt_registry(halt=False)).scan_status(STOCK)
    assert normal.scoring_ready is True
