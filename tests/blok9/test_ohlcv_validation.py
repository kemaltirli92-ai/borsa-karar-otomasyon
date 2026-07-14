"""BLOK 9 - OHLCV Dogrulama ve Kurumsal Islem Duzeltmesi: TAM 100 pytest testi.

Kategoriler (toplam = 100, SPEC BLOK 9 bolum 10):
1. OHLC mantigi (kural 1-7): pozitiflik, high/low kapsama, hacim (18)
2. Tarih/tatil/tekrar (kural 8-9): hafta sonu, tatil enjeksiyonu, gelecek
   tarih, cift tarih (14)
3. Para birimi + sembol-sirket (kural 10-11): yanlis para birimi, yanlis
   sirket, BLOK 6 entegrasyonu mock (10)
4. Outlier + kurumsal aciklama + kaynak karsilastirma (kural 12-13 +
   cross-check + promote) (16)
5. Kurumsal islem duzeltmesi: bedelsiz/bedelli/temettu/bolunme/birlesme
   faktorleri, ham korunur, duzeltilmis ayri, kumulatif (16)
6. data_version + eski rapor korumasi: yeni surum, eski surum okunur,
   sessiz degisiklik yok (10)
7. Yeni halka arz + yeterlilik: sentetik gecmis uretilmez, 6 durum (10)
8. Gecit: VALIDATED gecer, REJECTED/REVIEW_REQUIRED gecmez, GATE_BLOCKED (6)

Hicbir test ag erisimi yapmaz: tum servisler mock/enjekte, saat enjekte
(sabit 2024-06-28 Cuma). BLOK 6/7/8'e dokunulmaz; entegrasyon enjeksiyonla.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.services.stock_scanning.validation import (
    ALL_RULE_CODES,
    BAR_NOT_FOUND,
    CLOSE_NOT_POSITIVE,
    CORPORATE_CHECK_MISSING,
    CORPORATE_NOT_CHECKED,
    CURRENCY_MISMATCH,
    DUPLICATE_DATE,
    DUPLICATE_KAP_NOTICE,
    FATAL,
    FUTURE_DATE,
    GATE_BLOCKED,
    GATE_RELEASED,
    HIGH_LT_PRICE,
    HIGH_NOT_POSITIVE,
    INFO,
    INSUFFICIENT_FOR_TECHNICAL,
    LIMITED_DATA,
    LOW_GT_PRICE,
    LOW_NOT_POSITIVE,
    NEGATIVE_VOLUME,
    NEW_LISTING,
    NON_TRADING_DAY,
    NO_RELEASABLE_BARS,
    NO_SYNTHETIC_HISTORY,
    OPEN_NOT_POSITIVE,
    PRICE_DATA_MISSING,
    PROMOTED_TO_VALIDATED,
    REVIEW_REQUIRED,
    SOURCE_CHECK_MISSING,
    SOURCE_DIVERGENCE_REVIEW,
    STATUS_NOT_CLEAN,
    SUFFICIENT_DATA,
    SYMBOL_OWNER_MISMATCH,
    UNEXPLAINED_OUTLIER,
    WARN,
    AdjustedSeries,
    BarContext,
    CorporateAction,
    CorporateActionAdjuster,
    DuplicateKapNoticeError,
    FrozenSnapshotStore,
    LayerStatus,
    NoSyntheticHistoryError,
    OhlcvValidator,
    ReleaseGate,
    SeriesVerdict,
    SnapshotFrozenError,
    SufficiencyVerdict,
    TradingCalendar,
    ValidationConfig,
    classify_sufficiency,
    close_positive,
    corporate_checked,
    currency_ok,
    evaluate_bar,
    high_covers_all,
    high_positive,
    low_below_all,
    low_positive,
    no_duplicate_date,
    open_positive,
    outlier_explained,
    source_cross_check,
    symbol_owner_ok,
    valid_trading_day,
    volume_non_negative,
)

# ---------------------------------------------------------------------- #
# Sabitler + yardimcilar
# ---------------------------------------------------------------------- #
STOCK = "THYAO"
FIXED_TODAY = date(2024, 6, 28)  # Cuma (enjekte saat)
DAY = timedelta(days=1)


def fixed_clock():
    """Deterministik 'bugun' (takvim/yeterlilik icin)."""
    return FIXED_TODAY


def iso(d: date) -> str:
    return d.isoformat()


def make_bar(
    trade_date="2024-06-27",
    close=100.0,
    *,
    open_=None,
    high=None,
    low=None,
    volume=1000,
    currency="TRY",
    stock_id=STOCK,
    source="licensed",
    symbol=None,
    outlier_explanation=None,
    bar_id=None,
):
    """Duck-typed bar (BLOK 8 PriceBar ile ayni nitelik adlari)."""
    if isinstance(trade_date, date):
        trade_date = trade_date.isoformat()
    o = open_ if open_ is not None else close
    h = high if high is not None else close + 1.0
    l = low if low is not None else close - 1.0
    bar = SimpleNamespace(
        stock_id=stock_id,
        trade_date=trade_date,
        open=float(o),
        high=float(h),
        low=float(l),
        close=float(close),
        volume=volume,
        currency=currency,
        source=source,
    )
    if symbol is not None:
        bar.symbol = symbol
    if outlier_explanation is not None:
        bar.outlier_explanation = outlier_explanation
    if bar_id is not None:
        bar.bar_id = bar_id
    return bar


def make_bars(n, start=date(2024, 1, 2), close=100.0):
    """n adet gecerli ham bar (art arda gunler)."""
    return [make_bar(iso(start + i * DAY), close) for i in range(n)]


def make_calendar(holidays=None):
    return TradingCalendar(holidays=holidays, clock=fixed_clock)


def make_validator(**kwargs):
    kwargs.setdefault("calendar", make_calendar())
    return OhlcvValidator(**kwargs)


class MockIdentityService:
    """BLOK 6 SymbolIdentityService mock'u (symbol_belongs_to protokolu)."""

    def __init__(self, allowed=True):
        self.allowed = allowed
        self.calls = []

    def symbol_belongs_to(self, stock_id, symbol):
        self.calls.append((stock_id, symbol))
        return self.allowed


class Blok6ResolveService:
    """BLOK 6 SymbolIdentityService mock'u (resolve protokolu)."""

    def __init__(self, resolved_stock_id):
        self._resolved = resolved_stock_id

    def resolve(self, symbol):
        return SimpleNamespace(stock_id=self._resolved, matched_by="symbol")


def corporate_action(
    stock_id=STOCK,
    action_type="split",
    effective_date="2024-06-28",
    ratio="2:1",
    kap_notice_no="KAP-2024-001",
    announcement_date="2024-06-20",
):
    return CorporateAction(
        stock_id=stock_id,
        action_type=action_type,
        announcement_date=announcement_date,
        effective_date=effective_date,
        ratio=ratio,
        kap_notice_no=kap_notice_no,
        source="KAP",
    )


# ====================================================================== #
# KATEGORI 1 - OHLC mantigi (kurallar 1-7) — 18 test
# ====================================================================== #
def test_open_positive_ok():
    bar = make_bar(open_=100.0)
    res = open_positive(bar)
    assert res.code == OPEN_NOT_POSITIVE
    assert res.ok is True


def test_open_zero_fails_open_not_positive():
    res = open_positive(make_bar(open_=0.0))
    assert res.ok is False
    assert res.code == OPEN_NOT_POSITIVE
    assert res.severity == FATAL


def test_open_negative_fails_open_not_positive():
    res = open_positive(make_bar(open_=-5.0))
    assert res.ok is False
    assert res.code == OPEN_NOT_POSITIVE
    assert res.severity == FATAL


def test_high_positive_ok():
    res = high_positive(make_bar(high=101.0))
    assert res.ok is True
    assert res.code == HIGH_NOT_POSITIVE


def test_high_zero_fails_high_not_positive():
    res = high_positive(make_bar(high=0.0))
    assert res.ok is False
    assert res.code == HIGH_NOT_POSITIVE
    assert res.severity == FATAL


def test_low_positive_ok():
    res = low_positive(make_bar(low=99.0))
    assert res.ok is True
    assert res.code == LOW_NOT_POSITIVE


def test_low_negative_fails_low_not_positive():
    res = low_positive(make_bar(low=-1.0))
    assert res.ok is False
    assert res.code == LOW_NOT_POSITIVE
    assert res.severity == FATAL


def test_close_positive_ok():
    res = close_positive(make_bar(close=100.0))
    assert res.ok is True
    assert res.code == CLOSE_NOT_POSITIVE


def test_close_zero_fails_close_not_positive():
    res = close_positive(make_bar(close=0.0))
    assert res.ok is False
    assert res.code == CLOSE_NOT_POSITIVE
    assert res.severity == FATAL


def test_volume_zero_ok():
    res = volume_non_negative(make_bar(volume=0))
    assert res.ok is True
    assert res.code == NEGATIVE_VOLUME


def test_negative_volume_fails():
    res = volume_non_negative(make_bar(volume=-100))
    assert res.ok is False
    assert res.code == NEGATIVE_VOLUME
    assert res.severity == FATAL


def test_high_covers_all_ok():
    bar = make_bar(close=100.0, open_=99.0, high=101.0, low=98.0)
    res = high_covers_all(bar)
    assert res.ok is True
    assert res.code == HIGH_LT_PRICE


def test_high_below_open_fails_high_lt_price():
    bar = make_bar(close=100.0, open_=105.0, high=103.0, low=98.0)
    res = high_covers_all(bar)
    assert res.ok is False
    assert res.code == HIGH_LT_PRICE
    assert res.severity == FATAL


def test_high_below_close_fails_high_lt_price():
    bar = make_bar(close=110.0, open_=100.0, high=105.0, low=98.0)
    res = high_covers_all(bar)
    assert res.ok is False
    assert res.code == HIGH_LT_PRICE


def test_high_below_low_fails_high_lt_price():
    bar = make_bar(close=100.0, open_=100.0, high=99.0, low=101.0)
    res = high_covers_all(bar)
    assert res.ok is False
    assert res.code == HIGH_LT_PRICE


def test_low_below_all_ok():
    bar = make_bar(close=100.0, open_=99.0, high=101.0, low=98.0)
    res = low_below_all(bar)
    assert res.ok is True
    assert res.code == LOW_GT_PRICE


def test_low_above_close_fails_low_gt_price():
    bar = make_bar(close=90.0, open_=100.0, high=101.0, low=95.0)
    res = low_below_all(bar)
    assert res.ok is False
    assert res.code == LOW_GT_PRICE
    assert res.severity == FATAL


def test_price_violation_is_fatal_rejected():
    """FATAL kural ihlali evaluate_bar'da REJECTED uretir; 13 kural calisir."""
    bar = make_bar(close=100.0, open_=0.0, high=101.0, low=99.0)
    status, results = evaluate_bar(bar, BarContext(calendar=make_calendar()))
    assert status == LayerStatus.REJECTED
    assert len(results) == len(ALL_RULE_CODES) == 13
    open_res = next(r for r in results if r.code == OPEN_NOT_POSITIVE)
    assert open_res.ok is False
    assert open_res.severity == FATAL


# ====================================================================== #
# KATEGORI 2 - Tarih/tatil/tekrar (kurallar 8-9) — 14 test
# ====================================================================== #
def test_weekday_is_trading_day():
    cal = make_calendar()
    assert cal.is_trading_day("2024-06-27") is True  # Persembe
    assert cal.non_trading_reason("2024-06-27") is None


def test_saturday_not_trading_day():
    cal = make_calendar()
    assert cal.is_trading_day("2024-06-22") is False  # Cumartesi (gecmis)
    assert cal.non_trading_reason("2024-06-22") == "WEEKEND"


def test_sunday_not_trading_day():
    cal = make_calendar()
    assert cal.is_trading_day("2024-06-23") is False  # Pazar (gecmis)


def test_weekend_bar_rejected_non_trading_day():
    v = make_validator()
    verdict = v.validate_bar(make_bar("2024-06-22", 100.0))  # Cumartesi
    assert verdict.status == LayerStatus.REJECTED
    assert NON_TRADING_DAY in verdict.failed_codes()


def test_holiday_set_injection_blocks_trading():
    cal = make_calendar(holidays={"2024-06-27"})
    assert cal.is_trading_day("2024-06-27") is False
    assert cal.non_trading_reason("2024-06-27") == "HOLIDAY"


def test_holiday_callable_injection_blocks_trading():
    cal = make_calendar(holidays=lambda d: d == "2024-06-26")
    assert cal.is_trading_day("2024-06-26") is False
    assert cal.is_trading_day("2024-06-27") is True


def test_holiday_bar_rejected():
    v = make_validator()
    v.calendar = make_calendar(holidays={"2024-06-27"})
    verdict = v.validate_bar(make_bar("2024-06-27", 100.0))
    assert verdict.status == LayerStatus.REJECTED
    assert NON_TRADING_DAY in verdict.failed_codes()


def test_future_date_not_trading_day():
    cal = make_calendar()
    future = iso(FIXED_TODAY + 30 * DAY)
    assert cal.is_trading_day(future) is False
    assert cal.non_trading_reason(future) == FUTURE_DATE


def test_future_date_bar_rejected_future_date():
    v = make_validator()
    future = iso(FIXED_TODAY + 7 * DAY)
    verdict = v.validate_bar(make_bar(future, 100.0))
    assert verdict.status == LayerStatus.REJECTED
    assert FUTURE_DATE in verdict.failed_codes()


def test_today_weekday_is_trading_day():
    """Enjekte saatin 'bugun'u hafta ici ise islem gunudur."""
    cal = make_calendar()
    assert cal.is_trading_day(iso(FIXED_TODAY)) is True


def test_invalid_date_string_not_trading():
    cal = make_calendar()
    assert cal.is_trading_day("2024-13-99") is False
    assert cal.non_trading_reason("bir-tarih-degil") == "INVALID_DATE"


def test_custom_weekend_override():
    """weekend=(4,5): Cuma+Cumartesi tatil; Pazar islem gunu."""
    cal = TradingCalendar(weekend=(4, 5), clock=lambda: date(2024, 7, 1))
    assert cal.is_trading_day("2024-06-28") is False  # Cuma
    assert cal.is_trading_day("2024-06-30") is True   # Pazar


def test_duplicate_date_in_series_rejected():
    v = make_validator()
    bars = [make_bar("2024-06-26", 100.0), make_bar("2024-06-26", 101.0)]
    series = v.validate_series(STOCK, bars)
    assert series.bar_verdicts[0].status == LayerStatus.CLEAN
    dup = series.bar_verdicts[1]
    assert dup.status == LayerStatus.REJECTED
    assert DUPLICATE_DATE in dup.failed_codes()


def test_same_date_different_source_not_duplicate():
    v = make_validator()
    bars = [
        make_bar("2024-06-26", 100.0, source="licensed"),
        make_bar("2024-06-26", 100.5, source="yfinance"),
    ]
    series = v.validate_series(STOCK, bars)
    assert all(bv.status == LayerStatus.CLEAN for bv in series.bar_verdicts)
    assert series.count(LayerStatus.CLEAN) == 2


# ====================================================================== #
# KATEGORI 3 - Para birimi + sembol-sirket (kurallar 10-11) — 10 test
# ====================================================================== #
def test_try_currency_ok():
    res = currency_ok(make_bar(currency="TRY"), {"TRY"})
    assert res.ok is True
    assert res.code == CURRENCY_MISMATCH


def test_usd_currency_rejected():
    res = currency_ok(make_bar(currency="USD"), {"TRY"})
    assert res.ok is False
    assert res.code == CURRENCY_MISMATCH


def test_currency_mismatch_is_fatal_rejected():
    v = make_validator()
    verdict = v.validate_bar(make_bar("2024-06-27", 100.0, currency="USD"))
    assert verdict.status == LayerStatus.REJECTED
    assert CURRENCY_MISMATCH in verdict.failed_codes()
    res = next(r for r in verdict.rule_results if r.code == CURRENCY_MISMATCH)
    assert res.severity == FATAL


def test_custom_allowed_currencies():
    """Izinli sete eklenen para birimi gecer."""
    v = make_validator(config=ValidationConfig(allowed_currencies={"TRY", "USD"}))
    verdict = v.validate_bar(make_bar("2024-06-27", 100.0, currency="USD"))
    assert CURRENCY_MISMATCH not in verdict.failed_codes()
    assert verdict.status == LayerStatus.CLEAN


def test_symbol_owner_match_ok():
    """BLOK 6 resolve protokolu: sembol dogru sirkete ait."""
    service = Blok6ResolveService(resolved_stock_id=STOCK)
    bar = make_bar(symbol="THYAO")
    res = symbol_owner_ok(bar, service)
    assert res.ok is True
    assert res.code == SYMBOL_OWNER_MISMATCH


def test_symbol_owner_mismatch_fails():
    service = MockIdentityService(allowed=False)
    bar = make_bar(symbol="THYAO")
    res = symbol_owner_ok(bar, service)
    assert res.ok is False
    assert res.code == SYMBOL_OWNER_MISMATCH
    assert res.severity == FATAL
    assert service.calls == [(STOCK, "THYAO")]


def test_symbol_owner_mismatch_rejected():
    v = make_validator(identity_service=MockIdentityService(allowed=False))
    verdict = v.validate_bar(make_bar("2024-06-27", 100.0, symbol="THYAO"))
    assert verdict.status == LayerStatus.REJECTED
    assert SYMBOL_OWNER_MISMATCH in verdict.failed_codes()


def test_identity_service_none_skips():
    """Kimlik servisi enjekte edilmediyse kontrol atlanir (INFO ok)."""
    res = symbol_owner_ok(make_bar(symbol="THYAO"), None)
    assert res.ok is True
    assert res.severity == INFO


def test_bar_without_symbol_skips():
    """Bar'da symbol niteligi yoksa kontrol atlanir (INFO ok)."""
    res = symbol_owner_ok(make_bar(), MockIdentityService(allowed=False))
    assert res.ok is True
    assert res.severity == INFO


def test_callable_identity_service_supported():
    """Duck typing: duz callable (stock_id, symbol) -> bool desteklenir."""
    service = lambda stock_id, symbol: symbol == "THYAO"  # noqa: E731
    assert symbol_owner_ok(make_bar(symbol="THYAO"), service).ok is True
    res = symbol_owner_ok(make_bar(symbol="GARAN"), service)
    assert res.ok is False
    assert res.code == SYMBOL_OWNER_MISMATCH


# ====================================================================== #
# KATEGORI 4 - Outlier + kurumsal aciklama + kaynak karsilastirma — 16 test
# ====================================================================== #
def test_small_change_no_outlier():
    bar = make_bar(close=105.0)
    res = outlier_explained(bar, prev_close=100.0, threshold_pct=20.0)
    assert res.ok is True
    assert res.code == UNEXPLAINED_OUTLIER


def test_outlier_without_explanation_warns():
    bar = make_bar(close=130.0)  # %30 > %20
    res = outlier_explained(bar, prev_close=100.0, threshold_pct=20.0)
    assert res.ok is False
    assert res.code == UNEXPLAINED_OUTLIER
    assert res.severity == WARN


def test_unexplained_outlier_review_required():
    v = make_validator()
    verdict = v.validate_bar(make_bar("2024-06-27", 130.0), prev_close=100.0)
    assert verdict.status == LayerStatus.REVIEW_REQUIRED
    assert UNEXPLAINED_OUTLIER in verdict.failed_codes()


def test_outlier_with_bar_explanation_ok():
    """Bar uzerinde aciklama niteligi varsa outlier aciklanmis sayilir."""
    bar = make_bar("2024-06-27", 130.0, outlier_explanation="TRADING_HALT_RESUME")
    v = make_validator()
    verdict = v.validate_bar(bar, prev_close=100.0)
    assert UNEXPLAINED_OUTLIER not in verdict.failed_codes()
    assert verdict.status == LayerStatus.CLEAN


def test_outlier_with_registered_explanation_ok():
    """Validator'a elle kaydedilen aciklama (or. kaynak duzeltmesi)."""
    v = make_validator()
    v.add_outlier_explanation(STOCK, "2024-06-27", "SOURCE_CORRECTION")
    verdict = v.validate_bar(make_bar("2024-06-27", 130.0), prev_close=100.0)
    assert verdict.status == LayerStatus.CLEAN
    assert UNEXPLAINED_OUTLIER not in verdict.failed_codes()


def test_outlier_with_corporate_action_ok():
    """O gun effective_date'li kurumsal islem varsa outlier aciklanir."""
    action = corporate_action(effective_date="2024-06-27", ratio="2:1")
    lookup = lambda stock_id, trade_date: [action] if trade_date == "2024-06-27" else []  # noqa: E731
    v = make_validator(corporate_lookup=lookup)
    verdict = v.validate_bar(make_bar("2024-06-27", 50.0), prev_close=100.0)
    assert verdict.status == LayerStatus.CLEAN
    assert UNEXPLAINED_OUTLIER not in verdict.failed_codes()


def test_threshold_boundary_not_outlier():
    """Tam esik (%20) outlier DEGILDIR (kural: fark > esik)."""
    bar = make_bar(close=120.0)
    res = outlier_explained(bar, prev_close=100.0, threshold_pct=20.0)
    assert res.ok is True


def test_custom_threshold():
    """Esik config ile degistirilebilir (%10 -> %15 fark outlier)."""
    v = make_validator(config=ValidationConfig(outlier_threshold_pct=10.0))
    verdict = v.validate_bar(make_bar("2024-06-27", 115.0), prev_close=100.0)
    assert verdict.status == LayerStatus.REVIEW_REQUIRED
    assert UNEXPLAINED_OUTLIER in verdict.failed_codes()


def test_first_bar_no_prev_close_ok():
    """Serinin ilk barinda referans yok; outlier kontrolu atlanir."""
    v = make_validator()
    verdict = v.validate_bar(make_bar("2024-06-27", 100.0), prev_close=None)
    res = next(r for r in verdict.rule_results if r.code == UNEXPLAINED_OUTLIER)
    assert res.ok is True
    assert verdict.status == LayerStatus.CLEAN


def test_rejected_bar_not_used_as_reference():
    """REJECTED bar sonrasi outlier referansi guncellenmez.

    Seri: 100 (CLEAN) -> bozuk bar close=110 (REJECTED) -> 130.
    Referans 110 olsaydi %18.2 (outlier yok); 100 kaldigi icin %30 outlier.
    """
    v = make_validator()
    bars = [
        make_bar("2024-06-25", 100.0),
        make_bar("2024-06-26", 110.0, open_=0.0),  # REJECTED (open<=0)
        make_bar("2024-06-27", 130.0),
    ]
    series = v.validate_series(STOCK, bars)
    assert series.bar_verdicts[1].status == LayerStatus.REJECTED
    third = series.bar_verdicts[2]
    assert third.status == LayerStatus.REVIEW_REQUIRED
    assert UNEXPLAINED_OUTLIER in third.failed_codes()


def test_corporate_checked_ok_when_lookup_returns_list():
    """Lookup liste donerse (bos bile olsa) kontrol yapilmis sayilir."""
    v = make_validator(corporate_lookup=lambda s, d: [])
    verdict = v.validate_bar(make_bar("2024-06-27", 100.0))
    res = next(r for r in verdict.rule_results if r.code == CORPORATE_NOT_CHECKED)
    assert res.ok is True
    # None donen lookup: kontrol yapilmadi (INFO, katmani etkilemez)
    v2 = make_validator(corporate_lookup=lambda s, d: None)
    verdict2 = v2.validate_bar(make_bar("2024-06-27", 100.0))
    res2 = next(r for r in verdict2.rule_results if r.code == CORPORATE_NOT_CHECKED)
    assert res2.ok is False
    assert res2.severity == INFO
    assert verdict2.status == LayerStatus.CLEAN


def test_corporate_not_checked_info_when_no_lookup():
    """Kurumsal lookup yok: INFO (CLEAN engellenmez) ama VALIDATED olamaz."""
    # source_compare OK ama corporate_lookup=None -> kurumsal adim duser.
    v = make_validator(source_compare=lambda b: True)  # corporate_lookup=None
    verdict = v.validate_bar(make_bar("2024-06-27", 100.0))
    res = next(r for r in verdict.rule_results if r.code == CORPORATE_NOT_CHECKED)
    assert res.ok is False
    assert res.severity == INFO
    assert verdict.status == LayerStatus.CLEAN
    report = v.promote_validated([verdict.bar_id])
    assert report.promoted == []
    assert report.failed[verdict.bar_id] == CORPORATE_CHECK_MISSING


def test_source_cross_check_within_tolerance_ok():
    """Kaynak kapanislari tolerans icinde (fark 0.2% <= 0.5%)."""
    bar = make_bar(close=100.0)
    res = source_cross_check(bar, reference_close=100.2, tolerance_pct=0.5)
    assert res.ok is True
    assert res.code == SOURCE_DIVERGENCE_REVIEW


def test_source_cross_check_divergence_warns():
    """Kaynak farki tolerans disinda -> WARN."""
    bar = make_bar(close=100.0)
    res = source_cross_check(bar, reference_close=103.0, tolerance_pct=0.5)
    assert res.ok is False
    assert res.code == SOURCE_DIVERGENCE_REVIEW
    assert res.severity == WARN


def test_source_divergence_bar_review_required():
    """Tolerans disi kaynak uyusmazligi REVIEW_REQUIRED; VALIDATED olamaz."""
    v = make_validator()
    verdict = v.validate_bar(
        make_bar("2024-06-27", 100.0), reference_close=103.0
    )
    assert verdict.status == LayerStatus.REVIEW_REQUIRED
    assert SOURCE_DIVERGENCE_REVIEW in verdict.failed_codes()
    report = v.promote_validated([verdict.bar_id])
    assert report.failed[verdict.bar_id] == STATUS_NOT_CLEAN


def test_clean_bar_all_checks_pass_and_promote():
    """Tam entegrasyon: gecerli bar CLEAN -> promote kosullari -> VALIDATED.

    Ayrica SOURCE_CHECK_MISSING dali: kaynak karsilastirma yapilmadan
    yukseltme reddedilir.
    """
    promoted_ids = []

    def promoter(ids):
        promoted_ids.extend(ids)

    bar = make_bar("2024-06-27", 100.0, symbol="THYAO")
    # 1) Kaynak karsilastirma enjekte edilmezse VALIDATED olamaz.
    v_no_source = make_validator(corporate_lookup=lambda s, d: [])
    v1 = v_no_source.validate_bar(bar)
    assert v1.status == LayerStatus.CLEAN
    rep1 = v_no_source.promote_validated([v1.bar_id])
    assert rep1.failed[v1.bar_id] == SOURCE_CHECK_MISSING

    # 2) Tum kosullar OK: CLEAN + kaynak OK + kurumsal OK -> VALIDATED.
    v = make_validator(
        identity_service=MockIdentityService(allowed=True),
        corporate_lookup=lambda s, d: [],
        source_compare=lambda b: True,
        promoter=promoter,
    )
    verdict = v.validate_bar(bar)
    assert verdict.status == LayerStatus.CLEAN
    assert verdict.failed_codes() == []
    assert len(verdict.rule_results) == 13
    rep = v.promote_validated([verdict.bar_id])
    assert rep.promoted == [verdict.bar_id]
    assert verdict.status == LayerStatus.VALIDATED
    assert PROMOTED_TO_VALIDATED in verdict.notes
    assert promoted_ids == [verdict.bar_id]
    # Bilinmeyen bar id'si raporlanir.
    rep2 = v.promote_validated(["yok|boyle|bar"])
    assert rep2.failed["yok|boyle|bar"] == BAR_NOT_FOUND


# ====================================================================== #
# KATEGORI 5 - Kurumsal islem duzeltmesi — 16 test
# ====================================================================== #
def make_adjuster():
    return CorporateActionAdjuster(clock=lambda: "2024-06-30T08:00:00Z")


def test_register_returns_blok7_compatible_dict():
    adj = make_adjuster()
    row = adj.register(corporate_action())
    assert row["stock_id"] == STOCK
    assert row["action_type"] == "split"
    assert row["effective_date"] == "2024-06-28"
    assert row["ratio"] == "2:1"
    assert row["kap_notice_no"] == "KAP-2024-001"
    assert row["source"] == "KAP"
    assert row["registered_at"] == "2024-06-30T08:00:00Z"


def test_register_duplicate_kap_notice_rejected():
    adj = make_adjuster()
    adj.register(corporate_action())
    with pytest.raises(DuplicateKapNoticeError) as exc:
        adj.register(corporate_action())
    assert exc.value.code == DUPLICATE_KAP_NOTICE


def test_register_different_notices_ok():
    adj = make_adjuster()
    adj.register(corporate_action(kap_notice_no="KAP-1"))
    row = adj.register(
        corporate_action(action_type="dividend", ratio=2.0, kap_notice_no="KAP-2")
    )
    assert row["kap_notice_no"] == "KAP-2"
    assert len(adj.actions_for(STOCK)) == 2


def test_split_ratio_2_to_1_factor_half():
    """Bolunme 2:1 -> effective_date oncesi barlarin fiyat faktoru 0.5."""
    adj = make_adjuster()
    bars = make_bars(3, start=date(2024, 6, 25), close=100.0)
    series = adj.adjust_series(
        STOCK, bars, [corporate_action(effective_date="2024-06-28", ratio="2:1")]
    )
    assert all(ab.adj_factor == pytest.approx(0.5) for ab in series.bars)
    assert series.bars[0].adj_close == pytest.approx(50.0)


def test_split_float_ratio_direct_factor():
    """Sayisal ratio dogrudan faktor olarak uygulanir."""
    adj = make_adjuster()
    bars = make_bars(2, start=date(2024, 6, 25), close=100.0)
    series = adj.adjust_series(
        STOCK, bars, [corporate_action(effective_date="2024-06-28", ratio=0.25)]
    )
    assert series.bars[0].adj_factor == pytest.approx(0.25)
    assert series.bars[0].adj_close == pytest.approx(25.0)


def test_reverse_split_ratio_1_to_2_factor_two():
    """Birlesme 1:2 (2 eski -> 1 yeni) -> faktor 2.0."""
    adj = make_adjuster()
    bars = make_bars(2, start=date(2024, 6, 25), close=50.0)
    series = adj.adjust_series(
        STOCK,
        bars,
        [corporate_action(action_type="reverse_split", effective_date="2024-06-28", ratio="1:2")],
    )
    assert series.bars[0].adj_factor == pytest.approx(2.0)
    assert series.bars[0].adj_close == pytest.approx(100.0)


def test_bonus_ratio_1_to_1_factor_half():
    """Bedelsiz 1:1 (1 paya 1 bedelsiz) -> faktor 1/(1+1) = 0.5."""
    adj = make_adjuster()
    bars = make_bars(2, start=date(2024, 6, 25), close=100.0)
    series = adj.adjust_series(
        STOCK,
        bars,
        [corporate_action(action_type="bonus", effective_date="2024-06-28", ratio="1:1")],
    )
    assert series.bars[0].adj_factor == pytest.approx(0.5)
    assert series.bars[0].adj_close == pytest.approx(50.0)


def test_dividend_cash_factor():
    """Temettu: nakit dusum (ref_close - tutar) / ref_close.

    Barlar: 100, 101, 102 (06-25..27); effective 06-28; temettu 2.04.
    ref_close = 102 -> faktor = (102 - 2.04) / 102 = 0.98.
    """
    adj = make_adjuster()
    bars = [
        make_bar("2024-06-25", 100.0),
        make_bar("2024-06-26", 101.0),
        make_bar("2024-06-27", 102.0),
    ]
    series = adj.adjust_series(
        STOCK,
        bars,
        [corporate_action(action_type="dividend", effective_date="2024-06-28", ratio=2.04)],
    )
    assert series.bars[0].adj_factor == pytest.approx(0.98)
    assert series.bars[0].adj_close == pytest.approx(98.0)
    assert series.bars[2].adj_close == pytest.approx(99.96)


def test_adjustment_only_before_effective_date():
    """Duzeltme effective_date ONCESI barlara uygulanir; o gun ve sonrasi
    faktor 1.0 (duzeltme zaten fiyata yansimistir)."""
    adj = make_adjuster()
    bars = [
        make_bar("2024-06-26", 100.0),
        make_bar("2024-06-27", 100.0),
        make_bar("2024-06-28", 100.0),
    ]
    series = adj.adjust_series(
        STOCK, bars, [corporate_action(effective_date="2024-06-27", ratio="2:1")]
    )
    factors = [ab.adj_factor for ab in series.bars]
    assert factors[0] == pytest.approx(0.5)   # 06-26 < effective
    assert factors[1] == pytest.approx(1.0)   # 06-27 == effective
    assert factors[2] == pytest.approx(1.0)   # 06-28 > effective


def test_cumulative_multiple_actions():
    """Birden fazla islem effective_date oncesi barlara kumulatif (carpim)."""
    adj = make_adjuster()
    bars = [
        make_bar("2024-06-26", 100.0),
        make_bar("2024-06-27", 100.0),
        make_bar("2024-06-28", 100.0),
    ]
    actions = [
        corporate_action(effective_date="2024-06-27", ratio="2:1", kap_notice_no="KAP-A"),
        corporate_action(
            action_type="bonus", effective_date="2024-06-28", ratio="1:1", kap_notice_no="KAP-B"
        ),
    ]
    series = adj.adjust_series(STOCK, bars, actions)
    f = [ab.adj_factor for ab in series.bars]
    assert f[0] == pytest.approx(0.25)  # 0.5 * 0.5
    assert f[1] == pytest.approx(0.5)   # sadece bonus
    assert f[2] == pytest.approx(1.0)   # duzeltme yok
    assert series.bars[0].adj_close == pytest.approx(25.0)


def test_raw_bars_never_modified():
    """Ham barlar KORUNUR: adjust_series sonrasi ham nesneler degismez."""
    adj = make_adjuster()
    bar = make_bar("2024-06-25", 100.0)
    original_close = bar.close
    adj.adjust_series(
        STOCK, [bar], [corporate_action(effective_date="2024-06-28", ratio="2:1")]
    )
    assert bar.close == original_close == 100.0
    assert not hasattr(bar, "adj_close")


def test_adjusted_bar_fields():
    """AdjustedBar: trade_date, raw_close, adj_close, adj_factor, action_refs."""
    adj = make_adjuster()
    bars = [make_bar("2024-06-25", 100.0)]
    series = adj.adjust_series(
        STOCK, bars, [corporate_action(effective_date="2024-06-28", ratio="2:1")]
    )
    ab = series.bars[0]
    assert ab.trade_date == "2024-06-25"
    assert ab.raw_close == 100.0          # ham kapanis korunur
    assert ab.adj_close == pytest.approx(50.0)  # duzeltilmis ayri
    assert ab.adj_factor == pytest.approx(0.5)
    assert ab.action_refs == ["KAP-2024-001"]


def test_action_refs_recorded():
    """Uygulanan aksiyonlarin kap_notice_no'lari bar bazinda referanslanir."""
    adj = make_adjuster()
    bars = [make_bar("2024-06-25", 100.0)]
    actions = [
        corporate_action(effective_date="2024-06-27", ratio="2:1", kap_notice_no="KAP-A"),
        corporate_action(
            action_type="dividend", effective_date="2024-06-28", ratio=2.0, kap_notice_no="KAP-B"
        ),
    ]
    series = adj.adjust_series(STOCK, bars, actions)
    assert series.bars[0].action_refs == ["KAP-A", "KAP-B"]
    assert series.action_refs == ["KAP-A", "KAP-B"]


def test_no_actions_factor_one():
    """Aksiyon yoksa faktor 1.0 ve adj_close == raw_close."""
    adj = make_adjuster()
    bars = make_bars(3, start=date(2024, 6, 25), close=100.0)
    series = adj.adjust_series(STOCK, bars, [])
    for ab in series.bars:
        assert ab.adj_factor == 1.0
        assert ab.adj_close == ab.raw_close == 100.0
        assert ab.action_refs == []


def test_explain_outlier_explained_by_split():
    """2:1 bolunme gunu fiyat yarilanirsa outlier aciklanmis sayilir."""
    adj = make_adjuster()
    action = corporate_action(effective_date="2024-06-27", ratio="2:1")
    bar = make_bar("2024-06-27", 50.0)
    result = adj.explain_outlier(bar, prev_close=100.0, actions=[action])
    assert result.explained is True
    assert result.reason == "CORPORATE_ACTION"
    assert result.action_ref == "KAP-2024-001"
    assert result.expected_close == pytest.approx(50.0)
    assert result.diff_pct == pytest.approx(50.0)


def test_explain_outlier_unexplained():
    """Aksiyon yoksa (veya fiyat beklenenden uzaksa) aciklanamaz."""
    adj = make_adjuster()
    bar = make_bar("2024-06-27", 130.0)
    result = adj.explain_outlier(bar, prev_close=100.0, actions=[])
    assert result.explained is False
    assert result.reason == "UNEXPLAINED_OUTLIER"
    # Aksiyon var ama fiyat beklentiyle uyumsuz:
    action = corporate_action(effective_date="2024-06-27", ratio="2:1")
    mismatch = adj.explain_outlier(bar, prev_close=100.0, actions=[action])
    assert mismatch.explained is False
    assert mismatch.reason == "CORPORATE_ACTION_MISMATCH"


# ====================================================================== #
# KATEGORI 6 - data_version + eski rapor korumasi — 10 test
# ====================================================================== #
def test_first_adjustment_version_adj_v1():
    adj = make_adjuster()
    series = adj.adjust_series(STOCK, make_bars(2, start=date(2024, 6, 25)), [])
    assert series.data_version == "adj-v1"
    assert isinstance(series, AdjustedSeries)


def test_second_adjustment_version_adj_v2():
    adj = make_adjuster()
    bars = make_bars(2, start=date(2024, 6, 25))
    adj.adjust_series(STOCK, bars, [])
    series2 = adj.adjust_series(STOCK, bars, [])
    assert series2.data_version == "adj-v2"


def test_old_version_still_readable():
    """Eski data_version okunabilir ve ESKI degerleri dondurur."""
    adj = make_adjuster()
    bars = make_bars(2, start=date(2024, 6, 25), close=100.0)
    adj.adjust_series(STOCK, bars, [])
    adj.adjust_series(
        STOCK, bars, [corporate_action(effective_date="2024-06-28", ratio="2:1")]
    )
    old = adj.get_series(STOCK, "adj-v1")
    assert old.data_version == "adj-v1"
    assert old.bars[0].adj_close == 100.0  # eski surum: duzeltme yok
    assert old.bars[0].adj_factor == 1.0


def test_list_versions_grows():
    adj = make_adjuster()
    bars = make_bars(1, start=date(2024, 6, 25))
    assert adj.list_versions(STOCK) == []
    adj.adjust_series(STOCK, bars, [])
    adj.adjust_series(STOCK, bars, [])
    adj.adjust_series(STOCK, bars, [])
    assert adj.list_versions(STOCK) == ["adj-v1", "adj-v2", "adj-v3"]


def test_new_adjustment_keeps_old_values():
    """Yeni duzeltme calismasi eski surumu SESSIZCE DEGISTIRMEZ."""
    adj = make_adjuster()
    bars = make_bars(2, start=date(2024, 6, 25), close=100.0)
    adj.register(corporate_action(effective_date="2024-06-28", ratio="2:1"))
    adj.adjust_series(STOCK, bars)  # adj-v1 (kayitli aksiyonla)
    adj.register(
        corporate_action(
            action_type="bonus", effective_date="2024-06-28", ratio="1:1",
            kap_notice_no="KAP-EXTRA",
        )
    )
    adj.adjust_series(STOCK, bars)  # adj-v2 (iki aksiyonla)
    v1 = adj.get_series(STOCK, "adj-v1")
    v2 = adj.get_series(STOCK, "adj-v2")
    assert v1.bars[0].adj_factor == pytest.approx(0.5)
    assert v1.action_refs == ["KAP-2024-001"]
    assert v2.bars[0].adj_factor == pytest.approx(0.25)
    assert sorted(v2.action_refs) == ["KAP-2024-001", "KAP-EXTRA"]


def test_frozen_snapshot_freeze_and_get():
    store = FrozenSnapshotStore()
    report = {"stock_id": STOCK, "data_version": "adj-v1", "avg_close": 50.5}
    store.freeze("rapor-2024-06", report)
    assert store.get("rapor-2024-06") == report
    assert store.keys() == ["rapor-2024-06"]


def test_frozen_snapshot_overwrite_rejected():
    store = FrozenSnapshotStore()
    store.freeze("rapor-1", {"v": 1})
    with pytest.raises(SnapshotFrozenError):
        store.freeze("rapor-1", {"v": 2})
    assert store.get("rapor-1") == {"v": 1}


def test_snapshot_unchanged_after_new_adjustment():
    """Rapor snapshot'i dondurulduktan sonra yeni duzeltme onu degistirmez."""
    adj = make_adjuster()
    store = FrozenSnapshotStore()
    bars = make_bars(2, start=date(2024, 6, 25), close=100.0)
    s1 = adj.adjust_series(
        STOCK, bars, [corporate_action(effective_date="2024-06-28", ratio="2:1")]
    )
    store.freeze(
        "rapor-1",
        {"data_version": s1.data_version, "closes": [ab.adj_close for ab in s1.bars]},
    )
    # Yeni duzeltme calismasi (yeni data_version):
    adj.adjust_series(
        STOCK, bars, [corporate_action(effective_date="2024-06-28", ratio=0.1)]
    )
    snap = store.get("rapor-1")
    assert snap["data_version"] == "adj-v1"
    assert snap["closes"] == [50.0, 50.0]


def test_snapshot_get_returns_deep_copy():
    """get her zaman kopya dondurur: cagiranin degisikligi snapshot'i bozmaz."""
    store = FrozenSnapshotStore()
    store.freeze("rapor-1", {"closes": [50.0, 51.0]})
    snap = store.get("rapor-1")
    snap["closes"].append(999.0)
    snap["closes"][0] = -1.0
    assert store.get("rapor-1") == {"closes": [50.0, 51.0]}


def test_data_version_format_adj_vn():
    adj = make_adjuster()
    bars = make_bars(1, start=date(2024, 6, 25))
    for _ in range(3):
        series = adj.adjust_series(STOCK, bars, [])
        assert re.match(r"^adj-v\d+$", series.data_version)
    assert series.data_version == "adj-v3"


# ====================================================================== #
# KATEGORI 7 - Yeni halka arz + veri yeterlilik (6 durum) — 10 test
# ====================================================================== #
def test_backfill_raises_no_synthetic_history():
    """Yeni halka arz icin sentetik gecmis URETILMEZ: backfill hata verir."""
    adj = make_adjuster()
    with pytest.raises(NoSyntheticHistoryError):
        adj.backfill_history(STOCK, days=260)


def test_no_synthetic_history_error_code():
    adj = make_adjuster()
    with pytest.raises(NoSyntheticHistoryError) as exc:
        adj.backfill_history(STOCK, days=260, fill="zero")
    assert exc.value.code == NO_SYNTHETIC_HISTORY


def test_sufficient_data_260_bars():
    verdict = classify_sufficiency(STOCK, make_bars(260), clock=fixed_clock)
    assert verdict.status == SUFFICIENT_DATA
    assert verdict.valid_bars == 260
    assert verdict.total_bars == 260


def test_limited_data_100_bars():
    verdict = classify_sufficiency(STOCK, make_bars(100), clock=fixed_clock)
    assert verdict.status == LIMITED_DATA
    assert verdict.valid_bars == 100


def test_new_listing_recent_few_bars():
    """Halka arzi 30 gun once + 40 bar -> NEW_LISTING (gecmis uretilmez)."""
    listing = iso(FIXED_TODAY - 30 * DAY)
    verdict = classify_sufficiency(
        STOCK, make_bars(40), listing_date=listing, clock=fixed_clock
    )
    assert verdict.status == NEW_LISTING
    assert verdict.valid_bars == 40


def test_insufficient_for_technical_30_bars():
    verdict = classify_sufficiency(STOCK, make_bars(30), clock=fixed_clock)
    assert verdict.status == INSUFFICIENT_FOR_TECHNICAL
    assert 0 < verdict.valid_bars < 60


def test_price_data_missing_zero_bars():
    verdict = classify_sufficiency(STOCK, [], clock=fixed_clock)
    assert verdict.status == PRICE_DATA_MISSING
    assert verdict.valid_bars == 0
    assert verdict.total_bars == 0


def test_review_required_when_unresolved():
    """Seride cozulmemis REVIEW_REQUIRED bar varsa durum REVIEW_REQUIRED."""
    v = make_validator()
    bars = make_bars(99, start=date(2024, 1, 2), close=100.0)
    bars.append(make_bar(iso(date(2024, 1, 2) + 99 * DAY), 150.0))  # %50 outlier
    series = v.validate_series(STOCK, bars)
    assert series.count(LayerStatus.REVIEW_REQUIRED) == 1
    verdict = classify_sufficiency(
        STOCK, series.bar_verdicts, clock=fixed_clock
    )
    assert verdict.status == REVIEW_REQUIRED
    assert verdict.total_bars == 100


def test_old_listing_not_new_listing():
    """Halka arzi 200 gun once + 100 bar -> NEW_LISTING degil, LIMITED_DATA."""
    listing = iso(FIXED_TODAY - 200 * DAY)
    verdict = classify_sufficiency(
        STOCK, make_bars(100), listing_date=listing, clock=fixed_clock
    )
    assert verdict.status == LIMITED_DATA


def test_sufficiency_verdict_fields():
    """SufficiencyVerdict(status, valid_bars, total_bars, reason)."""
    verdict = classify_sufficiency(STOCK, make_bars(300), clock=fixed_clock)
    assert isinstance(verdict, SufficiencyVerdict)
    assert verdict.status == SUFFICIENT_DATA
    assert verdict.valid_bars == 300
    assert verdict.total_bars == 300
    assert isinstance(verdict.reason, str) and verdict.reason


# ====================================================================== #
# KATEGORI 8 - Gecit (ReleaseGate) — 6 test
# ====================================================================== #
def _gate_validator():
    return make_validator(
        corporate_lookup=lambda s, d: [],
        source_compare=lambda b: True,
    )


def test_validated_bars_released():
    """VALIDATED barlar analize gecer; GATE_RELEASED loglanir."""
    v = _gate_validator()
    bars = [
        make_bar("2024-06-25", 100.0),
        make_bar("2024-06-26", 101.0),
        make_bar("2024-06-27", 102.0),
    ]
    series = v.validate_series(STOCK, bars)
    report = v.promote_validated([bv.bar_id for bv in series.bar_verdicts])
    assert len(report.promoted) == 3
    gate = ReleaseGate()
    suff = SufficiencyVerdict(SUFFICIENT_DATA, 3, 3, "yeterli")
    decision = gate.release_for_analysis(series, suff)
    assert decision.allowed is True
    assert decision.released_count == 3
    assert decision.bars == bars  # ham nesneler degistirilmeden gecer
    events = gate.events_by_code(GATE_RELEASED)
    assert events and events[0]["released"] == 3


def test_rejected_and_review_removed_and_counted():
    """REJECTED/REVIEW_REQUIRED barlar CIKARILIR ve sayilari raporlanir."""
    v = _gate_validator()
    bars = [
        make_bar("2024-06-25", 100.0),                    # CLEAN -> VALIDATED
        make_bar("2024-06-26", 110.0, open_=0.0),         # REJECTED
        make_bar("2024-06-27", 130.0),                    # REVIEW_REQUIRED (outlier)
    ]
    series = v.validate_series(STOCK, bars)
    v.promote_validated([series.bar_verdicts[0].bar_id])
    gate = ReleaseGate()
    suff = SufficiencyVerdict(LIMITED_DATA, 2, 3, "sinirli")
    decision = gate.release_for_analysis(series, suff)
    assert decision.allowed is True
    assert decision.released_count == 1
    assert decision.rejected_count == 1
    assert decision.review_count == 1
    assert decision.bars == [bars[0]]


def test_clean_bars_blocked_by_default():
    """VALIDATED olmayan CLEAN barlar varsayilanda analize GECMEZ."""
    v = _gate_validator()
    bars = [make_bar("2024-06-26", 100.0), make_bar("2024-06-27", 101.0)]
    series = v.validate_series(STOCK, bars)  # ikisi de CLEAN (promote yok)
    gate = ReleaseGate()
    suff = SufficiencyVerdict(LIMITED_DATA, 2, 2, "sinirli")
    decision = gate.release_for_analysis(series, suff)
    assert decision.allowed is False
    assert decision.bars == []
    assert decision.reason == NO_RELEASABLE_BARS
    assert decision.excluded_count == 2
    assert gate.events_by_code(GATE_BLOCKED)


def test_clean_bars_released_when_allow_clean():
    """allow_clean=True: izinli CLEAN barlar analize birakilir."""
    v = _gate_validator()
    bars = [make_bar("2024-06-26", 100.0), make_bar("2024-06-27", 101.0)]
    series = v.validate_series(STOCK, bars)
    gate = ReleaseGate(allow_clean=True)
    suff = SufficiencyVerdict(LIMITED_DATA, 2, 2, "sinirli")
    decision = gate.release_for_analysis(series, suff)
    assert decision.allowed is True
    assert decision.released_count == 2
    assert decision.bars == bars
    assert gate.events_by_code(GATE_RELEASED)[0]["allow_clean"] is True


def test_insufficient_for_technical_blocks_gate():
    """INSUFFICIENT_FOR_TECHNICAL: analiz modulu CAGRILMAZ (GATE_BLOCKED)."""
    v = _gate_validator()
    bars = make_bars(2, start=date(2024, 6, 26), close=100.0)
    series = v.validate_series(STOCK, bars)
    v.promote_validated([bv.bar_id for bv in series.bar_verdicts])
    suff = classify_sufficiency(STOCK, bars, clock=fixed_clock)
    assert suff.status == INSUFFICIENT_FOR_TECHNICAL
    gate = ReleaseGate()
    decision = gate.release_for_analysis(series, suff)
    assert decision.allowed is False
    assert decision.bars == []
    assert decision.blocked_reason == INSUFFICIENT_FOR_TECHNICAL
    events = gate.events_by_code(GATE_BLOCKED)
    assert events and events[0]["reason"] == INSUFFICIENT_FOR_TECHNICAL


def test_price_data_missing_blocks_gate():
    """PRICE_DATA_MISSING: gecit kapanir, hic bar birakilmaz."""
    gate = ReleaseGate()
    empty = SeriesVerdict(stock_id=STOCK)
    suff = classify_sufficiency(STOCK, [], clock=fixed_clock)
    assert suff.status == PRICE_DATA_MISSING
    decision = gate.release_for_analysis(empty, suff)
    assert decision.allowed is False
    assert decision.bars == []
    assert decision.released_count == 0
    assert decision.blocked_reason == PRICE_DATA_MISSING
    assert gate.events_by_code(GATE_BLOCKED)[0]["reason"] == PRICE_DATA_MISSING
