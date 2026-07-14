"""BLOK 10 - Hacim ve TL Islem Hacmi: TAM 100 pytest testi.

Kategoriler (toplam = 100, SPEC BLOK 10 bolum 8):
1. 20 gunluk ortalama dogrulugu (elle hesaplanan beklenen degerler) (16)
2. Son gun ortalamaya dahil edilmeme (son gun devasa olsa bile ortalama
   degismez) (14)
3. Eksik gun: tatil/kaynak hatasi pencereye sifir girmez, kayar pencere,
   gercek sifir ortalamaya katilir (16)
4. Gercek sifir vs eksik hacim ayrimi + REVIEW_REQUIRED (12)
5. Tahmini hacim: formul dogrulugu ((O+H+L+C)/4 x V), is_estimated bayragi,
   turnover_try=None kalmasi (16)
6. Hacim turu: OFFICIAL/PROVIDER/ESTIMATED/MISSING dogru atama, tahmin
   gercek diye gosterilemez (14)
7. Durum siniflandirma esikleri + sinyal kilidi (signal her zaman None,
   AL/SAT uretimi yok) (12)

Hicbir test ag erisimi yapmaz: tum kayitlar mock/enjekte, saat enjekte
(sabit 2024-06-28). BLOK 6-9'a dokunulmaz; BLOK 8 PriceBar duck-typing ile
okunur.
"""
from __future__ import annotations

from dataclasses import fields
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.services.stock_scanning.volume import (
    HOLIDAY,
    INSUFFICIENT_WINDOW,
    LAST_VOLUME_MISSING,
    NO_DATA,
    RATIO_UNDEFINED,
    REAL_ZERO,
    SOURCE_ERROR,
    ZERO_VOLUME_EXPLAINED,
    ZERO_VOLUME_WITHOUT_EXPLANATION,
    DuplicateDateError,
    SeriesOrderError,
    SignalLockError,
    TurnoverType,
    VolumeAnalyzer,
    VolumeBar,
    VolumeConfig,
    VolumeMetrics,
    VolumeStatus,
    avg_volume,
    classify_volume,
    compute_ratio_20,
    estimate_turnover,
    resolve_turnover,
    valid_volume,
    volume_ratio,
    window_volumes,
)

FIXED_NOW = date(2024, 6, 28)
BASE = date(2024, 1, 2)


def day(n: int) -> str:
    """BASE + n gun (ISO)."""
    return (BASE + timedelta(days=n)).isoformat()


def ns(day_str, volume, missing_reason=None, is_trading_day=True, **extra):
    """Duck-typed bar (SimpleNamespace) — ratio fonksiyonlari icin."""
    data = dict(
        stock_id="X",
        trade_date=day_str,
        volume_units=volume,
        missing_reason=missing_reason,
        is_trading_day=is_trading_day,
    )
    data.update(extra)
    return SimpleNamespace(**data)


def ns_series(volumes, start=0):
    return [ns(day(start + i), v) for i, v in enumerate(volumes)]


def make_analyzer(**kwargs):
    kwargs.setdefault("clock", lambda: FIXED_NOW)
    return VolumeAnalyzer(**kwargs)


def make_bar(analyzer, day_str, volume, ohlc=(10.0, 10.0, 10.0, 10.0), **extra):
    """Ham kayit -> VolumeBar (analyzer.build_volume_bar)."""
    record = {
        "stock_id": "X",
        "trade_date": day_str,
        "volume": volume,
        "open": ohlc[0],
        "high": ohlc[1],
        "low": ohlc[2],
        "close": ohlc[3],
        "source": "test_provider",
    }
    record.update(extra)
    return analyzer.build_volume_bar(record)


def bar_series(volumes, start=0, analyzer=None):
    a = analyzer or make_analyzer()
    return [make_bar(a, day(start + i), v) for i, v in enumerate(volumes)]


# --------------------------------------------------------------------- #
# 1) 20 gunluk ortalama dogrulugu (16 test)
# --------------------------------------------------------------------- #
class TestAvg20Correctness:
    def test_avg_of_20_known_values(self):
        bars = ns_series(list(range(1, 22)))  # 1..21
        # son gun (21) haric: 1..20 ortalamasi = 210/20 = 10.5
        assert avg_volume(bars) == 10.5

    def test_avg_returns_exact_float(self):
        bars = ns_series(list(range(1, 22)))
        result = avg_volume(bars)
        assert isinstance(result, float)
        assert result == 10.5

    def test_custom_window_5(self):
        bars = ns_series(list(range(1, 22)))
        # window=5: son gun haric son 5 gecerli = 16,17,18,19,20 -> 90/5
        assert avg_volume(bars, window=5) == 18.0

    def test_fewer_valid_than_window_hand_computed(self):
        bars = ns_series(list(range(2, 15)))  # 2..14 (13 bar)
        # son gun (14) haric: 2..13 -> toplam 90, 12 gun -> 7.5
        assert avg_volume(bars) == 7.5

    def test_no_valid_days_returns_none(self):
        bars = ns_series([None, None, None])
        assert avg_volume(bars) is None

    def test_empty_series_returns_none(self):
        assert avg_volume([]) is None

    def test_alternating_values(self):
        prev = [100 if i % 2 == 0 else 200 for i in range(20)]
        bars = ns_series(prev + [999])
        # 10x100 + 10x200 = 3000/20 = 150.0
        assert avg_volume(bars) == 150.0

    def test_duck_typing_minimal_namespace(self):
        # sadece volume_units niteligi olan nesneler de calisir
        bars = [SimpleNamespace(volume_units=v) for v in [10, 20, 30, 40]]
        # son (40) haric: (10+20+30)/3 = 20.0
        assert avg_volume(bars, window=20) == 20.0

    def test_real_zero_counts_as_zero(self):
        prev = [100] * 19 + [0]
        bars = ns_series(prev + [50])
        # 19x100 + 0 = 1900 / 20 = 95.0
        assert avg_volume(bars) == 95.0

    def test_compute_ratio_returns_triple(self):
        bars = ns_series(list(range(1, 22)))
        result = compute_ratio_20(bars)
        assert isinstance(result, tuple) and len(result) == 3
        ratio, avg20, used = result
        assert ratio == 21 / 10.5
        assert avg20 == 10.5
        assert used == 20

    def test_ratio_equals_last_over_avg(self):
        bars = ns_series(list(range(1, 21)) + [210])
        ratio, avg20, used = compute_ratio_20(bars)
        assert avg20 == 10.5
        assert ratio == 20.0
        assert used == 20

    def test_window_larger_than_available(self):
        bars = ns_series([4] * 8)
        ratio, avg20, used = compute_ratio_20(bars)
        assert used == 7  # son haric 7 gecerli gun
        assert avg20 == 4.0
        assert ratio == 1.0

    def test_window_one(self):
        bars = ns_series([5, 7, 9])
        # window=1: son gun haric son 1 gecerli gun = 7
        assert avg_volume(bars, window=1) == 7.0

    def test_exclude_last_false_includes_last(self):
        bars = ns_series(list(range(1, 21)) + [1000])
        assert avg_volume(bars, exclude_last=True) == 10.5
        # dahil edilirse: 2..20 + 1000 -> 1209/20 = 60.45
        assert avg_volume(bars, exclude_last=False) == 60.45

    def test_deterministic_repeated_calls(self):
        bars = ns_series(list(range(1, 22)))
        results = [avg_volume(bars) for _ in range(3)]
        assert results == [10.5, 10.5, 10.5]

    def test_extra_attrs_ignored(self):
        bars = [
            ns(day(i), v, turnover_try=999.9, foo="bar")
            for i, v in enumerate([10, 20, 30, 40])
        ]
        assert avg_volume(bars) == 20.0  # 10+20+30... son haric: 10,20,30 -> 20.0


# --------------------------------------------------------------------- #
# 2) Son gun ortalamaya dahil edilmeme (14 test)
# --------------------------------------------------------------------- #
class TestLastDayExcluded:
    def test_huge_last_day_avg_unchanged(self):
        bars = ns_series(list(range(1, 21)) + [10**9])
        assert avg_volume(bars) == 10.5

    def test_zero_last_day_avg_unchanged(self):
        bars = ns_series(list(range(1, 21)) + [0])
        assert avg_volume(bars) == 10.5

    def test_missing_last_day_avg_unchanged(self):
        bars = ns_series(list(range(1, 21)) + [None])
        assert avg_volume(bars) == 10.5

    def test_ratio_changes_avg_constant(self):
        base = list(range(1, 21))
        r1, a1, _ = compute_ratio_20(ns_series(base + [210]))
        r2, a2, _ = compute_ratio_20(ns_series(base + [30]))
        assert a1 == a2 == 10.5
        assert r1 == 20.0
        assert r2 == 30 / 10.5

    def test_exact_21_bars_uses_first_20(self):
        bars = ns_series(list(range(1, 22)))
        # son bar (21) dahil edilseydi pencere 2..21 -> 230/20 = 11.5 olurdu
        assert avg_volume(bars, exclude_last=False) == 11.5
        assert avg_volume(bars) == 10.5

    def test_sliding_window_22_bars(self):
        bars = ns_series(list(range(1, 23)))  # 1..22
        # son (22) haric, pencere 20: 2..21 -> toplam 230 -> 11.5
        assert avg_volume(bars) == 11.5

    def test_huge_last_ratio_reflects_last(self):
        bars = ns_series(list(range(1, 21)) + [10**6])
        ratio, avg20, used = compute_ratio_20(bars)
        assert avg20 == 10.5
        assert ratio == 10**6 / 10.5
        assert used == 20

    def test_two_last_values_same_avg(self):
        base = list(range(1, 21))
        assert avg_volume(ns_series(base + [5])) == avg_volume(ns_series(base + [500]))

    def test_exclude_last_param_difference(self):
        bars = ns_series(list(range(1, 21)) + [1000])
        with_last = avg_volume(bars, exclude_last=False)
        without_last = avg_volume(bars, exclude_last=True)
        assert with_last != without_last
        assert without_last == 10.5
        assert with_last == 60.45

    def test_analyzer_avg_excludes_last(self):
        a = make_analyzer()
        bars = bar_series([100] * 20 + [10**7], analyzer=a)
        metrics = a.analyze_series("X", bars)
        assert metrics.avg20_volume_units == 100.0

    def test_metrics_last_volume_is_huge(self):
        a = make_analyzer()
        bars = bar_series([100] * 20 + [10**7], analyzer=a)
        metrics = a.analyze_series("X", bars)
        assert metrics.last_volume_units == 10**7
        assert metrics.avg20_volume_units == 100.0
        assert metrics.volume_ratio_20 == 10**7 / 100.0

    def test_only_last_bar_excluded_not_last_valid(self):
        # pencere icindeki eksik gunler zaten atlanir; son BAR cikarilir
        volumes = [100] * 23
        bars = ns_series(volumes)
        bars[5] = ns(day(5), None, missing_reason=NO_DATA)
        bars[10] = ns(day(10), None, missing_reason=NO_DATA)
        bars[-1] = ns(day(22), 999)
        assert avg_volume(bars) == 100.0
        bars[-1] = ns(day(22), 1)
        assert avg_volume(bars) == 100.0

    def test_last_bar_holiday(self):
        bars = ns_series([i * 10 for i in range(1, 22)])  # 10..210 (21 bar)
        bars.append(ns(day(21), None, missing_reason=HOLIDAY, is_trading_day=False))
        # son bar tatil -> adaylar 10..210 (21 gecerli) -> pencere: 20..210
        # toplam = (20+210)*20/2 = 2300 -> 115.0
        assert avg_volume(bars) == 115.0

    def test_compute_ratio_huge_last(self):
        bars = ns_series(list(range(1, 21)) + [10**6])
        ratio, avg20, used = compute_ratio_20(bars)
        assert ratio == 10**6 / 10.5
        assert used == 20


# --------------------------------------------------------------------- #
# 3) Eksik gun / gercek sifir ortalamasi (16 test)
# --------------------------------------------------------------------- #
class TestMissingDaysAndRealZeroAverage:
    def test_holiday_skipped_not_zero(self):
        bars = ns_series([100] * 22)
        bars[3] = ns(day(3), None, missing_reason=HOLIDAY, is_trading_day=False)
        # son haric 21 aday -> 20 gecerli (tatil atlandi) -> 100.0
        # tatil sifir sayilsaydi 2000/21 != 100.0 olurdu
        assert avg_volume(bars) == 100.0

    def test_source_error_skipped(self):
        bars = ns_series([100] * 22)
        bars[7] = ns(day(7), None, missing_reason=SOURCE_ERROR)
        assert avg_volume(bars) == 100.0

    def test_no_data_skipped(self):
        bars = ns_series([100] * 22)
        bars[9] = ns(day(9), None, missing_reason=NO_DATA)
        assert avg_volume(bars) == 100.0

    def test_missing_not_diluting(self):
        bars = ns_series([100] * 11)
        bars[5] = ns(day(5), None, missing_reason=NO_DATA)
        # 10 gecerli x 100 -> 100.0 (sifir eklenip 90.9 olmaz)
        assert avg_volume(bars) == 100.0

    def test_window_slides_over_missing(self):
        bars = ns_series([50] * 24)
        for idx in (3, 11, 19):
            bars[idx] = ns(day(idx), None, missing_reason=NO_DATA)
        ratio, avg20, used = compute_ratio_20(bars)
        assert used == 20  # 23 aday - 3 eksik = 20 gecerli (pencere kaydi)
        assert avg20 == 50.0
        assert ratio == 1.0

    def test_real_zero_joins_average(self):
        prev = [100] * 19 + [0]
        bars = ns_series(prev + [100])
        ratio, avg20, used = compute_ratio_20(bars)
        assert avg20 == 95.0
        assert used == 20
        assert ratio == 100 / 95.0

    def test_missing_vs_zero_different_avg(self):
        base = [100] * 20
        with_missing = ns_series(base + [100])
        with_missing[7] = ns(day(7), None, missing_reason=NO_DATA)
        with_zero = ns_series(base + [100])
        with_zero[7] = ns(day(7), 0)
        # eksik: 19 gecerli -> 100.0 ; gercek sifir: 20 gecerli -> 95.0
        assert avg_volume(with_missing) == 100.0
        assert avg_volume(with_zero) == 95.0

    def test_used_days_counts_valid_only(self):
        bars = ns_series([80] * 24)
        for idx in (1, 4, 8, 12, 16):
            bars[idx] = ns(day(idx), None, missing_reason=NO_DATA)
        _, _, used = compute_ratio_20(bars)
        assert used == 18  # 23 aday - 5 eksik

    def test_used_days_counts_zeros(self):
        bars = ns_series([60] * 24)
        for idx in (2, 6, 10):
            bars[idx] = ns(day(idx), 0)  # gercek sifir — gecerli
        for idx in (1, 4, 8, 12, 16):
            bars[idx] = ns(day(idx), None, missing_reason=NO_DATA)
        _, avg20, used = compute_ratio_20(bars)
        assert used == 18  # 15 dolu + 3 gercek sifir
        assert avg20 == (15 * 60) / 18

    def test_insufficient_window_ratio_none(self):
        bars = ns_series([10, 10, 10, 10, 10])  # son haric 4 gecerli
        ratio, avg20, used = compute_ratio_20(bars)
        assert used == 4
        assert avg20 == 10.0  # eldekiyle hesaplanir ve raporlanir
        assert ratio is None  # min_valid_days(5) alti -> oran yok

    def test_min_boundary_five_valid_days(self):
        bars = ns_series([10, 10, 10, 10, 10, 30])  # son haric 5 gecerli
        ratio, avg20, used = compute_ratio_20(bars)
        assert used == 5
        assert avg20 == 10.0
        assert ratio == 3.0

    def test_custom_min_valid_days(self):
        bars = ns_series([10, 10, 10, 10, 30])  # son haric 4 gecerli
        ratio_default, _, _ = compute_ratio_20(bars, min_valid_days=5)
        ratio_custom, _, _ = compute_ratio_20(bars, min_valid_days=3)
        assert ratio_default is None
        assert ratio_custom == 3.0

    def test_avg_zero_ratio_none_no_division(self):
        bars = ns_series([0, 0, 0, 0, 0, 10])  # 5 gercek sifir + son 10
        ratio, avg20, used = compute_ratio_20(bars)
        assert avg20 == 0.0
        assert used == 5
        assert ratio is None  # sifira bolme yok

    def test_volume_ratio_direct_zero_avg(self):
        assert volume_ratio(10, 0.0) is None
        assert volume_ratio(0, 0.0) is None

    def test_used_days_capped_at_window(self):
        bars = ns_series([5] * 31)  # 30 gecerli aday
        _, avg20, used = compute_ratio_20(bars)
        assert used == 20
        assert avg20 == 5.0

    def test_analyzer_end_to_end_mixed(self):
        a = make_analyzer()
        bars = bar_series([100] * 20, analyzer=a)
        bars[5] = make_bar(a, day(5), 0)  # gercek sifir
        bars.append(make_bar(a, day(20), None, is_trading_day=False))  # tatil
        bars.append(make_bar(a, day(21), 200))  # son gun
        metrics = a.analyze_series("X", bars)
        # adaylar: ilk 20 bar + tatil -> 19x100 + 0 = 1900/20 = 95.0
        assert metrics.avg20_volume_units == 95.0
        assert metrics.used_days == 20
        assert metrics.volume_ratio_20 == 200 / 95.0
        assert metrics.status == VolumeStatus.HIGH  # 2.105... >= 2.0
        assert metrics.signal is None
        # seri dogrulama: tekrar tarih reddi + tarih sirasi zorunlulugu
        duplicate = bars + [make_bar(a, day(21), 5)]
        with pytest.raises(DuplicateDateError):
            a.analyze_series("X", duplicate)
        with pytest.raises(SeriesOrderError):
            a.analyze_series("X", list(reversed(bars)))


# --------------------------------------------------------------------- #
# 4) Gercek sifir vs eksik hacim ayrimi + REVIEW_REQUIRED (12 test)
# --------------------------------------------------------------------- #
class TestRealZeroVsMissingSeparation:
    def test_classify_gaps_separates_zero_from_missing(self):
        a = make_analyzer()
        records = [
            {"trade_date": day(0), "volume": 0},       # gercek sifir
            {"trade_date": day(1), "volume": None},    # eksik
        ]
        gaps = a.classify_gaps(records)
        assert gaps[REAL_ZERO] == [day(0)]
        assert gaps[NO_DATA] == [day(1)]

    def test_classify_gaps_buckets(self):
        a = make_analyzer()
        records = [
            {"trade_date": day(0), "is_trading_day": False},
            {"trade_date": day(1), "error": "timeout"},
            {"trade_date": day(2), "volume": None},
            {"trade_date": day(3), "volume": 500},
        ]
        gaps = a.classify_gaps(records)
        assert gaps[HOLIDAY] == [day(0)]
        assert gaps[SOURCE_ERROR] == [day(1)]
        assert gaps[NO_DATA] == [day(2)]
        assert gaps[REAL_ZERO] == []
        assert day(3) not in sum(gaps.values(), [])

    def test_volume_bar_real_zero_fields(self):
        bar = VolumeBar(stock_id="X", trade_date=day(0), volume_units=0)
        assert bar.volume_units == 0
        assert bar.missing_reason is None
        assert valid_volume(bar) == 0  # gecerli: ortalamaya 0 olarak katilir

    def test_volume_bar_missing_fields(self):
        bar = VolumeBar(
            stock_id="X", trade_date=day(0), volume_units=None, missing_reason=NO_DATA
        )
        assert bar.volume_units is None
        assert valid_volume(bar) is None  # ortalamaya katilmaz

    def test_analyze_last_zero_unexplained_review(self):
        a = make_analyzer()
        bars = bar_series([100] * 20 + [0], analyzer=a)
        metrics = a.analyze_series("X", bars)
        assert metrics.status == VolumeStatus.REVIEW_REQUIRED
        assert metrics.status_reason == ZERO_VOLUME_WITHOUT_EXPLANATION

    def test_analyze_last_zero_explained_normal(self):
        explainer = lambda stock_id, trade_date: "TRADING_HALT_KNOWN"
        a = make_analyzer(zero_volume_explainer=explainer)
        bars = bar_series([100] * 20 + [0], analyzer=a)
        metrics = a.analyze_series("X", bars)
        assert metrics.status == VolumeStatus.NORMAL
        assert metrics.status_reason == ZERO_VOLUME_EXPLAINED

    def test_classify_zero_unexplained(self):
        status, reason = classify_volume(last_volume=0, avg20=100.0, ratio=0.0)
        assert status == VolumeStatus.REVIEW_REQUIRED
        assert reason == ZERO_VOLUME_WITHOUT_EXPLANATION

    def test_classify_zero_explained(self):
        status, reason = classify_volume(
            last_volume=0, avg20=100.0, ratio=0.0, zero_explanation="BEDELSIZ"
        )
        assert status == VolumeStatus.NORMAL
        assert reason == ZERO_VOLUME_EXPLAINED

    def test_missing_last_is_missing_not_review(self):
        a = make_analyzer()
        bars = bar_series([100] * 20, analyzer=a)
        bars.append(make_bar(a, day(20), None))  # son gun hacmi yok
        metrics = a.analyze_series("X", bars)
        assert metrics.status == VolumeStatus.MISSING
        assert metrics.status_reason == NO_DATA

    def test_zero_in_middle_no_review(self):
        a = make_analyzer()
        volumes = [100] * 20 + [100]
        bars = bar_series(volumes, analyzer=a)
        bars[10] = make_bar(a, day(10), 0)  # ortada gercek sifir
        metrics = a.analyze_series("X", bars)
        assert metrics.avg20_volume_units == 95.0
        assert metrics.status == VolumeStatus.NORMAL  # ratio 100/95 < 1.3

    def test_valid_volume_distinguishes(self):
        zero_bar = ns(day(0), 0)
        missing_bar = ns(day(1), None, missing_reason=NO_DATA)
        holiday_bar = ns(day(2), None, missing_reason=HOLIDAY, is_trading_day=False)
        assert valid_volume(zero_bar) == 0
        assert valid_volume(missing_bar) is None
        assert valid_volume(holiday_bar) is None

    def test_explainer_receives_stock_and_date(self):
        calls = []
        explainer = lambda stock_id, trade_date: calls.append((stock_id, trade_date)) or "OK"
        a = make_analyzer(zero_volume_explainer=explainer)
        bars = bar_series([100] * 20 + [0], analyzer=a)
        a.analyze_series("THYAO", bars)
        assert calls == [("THYAO", day(20))]


# --------------------------------------------------------------------- #
# 5) Tahmini hacim: formul + etiket (16 test)
# --------------------------------------------------------------------- #
class TestEstimatedTurnover:
    def test_formula_exact(self):
        record = {"open": 10.0, "high": 14.0, "low": 9.0, "close": 11.0, "volume": 100}
        _, estimated, ttype = resolve_turnover(record)
        # (10+14+9+11)/4 = 11.0 ; 11.0 x 100 = 1100.0
        assert estimated == 1100.0
        assert ttype == TurnoverType.ESTIMATED

    def test_formula_fractional(self):
        record = {"open": 10.5, "high": 11.5, "low": 10.0, "close": 11.0, "volume": 123}
        _, estimated, _ = resolve_turnover(record)
        # (10.5+11.5+10+11)/4 = 10.75 ; 10.75 x 123 = 1322.25
        assert estimated == 1322.25

    def test_estimated_turnover_try_none_pair(self):
        record = {"open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 50}
        turnover_try, estimated, _ = resolve_turnover(record)
        assert turnover_try is None  # KARISTIRILMAZ
        assert estimated == 500.0

    def test_type_estimated(self):
        record = {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 10}
        _, _, ttype = resolve_turnover(record)
        assert ttype == TurnoverType.ESTIMATED

    def test_is_estimated_flag(self):
        a = make_analyzer()
        bar = make_bar(a, day(0), 100, ohlc=(10.0, 14.0, 9.0, 11.0))
        assert bar.is_estimated is True
        assert bar.turnover_type == TurnoverType.ESTIMATED
        assert bar.turnover_try is None
        assert bar.estimated_turnover_try == 1100.0

    def test_tuple_order(self):
        record = {"open": 2.0, "high": 2.0, "low": 2.0, "close": 2.0, "volume": 10}
        result = resolve_turnover(record)
        assert result == (None, 20.0, TurnoverType.ESTIMATED)

    def test_uses_volume_units_not_turnover(self):
        ohlc = {"open": 10.0, "high": 14.0, "low": 9.0, "close": 11.0}
        r1 = dict(ohlc, volume=100)
        r2 = dict(ohlc, volume=200)
        _, e1, _ = resolve_turnover(r1)
        _, e2, _ = resolve_turnover(r2)
        assert e2 == 2 * e1  # adetle dogru orantili
        assert e1 / 100 == 11.0  # tipik fiyat = adet basina tahmin

    def test_build_from_pricebar_duck(self):
        # BLOK 8 PriceBar benzeri nesne (nitelikli) duck-typing ile okunur
        price_bar = SimpleNamespace(
            stock_id="THYAO",
            trade_date=day(0),
            open=10.0,
            high=14.0,
            low=9.0,
            close=11.0,
            volume=100,
            adjusted_close=11.0,
            currency="TRY",
            source="licensed",
            source_timestamp=None,
            collected_timestamp="2024-06-28T00:00:00Z",
        )
        a = make_analyzer()
        bar = a.build_volume_bar(price_bar)
        assert bar.stock_id == "THYAO"
        assert bar.volume_units == 100
        assert bar.turnover_type == TurnoverType.ESTIMATED
        assert bar.estimated_turnover_try == 1100.0
        assert bar.turnover_try is None

    def test_invariant_estimated_with_turnover_raises(self):
        with pytest.raises(ValueError):
            VolumeBar(
                stock_id="X",
                trade_date=day(0),
                volume_units=100,
                turnover_try=5.0,  # tahmin kaydinda gercek alan doldurulamaz
                estimated_turnover_try=1100.0,
                turnover_type=TurnoverType.ESTIMATED,
                is_estimated=True,
            )

    def test_invariant_estimate_under_official_raises(self):
        with pytest.raises(ValueError):
            VolumeBar(
                stock_id="X",
                trade_date=day(0),
                volume_units=100,
                turnover_try=1100.0,
                estimated_turnover_try=1100.0,  # OFFICIAL altinda tahmin olamaz
                turnover_type=TurnoverType.OFFICIAL,
            )

    def test_to_dict_estimated_prefix(self):
        a = make_analyzer()
        bar = make_bar(a, day(0), 100, ohlc=(10.0, 14.0, 9.0, 11.0))
        data = bar.to_dict()
        assert "estimated_turnover_try" in data
        assert data["estimated_turnover_try"] == 1100.0

    def test_to_dict_never_renames_estimate(self):
        a = make_analyzer()
        bar = make_bar(a, day(0), 100, ohlc=(10.0, 14.0, 9.0, 11.0))
        data = bar.to_dict()
        assert data["turnover_try"] is None  # tahmin gercek alana tasinmadi
        assert "turnover" not in data  # oneksiz 'turnover' anahtari yok
        assert data["turnover_type"] == "ESTIMATED"
        assert data["is_estimated"] is True

    def test_label_required_config_default(self):
        cfg = VolumeConfig()
        assert cfg.estimated_label_required is True
        a = make_analyzer()
        bar = make_bar(a, day(0), 100, ohlc=(10.0, 14.0, 9.0, 11.0), source="kaynak_a")
        # tahmin ciktisi kaynak etiketi tasir (source + ESTIMATED turu)
        assert bar.source == "kaynak_a"
        assert bar.turnover_type == TurnoverType.ESTIMATED
        assert bar.is_estimated is True

    def test_linear_in_volume(self):
        ohlc = {"open": 10.0, "high": 14.0, "low": 9.0, "close": 11.0}
        _, e100, _ = resolve_turnover(dict(ohlc, volume=100))
        _, e250, _ = resolve_turnover(dict(ohlc, volume=250))
        assert e100 == 1100.0
        assert e250 == 2750.0

    def test_missing_ohlc_raises(self):
        a = make_analyzer()
        record = {"stock_id": "X", "trade_date": day(0), "volume": 100, "source": "x"}
        with pytest.raises(ValueError):
            a.build_volume_bar(record)

    def test_zero_volume_estimate_zero(self):
        record = {"open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 0}
        turnover_try, estimated, ttype = resolve_turnover(record)
        assert estimated == 0.0
        assert turnover_try is None
        assert ttype == TurnoverType.ESTIMATED


# --------------------------------------------------------------------- #
# 6) Hacim turu atama: OFFICIAL/PROVIDER/ESTIMATED/MISSING (14 test)
# --------------------------------------------------------------------- #
class TestTurnoverTypeAssignment:
    def _record(self, source, **extra):
        record = {
            "stock_id": "X",
            "trade_date": day(0),
            "open": 10.0,
            "high": 14.0,
            "low": 9.0,
            "close": 11.0,
            "volume": 100,
            "source": source,
        }
        record.update(extra)
        return record

    def test_official_source(self):
        record = self._record("bist", turnover_try=12345.0)
        turnover_try, estimated, ttype = resolve_turnover(record)
        assert ttype == TurnoverType.OFFICIAL
        assert turnover_try == 12345.0
        assert estimated is None

    def test_provider_source(self):
        record = self._record("yfinance", turnover_try=12345.0)
        turnover_try, estimated, ttype = resolve_turnover(record)
        assert ttype == TurnoverType.PROVIDER
        assert turnover_try == 12345.0
        assert estimated is None

    def test_source_name_decides(self):
        official = resolve_turnover(self._record("bist", turnover_try=100.0))
        provider = resolve_turnover(self._record("yahoo", turnover_try=100.0))
        assert official[2] == TurnoverType.OFFICIAL
        assert provider[2] == TurnoverType.PROVIDER

    def test_custom_official_sources(self):
        cfg = VolumeConfig(official_sources=frozenset({"kaynak_x"}))
        assert resolve_turnover(self._record("kaynak_x", turnover_try=1.0), config=cfg)[2] == TurnoverType.OFFICIAL
        assert resolve_turnover(self._record("kaynak_y", turnover_try=1.0), config=cfg)[2] == TurnoverType.PROVIDER

    def test_no_turnover_field_estimated(self):
        record = self._record("bist")  # resmi kaynak ama TL alani yok
        turnover_try, estimated, ttype = resolve_turnover(record)
        assert ttype == TurnoverType.ESTIMATED  # asla OFFICIAL degil
        assert turnover_try is None
        assert estimated == 1100.0

    def test_missing_volume_missing_type(self):
        record = {"stock_id": "X", "trade_date": day(0), "source": "bist"}
        turnover_try, estimated, ttype = resolve_turnover(record)
        assert ttype == TurnoverType.MISSING
        assert turnover_try is None
        assert estimated is None

    def test_estimate_never_official(self):
        with pytest.raises(ValueError):
            VolumeBar(
                stock_id="X",
                trade_date=day(0),
                volume_units=100,
                turnover_type=TurnoverType.OFFICIAL,
                is_estimated=True,  # tahmin OFFICIAL etiketi tasiyamaz
            )

    def test_estimate_never_provider(self):
        with pytest.raises(ValueError):
            VolumeBar(
                stock_id="X",
                trade_date=day(0),
                volume_units=100,
                turnover_type=TurnoverType.PROVIDER,
                estimated_turnover_try=1100.0,  # PROVIDER altinda tahmin olamaz
            )

    def test_build_official_bar_fields(self):
        a = make_analyzer()
        bar = a.build_volume_bar(self._record("bist", turnover_try=999.0))
        assert bar.turnover_type == TurnoverType.OFFICIAL
        assert bar.turnover_try == 999.0
        assert bar.estimated_turnover_try is None
        assert bar.is_estimated is False

    def test_build_provider_bar_fields(self):
        a = make_analyzer()
        bar = a.build_volume_bar(self._record("yfinance", turnover_try=999.0))
        assert bar.turnover_type == TurnoverType.PROVIDER
        assert bar.turnover_try == 999.0
        assert bar.estimated_turnover_try is None
        assert bar.is_estimated is False

    def test_missing_bar_reason_inferred(self):
        a = make_analyzer()
        bar = a.build_volume_bar({"stock_id": "X", "trade_date": day(0), "source": "s"})
        assert bar.turnover_type == TurnoverType.MISSING
        assert bar.missing_reason == NO_DATA
        assert bar.turnover_try is None
        assert bar.estimated_turnover_try is None

    def test_holiday_record(self):
        a = make_analyzer()
        bar = a.build_volume_bar(
            {"stock_id": "X", "trade_date": day(0), "is_trading_day": False}
        )
        assert bar.turnover_type == TurnoverType.MISSING
        assert bar.missing_reason == HOLIDAY
        assert bar.is_trading_day is False

    def test_source_error_record(self):
        a = make_analyzer()
        bar = a.build_volume_bar(
            {"stock_id": "X", "trade_date": day(0), "error": "timeout", "volume": None}
        )
        assert bar.turnover_type == TurnoverType.MISSING
        assert bar.missing_reason == SOURCE_ERROR

    def test_official_no_double_fill(self):
        # resmi TL alani + OHLC + hacim var: tahmin alani doldurulMAZ
        a = make_analyzer()
        bar = a.build_volume_bar(self._record("bist", turnover_try=500.0))
        assert bar.turnover_try == 500.0
        assert bar.estimated_turnover_try is None
        assert bar.is_estimated is False


# --------------------------------------------------------------------- #
# 7) Durum esikleri + sinyal kilidi (12 test)
# --------------------------------------------------------------------- #
class TestStatusThresholdsAndSignalLock:
    def test_anomalous_threshold(self):
        status, reason = classify_volume(last_volume=500, avg20=100.0, ratio=5.0)
        assert status == VolumeStatus.ANOMALOUS
        assert reason == "ratio>=5"

    def test_high_threshold(self):
        status, reason = classify_volume(last_volume=250, avg20=100.0, ratio=2.5)
        assert status == VolumeStatus.HIGH
        assert reason == "ratio>=2"

    def test_increasing_threshold(self):
        status, reason = classify_volume(last_volume=150, avg20=100.0, ratio=1.5)
        assert status == VolumeStatus.INCREASING
        assert reason == "ratio>=1.3"

    def test_normal_band(self):
        status, reason = classify_volume(last_volume=100, avg20=100.0, ratio=1.0)
        assert status == VolumeStatus.NORMAL
        assert reason == "ratio<1.3"

    def test_boundaries(self):
        assert classify_volume(last_volume=1, avg20=1.0, ratio=2.0)[0] == VolumeStatus.HIGH
        assert classify_volume(last_volume=1, avg20=1.0, ratio=1.3)[0] == VolumeStatus.INCREASING
        assert classify_volume(last_volume=1, avg20=1.0, ratio=1.2999)[0] == VolumeStatus.NORMAL
        assert classify_volume(last_volume=1, avg20=1.0, ratio=4.999)[0] == VolumeStatus.HIGH
        assert classify_volume(last_volume=1, avg20=1.0, ratio=5.0)[0] == VolumeStatus.ANOMALOUS

    def test_custom_thresholds(self):
        cfg = VolumeConfig(
            increasing_threshold=1.1, high_threshold=1.5, anomalous_threshold=3.0
        )
        assert classify_volume(config=cfg, last_volume=1, avg20=1.0, ratio=1.2)[0] == VolumeStatus.INCREASING
        assert classify_volume(config=cfg, last_volume=1, avg20=1.0, ratio=2.0)[0] == VolumeStatus.HIGH
        assert classify_volume(config=cfg, last_volume=1, avg20=1.0, ratio=3.0)[0] == VolumeStatus.ANOMALOUS
        assert classify_volume(config=cfg, last_volume=1, avg20=1.0, ratio=1.0)[0] == VolumeStatus.NORMAL

    def test_isolated_spike_stays_anomalous(self):
        a = make_analyzer()
        normal = a.analyze_series("X", bar_series([100] * 21, analyzer=a))
        assert normal.status == VolumeStatus.NORMAL  # onceki gunler ANOMALOUS degil
        spike = a.analyze_series("X", bar_series([100] * 20 + [600], analyzer=a))
        assert spike.volume_ratio_20 == 6.0
        assert spike.status == VolumeStatus.ANOMALOUS  # izole sicrama da ANOMALOUS kalir

    def test_signal_none_anomalous(self):
        a = make_analyzer()
        metrics = a.analyze_series("X", bar_series([100] * 20 + [10**6], analyzer=a))
        assert metrics.status == VolumeStatus.ANOMALOUS
        assert metrics.signal is None

    def test_signal_lock_raises(self):
        for bad in ("AL", "SAT", "FAVORI", "BUY"):
            with pytest.raises(SignalLockError):
                VolumeMetrics(stock_id="X", as_of_date=day(0), signal=bad)
        with pytest.raises(ValueError):  # SignalLockError bir ValueError'dir
            VolumeMetrics(stock_id="X", as_of_date=day(0), signal="AL")

    def test_signal_none_all_statuses(self):
        a = make_analyzer()
        scenarios = []
        for last in (100, 150, 250, 600):  # NORMAL, INCREASING, HIGH, ANOMALOUS
            scenarios.append(a.analyze_series("X", bar_series([100] * 20 + [last], analyzer=a)))
        missing_bars = bar_series([100] * 20, analyzer=a)
        missing_bars.append(make_bar(a, day(20), None))
        scenarios.append(a.analyze_series("X", missing_bars))  # MISSING
        scenarios.append(
            a.analyze_series("X", bar_series([100] * 20 + [0], analyzer=a))
        )  # REVIEW_REQUIRED
        statuses = {m.status for m in scenarios}
        assert statuses == {
            VolumeStatus.NORMAL,
            VolumeStatus.INCREASING,
            VolumeStatus.HIGH,
            VolumeStatus.ANOMALOUS,
            VolumeStatus.MISSING,
            VolumeStatus.REVIEW_REQUIRED,
        }
        assert all(m.signal is None for m in scenarios)

    def test_no_signal_api(self):
        # classify_volume sadece (status, reason) dondurur — sinyal yok
        result = classify_volume(last_volume=600, avg20=100.0, ratio=6.0)
        assert isinstance(result, tuple) and len(result) == 2
        status, reason = result
        assert isinstance(status, VolumeStatus)
        assert isinstance(reason, str)
        # VolumeMetrics.signal alaninin varsayilani None (sinyal kilidi)
        signal_field = [f for f in fields(VolumeMetrics) if f.name == "signal"][0]
        assert signal_field.default is None

    def test_anomalous_produces_no_buy_sell(self):
        a = make_analyzer()
        metrics = a.analyze_series("X", bar_series([100] * 20 + [10**6], analyzer=a))
        assert metrics.status == VolumeStatus.ANOMALOUS
        assert metrics.status_reason == "ratio>=5"
        assert metrics.signal is None
        # anormal hacim tek basina AL/SAT/FAVORI uretmez: durum ve neden
        # degerleri sinyal sozcuklerinden hicbirine esit degildir
        signal_words = {"AL", "SAT", "FAVORI", "BUY", "SELL"}
        assert metrics.status.value not in signal_words
        assert str(metrics.status_reason) not in signal_words
