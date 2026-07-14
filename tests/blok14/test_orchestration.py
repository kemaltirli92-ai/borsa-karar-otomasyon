"""BLOK 14 - Zamanlama, Paralellik ve Durum Makinesi: TAM 100 pytest testi.

Kategoriler (toplam = 100, SPEC BLOK 14 bolum 11):
1. Zamanlama: 8 dilim siralama/sinirlar, DATA_CUTOFF 09:40 sabit,
   Europe/Istanbul, islem gunu/tatil (16).
2. Paralellik: max_workers sinirli, tek senkron dongu degil,
   concurrency_limit asilmaz, wait_all (14).
3. Hata toleransi: 1 hisse patlar 99 devam, kaynak eksik -> PARTIAL,
   tumu patlarsa FAILED sayilari (14).
4. Cift run_id: ayni run_id ikinci baslatma reddi, duplicate sayaci,
   kayit yazilmaz (12).
5. R2 olusturma: bilincli yeniden tarama R2/R3, parent_run_id,
   tamamlanmamis run'a R2 yok (12).
6. Durum gecisleri: 11 durum, izinli/izinsiz gecisler,
   INACTIVE kurallari (16).
7. Retry/backoff: hemen/30/90 plani, yedek kaynak gecis logu,
   deneme asimi (10).
8. Kaynak politikasi: rpm kovasi, timeout, varsayilan politikalar (6).

Hicbir test gercek aga erismez: tum kaynaklar mock/enjekte edilir.
Saat enjekte edilir (deterministik). Gercek bekleme YOK. stdlib only.
"""
from __future__ import annotations

import threading
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services.stock_scanning.orchestration.limits import (
    RateLimiter,
    SourcePolicy,
    default_policies,
)
from app.services.stock_scanning.orchestration.orchestrator import (
    FlowReport,
    MemoryLogger,
    PoolLimitExceededError,
    ScanOrchestrator,
)
from app.services.stock_scanning.orchestration.pool import ControlledPool, PoolTask
from app.services.stock_scanning.orchestration.retry import (
    FALLBACK_SWITCHED,
    RetryPolicy,
)
from app.services.stock_scanning.orchestration.runs import (
    RUN_ABORTED,
    RUN_ACTIVE,
    RUN_COMPLETED,
    RUN_FAILED,
    RescanNotAllowedError,
    RunAlreadyActiveError,
    RunNotFoundError,
    RunRegistry,
)
from app.services.stock_scanning.orchestration.schedule import (
    DATA_CUTOFF_TIME,
    ISTANBUL_TZ,
    NOT_TRADING_DAY,
    OUTSIDE_SCHEDULE,
    Phase,
    PhaseWindow,
    ScanSchedule,
)
from app.services.stock_scanning.orchestration.states import (
    CONSCIOUS_RESCAN_REASON,
    TRANSITIONS,
    InvalidTransitionError,
    ScanState,
    StockScanStatus,
    assert_transition,
    can_transition,
)

# 2025-01-06 Pazartesi; 2025-01-04 Cumartesi; 2025-01-05 Pazar.
MONDAY = date(2025, 1, 6)
SATURDAY = date(2025, 1, 4)
SUNDAY = date(2025, 1, 5)

T0800 = datetime(2025, 1, 6, 8, 0, 0, tzinfo=ISTANBUL_TZ)
T0830 = datetime(2025, 1, 6, 8, 30, 0, tzinfo=ISTANBUL_TZ)


def _dt(hour: int, minute: int, second: int = 0, day: date = MONDAY) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=ISTANBUL_TZ)


def _ok_collectors():
    return {
        "price": lambda sid: {"close": 10.0},
        "kap": lambda sid: {"items": 1},
        "news": lambda sid: {"items": 2},
        "actions": lambda sid: {"items": 0},
        "restrictions": lambda sid: {"items": 0},
    }


def _make_orchestrator(collectors=None, clock=None, **kwargs):
    return ScanOrchestrator(
        collectors=collectors if collectors is not None else _ok_collectors(),
        clock=clock or (lambda: T0830),
        **kwargs,
    )


# =====================================================================
# 1. ZAMANLAMA (16 test)
# =====================================================================
class TestZamanlama:
    def test_schedule_has_exactly_eight_windows(self):
        schedule = ScanSchedule()
        assert len(schedule.windows) == 8
        assert [w.phase for w in schedule.windows] == [
            Phase.PRECHECK,
            Phase.COLLECTION,
            Phase.CLEANING,
            Phase.RECOVERY,
            Phase.PACKAGING,
            Phase.ANOMALY_CHECK,
            Phase.DATA_CUTOFF,
            Phase.CRITICAL_RESCAN,
        ]

    def test_window_order_numbers_monotonic(self):
        schedule = ScanSchedule()
        assert [w.order for w in schedule.windows] == [1, 2, 3, 4, 5, 6, 7, 8]

    def test_precheck_point_at_0800(self):
        w = ScanSchedule().window_for(Phase.PRECHECK)
        assert w.point is True
        assert w.start == time(8, 0) == w.end

    def test_collection_window_bounds(self):
        w = ScanSchedule().window_for(Phase.COLLECTION)
        assert (w.start, w.end) == (time(8, 0), time(8, 45))
        assert w.point is False

    def test_cleaning_window_bounds(self):
        w = ScanSchedule().window_for(Phase.CLEANING)
        assert (w.start, w.end) == (time(8, 45), time(9, 0))

    def test_recovery_window_bounds(self):
        w = ScanSchedule().window_for(Phase.RECOVERY)
        assert (w.start, w.end) == (time(9, 0), time(9, 30))

    def test_packaging_window_bounds(self):
        w = ScanSchedule().window_for(Phase.PACKAGING)
        assert (w.start, w.end) == (time(9, 30), time(9, 35))

    def test_anomaly_check_window_bounds(self):
        w = ScanSchedule().window_for(Phase.ANOMALY_CHECK)
        assert (w.start, w.end) == (time(9, 35), time(9, 40))

    def test_data_cutoff_fixed_0940_point(self):
        schedule = ScanSchedule()
        w = schedule.window_for(Phase.DATA_CUTOFF)
        assert DATA_CUTOFF_TIME == time(9, 40)
        assert schedule.data_cutoff == time(9, 40)
        assert w.point is True and w.start == time(9, 40)
        # DATA_CUTOFF baska saate tasinarak schedule kurulamaz (sabit kural).
        bad = tuple(
            PhaseWindow(x.phase, time(9, 41) if x.phase is Phase.DATA_CUTOFF else x.start,
                        time(9, 41) if x.phase is Phase.DATA_CUTOFF else x.end,
                        x.order, x.point)
            for x in schedule.windows
        )
        with pytest.raises(ValueError):
            ScanSchedule(windows=bad)

    def test_critical_rescan_window_bounds(self):
        w = ScanSchedule().window_for(Phase.CRITICAL_RESCAN)
        assert (w.start, w.end) == (time(9, 40), time(9, 45))
        assert w.point is False

    def test_timezone_fixed_europe_istanbul(self):
        schedule = ScanSchedule()
        assert str(ISTANBUL_TZ) == "Europe/Istanbul"
        assert schedule.timezone is ISTANBUL_TZ

    def test_timezone_cannot_be_injected_and_window_count_fixed(self):
        with pytest.raises(ValueError):
            ScanSchedule(timezone=ZoneInfo("UTC"))
        with pytest.raises(ValueError):
            ScanSchedule(windows=())  # tam 8 dilim zorunlu

    def test_current_phase_precheck_then_collection(self):
        schedule = ScanSchedule()
        assert schedule.current_phase(_dt(8, 0, 0)) == Phase.PRECHECK
        assert schedule.current_phase(_dt(8, 0, 30)) == Phase.COLLECTION

    def test_current_phase_boundaries_and_outside_schedule(self):
        schedule = ScanSchedule()
        assert schedule.current_phase(_dt(8, 44, 59)) == Phase.COLLECTION
        assert schedule.current_phase(_dt(8, 45, 0)) == Phase.CLEANING
        assert schedule.current_phase(_dt(9, 29, 59)) == Phase.RECOVERY
        assert schedule.current_phase(_dt(9, 30, 0)) == Phase.PACKAGING
        assert schedule.current_phase(_dt(9, 35, 0)) == Phase.ANOMALY_CHECK
        assert schedule.current_phase(_dt(7, 59, 59)) == OUTSIDE_SCHEDULE
        assert schedule.current_phase(_dt(9, 45, 0)) == OUTSIDE_SCHEDULE
        assert schedule.current_phase(_dt(12, 0, 0)) == OUTSIDE_SCHEDULE

    def test_current_phase_data_cutoff_point_and_rescan(self):
        schedule = ScanSchedule()
        assert schedule.current_phase(_dt(9, 40, 0)) == Phase.DATA_CUTOFF
        assert schedule.current_phase(_dt(9, 40, 1)) == Phase.CRITICAL_RESCAN
        assert schedule.current_phase(_dt(9, 44, 59)) == Phase.CRITICAL_RESCAN

    def test_trading_day_weekend_and_injected_holiday(self):
        schedule = ScanSchedule().with_holidays(MONDAY)
        assert ScanSchedule().is_trading_day(MONDAY) is True
        assert ScanSchedule().is_trading_day(SATURDAY) is False
        assert ScanSchedule().is_trading_day(SUNDAY) is False
        assert schedule.is_trading_day(MONDAY) is False  # enjekte tatil
        assert schedule.current_phase(_dt(8, 30)) == NOT_TRADING_DAY
        assert schedule.current_phase(_dt(8, 30, day=SATURDAY)) == NOT_TRADING_DAY


# =====================================================================
# 2. PARALELLIK (14 test)
# =====================================================================
class TestParalellik:
    def test_sync_pool_runs_all_100_tasks(self):
        pool = ControlledPool(max_workers=8, use_threads=False)
        tasks = [PoolTask(f"s{i:03d}", (lambda i=i: i * 2)) for i in range(100)]
        report = pool.execute(tasks)
        assert (report.completed, report.failed, report.timed_out) == (100, 0, 0)
        assert len(report.results) == 100
        assert report.results["s042"].value == 84

    def test_sync_pool_deterministic_order(self):
        pool = ControlledPool(max_workers=4, use_threads=False)
        pool.execute([PoolTask(f"t{i}", lambda: None) for i in range(10)])
        assert list(pool.results.keys()) == [f"t{i}" for i in range(10)]

    def test_sync_pool_isolation_one_fails_others_continue(self):
        def boom():
            raise RuntimeError("tek hisse patladi")

        pool = ControlledPool(max_workers=4, use_threads=False)
        for i in range(100):
            pool.submit(f"s{i:03d}", boom if i == 7 else (lambda i=i: i))
        report = pool.execute([])
        assert (report.completed, report.failed, report.timed_out) == (99, 1, 0)
        assert report.results["s007"].ok is False
        assert "tek hisse patladi" in report.results["s007"].error
        assert report.results["s099"].ok is True

    def test_sync_pool_execute_never_raises(self):
        pool = ControlledPool(max_workers=2, use_threads=False)
        pool.submit("a", lambda: (_ for _ in ()).throw(ValueError("x")))
        pool.submit("b", lambda: 1)
        report = pool.execute([])  # hata fırlatmadan donmeli
        assert report.failed == 1
        assert report.completed == 1

    def test_sync_pool_peak_concurrency_is_one(self):
        pool = ControlledPool(max_workers=16, use_threads=False)
        pool.execute([PoolTask(f"t{i}", lambda: 1) for i in range(5)])
        assert pool.peak_concurrency == 1  # deterministik mod: sira ile

    def test_thread_pool_peak_bounded_by_max_workers(self):
        barrier = threading.Barrier(3)  # 2 isci + ana thread
        pool = ControlledPool(max_workers=2, use_threads=True)
        pool.submit("w1", lambda: barrier.wait(timeout=5))
        pool.submit("w2", lambda: barrier.wait(timeout=5))
        pool.start()
        barrier.wait(timeout=5)
        completed, failed, timed_out = pool.wait_all(timeout=5)
        assert (completed, failed, timed_out) == (2, 0, 0)
        assert pool.peak_concurrency == 2
        assert pool.peak_concurrency <= pool.max_workers

    def test_thread_pool_distributes_to_multiple_threads(self):
        seen = []
        lock = threading.Lock()

        def task():
            with lock:
                seen.append(threading.current_thread().name)

        pool = ControlledPool(max_workers=4, use_threads=True)
        pool.execute([PoolTask(f"t{i}", task) for i in range(6)])
        assert len(set(seen)) == 6  # tek senkron dongu degil: 6 ayri thread

    def test_thread_pool_isolation(self):
        def boom():
            raise KeyError("kaynak hatasi")

        pool = ControlledPool(max_workers=3, use_threads=True)
        for i in range(9):
            pool.submit(f"t{i}", boom if i == 3 else (lambda: 1))
        pool.start()
        completed, failed, timed_out = pool.wait_all(timeout=5)
        assert (completed, failed, timed_out) == (8, 1, 0)
        assert pool.results["t3"].ok is False

    def test_wait_all_counts_sum_to_task_count(self):
        pool = ControlledPool(max_workers=2, use_threads=False)
        pool.submit("ok1", lambda: 1)
        pool.submit("ok2", lambda: 2)
        pool.submit("bad", lambda: 1 / 0)
        pool.start()
        completed, failed, timed_out = pool.wait_all(timeout=5)
        assert completed + failed + timed_out == pool.task_count == 3

    def test_wait_all_timeout_marks_timed_out(self):
        gate = threading.Event()
        pool = ControlledPool(max_workers=1, use_threads=True)
        pool.submit("slow", lambda: gate.wait(5))
        pool.start()
        completed, failed, timed_out = pool.wait_all(timeout=0)
        assert (completed, failed, timed_out) == (0, 0, 1)
        assert pool.results["slow"].timed_out is True
        gate.set()  # thread'i serbest birak
        completed, failed, timed_out = pool.wait_all(timeout=5)
        assert (completed, failed, timed_out) == (1, 0, 0)

    def test_max_workers_minimum_one(self):
        with pytest.raises(ValueError):
            ControlledPool(max_workers=0)
        with pytest.raises(ValueError):
            ControlledPool(max_workers=-3)

    def test_for_policy_never_exceeds_concurrency_limit(self):
        policy = SourcePolicy("kap", concurrency_limit=2, requests_per_minute=30, timeout=15)
        pool = ControlledPool.for_policy(policy, requested_workers=10)
        assert pool.max_workers == 2
        assert pool.exceeds(policy) is False
        assert ControlledPool.bounded(10, 3).max_workers == 3
        assert ControlledPool.bounded(2, 8).max_workers == 2

    def test_exceeds_check_against_policy(self):
        policy = SourcePolicy("news", concurrency_limit=4, requests_per_minute=40, timeout=10)
        assert ControlledPool(5).exceeds(policy) is True
        assert ControlledPool(4).exceeds(policy) is False

    def test_orchestrator_rejects_oversized_pool_factory(self):
        orchestrator = _make_orchestrator(
            pool_factory=lambda policy: ControlledPool(max_workers=99)
        )
        with pytest.raises(PoolLimitExceededError):
            orchestrator.run_morning_flow(["AAA", "BBB"], now=T0830)


# =====================================================================
# 3. HATA TOLERANSI (14 test)
# =====================================================================
class TestHataToleransi:
    def test_one_stock_price_failure_others_ready(self):
        collectors = _ok_collectors()
        collectors["price"] = lambda sid: (_ for _ in ()).throw(RuntimeError("price kapali")) if sid == "BBB" else {"close": 1}
        orchestrator = _make_orchestrator(collectors=collectors)
        report = orchestrator.run_morning_flow(["AAA", "BBB", "CCC"], now=T0830)
        assert report.counts["FAILED"] == 1
        assert report.counts["READY"] == 2
        assert report.per_stock["BBB"].state is ScanState.FAILED
        assert report.per_stock["AAA"].state is ScanState.READY

    def test_one_stock_kap_failure_partial_others_ready(self):
        collectors = _ok_collectors()
        collectors["kap"] = lambda sid: (_ for _ in ()).throw(RuntimeError("kap yok")) if sid == "AAA" else {"items": 1}
        orchestrator = _make_orchestrator(collectors=collectors)
        report = orchestrator.run_morning_flow(["AAA", "BBB"], now=T0830)
        assert report.counts["PARTIAL_DATA"] == 1
        assert report.counts["READY"] == 1
        assert "source_failed:kap" in report.per_stock["AAA"].partial_reasons

    def test_all_stocks_fail_price_all_failed(self):
        collectors = _ok_collectors()
        collectors["price"] = lambda sid: (_ for _ in ()).throw(RuntimeError("down"))
        orchestrator = _make_orchestrator(collectors=collectors)
        report = orchestrator.run_morning_flow(["AAA", "BBB", "CCC"], now=T0830)
        assert report.counts["FAILED"] == 3
        assert report.counts["READY"] == 0
        assert len(report.errors) == 3

    def test_missing_collector_marks_partial(self):
        collectors = _ok_collectors()
        del collectors["news"]
        orchestrator = _make_orchestrator(collectors=collectors)
        report = orchestrator.run_morning_flow(["AAA"], now=T0830)
        assert report.counts["PARTIAL_DATA"] == 1
        assert "collector_missing:news" in report.per_stock["AAA"].partial_reasons

    def test_missing_all_collectors_all_partial(self):
        orchestrator = _make_orchestrator(collectors={})
        report = orchestrator.run_morning_flow(["AAA", "BBB"], now=T0830)
        assert report.counts["PARTIAL_DATA"] == 2
        reasons = report.per_stock["AAA"].partial_reasons
        assert sorted(reasons) == [
            "collector_missing:actions",
            "collector_missing:kap",
            "collector_missing:news",
            "collector_missing:price",
            "collector_missing:restrictions",
        ]

    def test_collector_exception_never_propagates(self):
        collectors = _ok_collectors()
        collectors["actions"] = lambda sid: (_ for _ in ()).throw(ValueError("bozuk"))
        orchestrator = _make_orchestrator(collectors=collectors)
        report = orchestrator.run_morning_flow(["AAA"], now=T0830)  # firlatmaz
        assert report.counts["PARTIAL_DATA"] == 1

    def test_not_trading_day_flow_does_not_start(self):
        orchestrator = _make_orchestrator()
        report = orchestrator.run_morning_flow(
            ["AAA"], now=datetime(2025, 1, 4, 8, 30, tzinfo=ISTANBUL_TZ)
        )
        assert report.status == NOT_TRADING_DAY
        assert report.run_id is None
        assert report.counts == {}
        assert report.reason == NOT_TRADING_DAY

    def test_not_trading_day_writes_no_run_record(self):
        orchestrator = _make_orchestrator()
        orchestrator.run_morning_flow(
            ["AAA"], now=datetime(2025, 1, 5, 8, 0, tzinfo=ISTANBUL_TZ)
        )
        assert orchestrator.registry.all_runs() == []

    def test_ready_stock_full_state_path(self):
        orchestrator = _make_orchestrator()
        report = orchestrator.run_morning_flow(["AAA"], now=T0830)
        status = report.per_stock["AAA"]
        assert status.state is ScanState.READY
        assert status.history == [
            ScanState.WAITING,
            ScanState.COLLECTING_PRICE,
            ScanState.COLLECTING_KAP,
            ScanState.COLLECTING_NEWS,
            ScanState.COLLECTING_ACTIONS,
            ScanState.COLLECTING_RESTRICTIONS,
            ScanState.VALIDATING,
        ]

    def test_inactive_stocks_skipped_and_counted(self):
        orchestrator = _make_orchestrator()
        report = orchestrator.run_morning_flow(
            ["AAA", "BBB", "CCC"], now=T0830, inactive=["BBB"]
        )
        assert report.counts["INACTIVE"] == 1
        assert report.counts["READY"] == 2
        bbb = report.per_stock["BBB"]
        assert bbb.state is ScanState.INACTIVE
        assert bbb.history == [ScanState.WAITING]  # toplamaya hic girmedi

    def test_failed_stock_error_recorded(self):
        collectors = _ok_collectors()
        collectors["price"] = lambda sid: (_ for _ in ()).throw(RuntimeError("borsa kapali"))
        policies = default_policies()
        # yedek kaynaksiz price politikasi: orijinal hata status.error'a yazilir
        policies["price"] = SourcePolicy(
            source_name="price",
            concurrency_limit=5,
            requests_per_minute=60,
            timeout=10.0,
            retry_count=3,
            backoff=RetryPolicy(max_attempts=3),
        )
        orchestrator = _make_orchestrator(collectors=collectors, policies=policies)
        report = orchestrator.run_morning_flow(["AAA"], now=T0830)
        status = report.per_stock["AAA"]
        assert status.state is ScanState.FAILED
        assert "borsa kapali" in status.error
        assert any("AAA" in e for e in report.errors)

    def test_retry_attempts_counted_on_status(self):
        calls = {"n": 0}

        def flaky(_sid):
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError(f"deneme {calls['n']}")
            return {"close": 5}

        collectors = _ok_collectors()
        collectors["price"] = flaky
        orchestrator = _make_orchestrator(collectors=collectors)
        report = orchestrator.run_morning_flow(["AAA"], now=T0830)
        status = report.per_stock["AAA"]
        assert status.state is ScanState.READY
        # price: 2 basarisiz + 1 basarili = 3; diger 4 kaynak ilk denemede = 4
        assert status.attempts == 7

    def test_fallback_switch_logged_and_stock_ready(self):
        collectors = _ok_collectors()
        collectors["price"] = lambda sid: (_ for _ in ()).throw(RuntimeError("ana kaynak yok"))
        collectors["price_backup"] = lambda sid: {"close": 9.9}
        logger = MemoryLogger()
        orchestrator = _make_orchestrator(collectors=collectors, logger=logger)
        report = orchestrator.run_morning_flow(["AAA"], now=T0830)
        status = report.per_stock["AAA"]
        assert status.state is ScanState.READY  # yedek kaynak verisiyle hazir
        assert len(report.fallback_logs) == 1
        event = report.fallback_logs[0]
        assert event.from_source == "price" and event.to_source == "price_backup"
        assert event.attempts == 3
        assert "ana kaynak yok" in event.reason
        assert any(e == FALLBACK_SWITCHED for e, _ in logger.records)

    def test_fallback_unavailable_marks_failed(self):
        collectors = _ok_collectors()
        collectors["price"] = lambda sid: (_ for _ in ()).throw(RuntimeError("down"))
        orchestrator = _make_orchestrator(collectors=collectors)
        report = orchestrator.run_morning_flow(["AAA"], now=T0830)
        status = report.per_stock["AAA"]
        assert status.state is ScanState.FAILED
        assert "fallback_unavailable:price_backup" in status.error


# =====================================================================
# 4. CIFT RUN_ID (12 test)
# =====================================================================
class TestCiftRunId:
    def _registry(self):
        return RunRegistry(clock=lambda: T0800)

    def test_start_run_format_r1(self):
        registry = self._registry()
        run_id = registry.start_run(MONDAY, trigger="scheduled")
        assert run_id == "2025-01-06-TARAMA-R1"

    def test_new_run_is_active_with_started_at(self):
        registry = self._registry()
        run_id = registry.start_run(MONDAY)
        run = registry.get_run(run_id)
        assert run.status == RUN_ACTIVE
        assert run.started_at == T0800
        assert run.revision == 1
        assert run.parent_run_id is None

    def test_second_start_while_active_rejected(self):
        registry = self._registry()
        registry.start_run(MONDAY)
        with pytest.raises(RunAlreadyActiveError):
            registry.start_run(MONDAY)

    def test_duplicate_attempt_counter_incremented(self):
        registry = self._registry()
        run_id = registry.start_run(MONDAY)
        for _ in range(3):
            with pytest.raises(RunAlreadyActiveError):
                registry.start_run(MONDAY)
        assert registry.get_run(run_id).duplicate_attempts == 3

    def test_duplicate_attempt_writes_no_record(self):
        registry = self._registry()
        registry.start_run(MONDAY)
        with pytest.raises(RunAlreadyActiveError):
            registry.start_run(MONDAY)
        assert len(registry.all_runs()) == 1
        assert registry.latest_run(MONDAY).run_id == "2025-01-06-TARAMA-R1"

    def test_scheduled_restart_after_completion_rejected(self):
        registry = self._registry()
        run_id = registry.start_run(MONDAY)
        registry.complete_run(run_id)
        with pytest.raises(RunAlreadyActiveError):
            registry.start_run(MONDAY, trigger="scheduled")

    def test_scheduled_restart_counts_duplicate_on_latest(self):
        registry = self._registry()
        run_id = registry.start_run(MONDAY)
        registry.complete_run(run_id)
        with pytest.raises(RunAlreadyActiveError):
            registry.start_run(MONDAY, trigger="scheduled")
        assert registry.get_run(run_id).duplicate_attempts == 1

    def test_still_single_record_after_scheduled_restart_attempt(self):
        registry = self._registry()
        registry.start_run(MONDAY)
        registry.complete_run("2025-01-06-TARAMA-R1")
        with pytest.raises(RunAlreadyActiveError):
            registry.start_run(MONDAY, trigger="scheduled")
        assert len(registry.all_runs()) == 1

    def test_complete_run_sets_status_and_time(self):
        registry = self._registry()
        run_id = registry.start_run(MONDAY)
        run = registry.complete_run(run_id)
        assert run.status == RUN_COMPLETED
        assert run.completed_at == T0800
        assert RUN_COMPLETED in run.history

    def test_fail_and_abort_run_statuses(self):
        registry = self._registry()
        r1 = registry.start_run(MONDAY)
        assert registry.fail_run(r1).status == RUN_FAILED
        registry.start_run(MONDAY, trigger="manual")
        assert registry.abort_run("2025-01-06-TARAMA-R2").status == RUN_ABORTED

    def test_complete_run_invalid_status_or_double_complete(self):
        registry = self._registry()
        run_id = registry.start_run(MONDAY)
        with pytest.raises(ValueError):
            registry.complete_run(run_id, status="YARIM")
        registry.complete_run(run_id)
        with pytest.raises(ValueError):
            registry.complete_run(run_id)

    def test_get_and_latest_run_and_unknown_run(self):
        registry = self._registry()
        assert registry.get_run("yok") is None
        assert registry.latest_run(MONDAY) is None
        run_id = registry.start_run(MONDAY)
        assert registry.latest_run(MONDAY).run_id == run_id
        with pytest.raises(RunNotFoundError):
            registry.complete_run("bilinmeyen-run")


# =====================================================================
# 5. R2 OLUSTURMA (12 test)
# =====================================================================
class TestR2Olusturma:
    def _registry_with_completed_r1(self):
        registry = RunRegistry(clock=lambda: T0800)
        r1 = registry.start_run(MONDAY)
        registry.complete_run(r1)
        return registry, r1

    def test_manual_rescan_creates_r2(self):
        registry, _ = self._registry_with_completed_r1()
        r2 = registry.start_run(MONDAY, trigger="manual")
        assert r2 == "2025-01-06-TARAMA-R2"

    def test_r2_parent_run_id_links_r1(self):
        registry, r1 = self._registry_with_completed_r1()
        r2 = registry.start_run(MONDAY, trigger="manual")
        assert registry.get_run(r2).parent_run_id == r1

    def test_r2_revision_and_r1_untouched(self):
        registry, r1 = self._registry_with_completed_r1()
        r2 = registry.start_run(MONDAY, trigger="manual")
        assert registry.get_run(r2).revision == 2
        assert registry.get_run(r1).status == RUN_COMPLETED
        assert registry.get_run(r2).status == RUN_ACTIVE

    def test_r3_chain_after_r2_completed(self):
        registry, r1 = self._registry_with_completed_r1()
        r2 = registry.start_run(MONDAY, trigger="manual")
        registry.complete_run(r2)
        r3 = registry.start_run(MONDAY, trigger="admin")
        assert r3 == "2025-01-06-TARAMA-R3"
        assert registry.get_run(r3).parent_run_id == r2
        assert registry.latest_run(MONDAY).run_id == r3

    def test_no_r2_while_previous_run_active(self):
        registry = RunRegistry(clock=lambda: T0800)
        registry.start_run(MONDAY)
        with pytest.raises(RunAlreadyActiveError):
            registry.start_run(MONDAY, trigger="manual")
        assert len(registry.all_runs()) == 1

    def test_no_rescan_when_latest_aborted(self):
        registry = RunRegistry(clock=lambda: T0800)
        r1 = registry.start_run(MONDAY)
        registry.abort_run(r1)
        with pytest.raises(RescanNotAllowedError):
            registry.start_run(MONDAY, trigger="manual")

    def test_rescan_allowed_after_failed_run(self):
        registry = RunRegistry(clock=lambda: T0800)
        r1 = registry.start_run(MONDAY)
        registry.fail_run(r1)
        r2 = registry.start_run(MONDAY, trigger="manual")
        assert r2.endswith("-R2")
        assert registry.get_run(r2).parent_run_id == r1

    def test_scheduled_trigger_cannot_create_r2(self):
        registry, _ = self._registry_with_completed_r1()
        with pytest.raises(RunAlreadyActiveError):
            registry.start_run(MONDAY, trigger="scheduled")
        assert len(registry.all_runs()) == 1

    def test_all_rescan_triggers_allowed(self):
        for trigger in ("manual", "admin", "rescan", "critical_rescan"):
            registry = RunRegistry(clock=lambda: T0800)
            r1 = registry.start_run(MONDAY)
            registry.complete_run(r1)
            r2 = registry.start_run(MONDAY, trigger=trigger)
            assert r2.endswith("-R2"), trigger

    def test_orchestrator_critical_rescan_creates_r2_with_parent(self):
        orchestrator = _make_orchestrator()
        report = orchestrator.run_morning_flow(["AAA"], now=T0830)
        rescan = orchestrator.critical_rescan(["AAA"], "kritik KAP haberi", now=T0830)
        assert rescan.run_id == "2025-01-06-TARAMA-R2"
        run = orchestrator.registry.get_run(rescan.run_id)
        assert run.parent_run_id == report.run_id
        assert run.trigger == "critical_rescan"

    def test_critical_rescan_failed_stock_goes_waiting_then_ready(self):
        calls = {"fail": True}

        def price(sid):
            if calls["fail"]:
                raise RuntimeError("price down")
            return {"close": 3.3}

        collectors = _ok_collectors()
        collectors["price"] = price
        orchestrator = _make_orchestrator(collectors=collectors)
        report = orchestrator.run_morning_flow(["AAA"], now=T0830)
        assert report.per_stock["AAA"].state is ScanState.FAILED
        calls["fail"] = False  # kaynak duzeldi
        rescan = orchestrator.critical_rescan(["AAA"], "kaynak duzeldi", now=T0830)
        status = rescan.per_stock["AAA"]
        assert status.state is ScanState.READY
        # FAILED -> WAITING gecisi bilincli yeniden tarama ile yapildi
        assert ScanState.FAILED in status.history
        assert ScanState.WAITING in status.history

    def test_morning_flow_critical_events_trigger_rescan_wave(self):
        orchestrator = _make_orchestrator()
        report = orchestrator.run_morning_flow(
            ["AAA", "BBB", "CCC"],
            now=T0830,
            critical_events={"AAA": "islem durdurma", "BBB": "islem durdurma", "ZZZ": "yok"},
        )
        assert report.rescan_report is not None
        assert report.rescan_report.run_id.endswith("-TARAMA-R2")
        assert report.rescan_report.universe_size == 2  # ZZZ evrende yok
        assert set(report.rescan_report.per_stock.keys()) == {"AAA", "BBB"}
        assert report.rescan_report.reason == "islem durdurma"


# =====================================================================
# 6. DURUM GECISLERI (16 test)
# =====================================================================
class TestDurumGecisleri:
    def test_scan_state_has_exactly_11_members(self):
        assert len(ScanState) == 11

    def test_scan_state_names_exact(self):
        assert [s.value for s in ScanState] == [
            "WAITING",
            "COLLECTING_PRICE",
            "COLLECTING_KAP",
            "COLLECTING_NEWS",
            "COLLECTING_ACTIONS",
            "COLLECTING_RESTRICTIONS",
            "VALIDATING",
            "READY",
            "PARTIAL_DATA",
            "FAILED",
            "INACTIVE",
        ]

    def test_transitions_table_covers_all_states(self):
        assert set(TRANSITIONS.keys()) == set(ScanState)

    def test_waiting_to_all_collecting_states(self):
        for target in (
            ScanState.COLLECTING_PRICE,
            ScanState.COLLECTING_KAP,
            ScanState.COLLECTING_NEWS,
            ScanState.COLLECTING_ACTIONS,
            ScanState.COLLECTING_RESTRICTIONS,
        ):
            assert can_transition(ScanState.WAITING, target) is True

    def test_collecting_chain_allowed(self):
        chain = [
            ScanState.COLLECTING_PRICE,
            ScanState.COLLECTING_KAP,
            ScanState.COLLECTING_NEWS,
            ScanState.COLLECTING_ACTIONS,
            ScanState.COLLECTING_RESTRICTIONS,
        ]
        for a, b in zip(chain, chain[1:]):
            assert can_transition(a, b) is True

    def test_collecting_to_terminal_paths(self):
        for source in (
            ScanState.COLLECTING_PRICE,
            ScanState.COLLECTING_KAP,
            ScanState.COLLECTING_NEWS,
            ScanState.COLLECTING_ACTIONS,
            ScanState.COLLECTING_RESTRICTIONS,
        ):
            for target in (ScanState.VALIDATING, ScanState.PARTIAL_DATA, ScanState.FAILED):
                assert can_transition(source, target) is True

    def test_validating_to_ready_partial_failed(self):
        for target in (ScanState.READY, ScanState.PARTIAL_DATA, ScanState.FAILED):
            assert can_transition(ScanState.VALIDATING, target) is True

    def test_partial_data_recovery_paths(self):
        assert can_transition(ScanState.PARTIAL_DATA, ScanState.VALIDATING) is True
        assert can_transition(ScanState.PARTIAL_DATA, ScanState.READY) is True
        assert can_transition(ScanState.PARTIAL_DATA, ScanState.WAITING) is False

    def test_failed_to_waiting_with_conscious_rescan(self):
        assert (
            can_transition(
                ScanState.FAILED, ScanState.WAITING, reason=CONSCIOUS_RESCAN_REASON
            )
            is True
        )

    def test_failed_to_waiting_without_reason_rejected(self):
        status = StockScanStatus("AAA", state=ScanState.FAILED)
        with pytest.raises(InvalidTransitionError):
            status.transition(ScanState.WAITING)
        assert can_transition(ScanState.FAILED, ScanState.WAITING) is False

    def test_inactive_cannot_enter_any_collecting(self):
        for target in (
            ScanState.COLLECTING_PRICE,
            ScanState.COLLECTING_KAP,
            ScanState.COLLECTING_NEWS,
            ScanState.COLLECTING_ACTIONS,
            ScanState.COLLECTING_RESTRICTIONS,
        ):
            assert can_transition(ScanState.INACTIVE, target) is False
            with pytest.raises(InvalidTransitionError):
                assert_transition(ScanState.INACTIVE, target)

    def test_inactive_has_no_outgoing_transitions(self):
        assert TRANSITIONS[ScanState.INACTIVE] == frozenset()
        for target in ScanState:
            assert can_transition(ScanState.INACTIVE, target) is False

    def test_ready_is_terminal(self):
        for target in ScanState:
            assert can_transition(ScanState.READY, target) is False

    def test_waiting_to_ready_directly_rejected(self):
        assert can_transition(ScanState.WAITING, ScanState.READY) is False
        assert can_transition(ScanState.WAITING, ScanState.VALIDATING) is False
        with pytest.raises(InvalidTransitionError):
            assert_transition(ScanState.WAITING, ScanState.READY)

    def test_status_transition_records_history_time_error(self):
        status = StockScanStatus("AAA")
        status.transition(ScanState.COLLECTING_PRICE, at=T0830)
        status.transition(ScanState.FAILED, at=T0830, error="kaynak yok")
        assert status.history == [ScanState.WAITING, ScanState.COLLECTING_PRICE]
        assert status.updated_at == T0830
        assert status.error == "kaynak yok"
        assert status.is_terminal is True

    def test_invalid_transition_error_carries_states(self):
        status = StockScanStatus("AAA")
        try:
            status.transition(ScanState.READY)
        except InvalidTransitionError as exc:
            assert exc.from_state is ScanState.WAITING
            assert exc.to_state is ScanState.READY
        else:
            pytest.fail("InvalidTransitionError firlatilmadi")
        assert status.state is ScanState.WAITING  # durum degismedi


# =====================================================================
# 7. RETRY / BACKOFF (10 test)
# =====================================================================
class TestRetryBackoff:
    def test_attempt_plan_immediate_30_90(self):
        policy = RetryPolicy()
        times = policy.attempt_times(T0800)
        assert times == [
            T0800,
            T0800 + timedelta(seconds=30),
            T0800 + timedelta(seconds=120),  # 30 + 90 kumulatif
        ]

    def test_planned_times_are_datetimes_no_sleep(self):
        policy = RetryPolicy()
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            return "ok"

        outcome = policy.execute(fn, start=T0800)
        assert outcome.ok is True
        assert calls["n"] == 1
        assert outcome.attempt_times == [T0800]  # planlanan zaman donduruldu

    def test_next_attempt_time_bounds(self):
        policy = RetryPolicy()
        assert policy.next_attempt_time(T0800, 1) == T0800
        assert policy.next_attempt_time(T0800, 2) == T0800 + timedelta(seconds=30)
        assert policy.next_attempt_time(T0800, 3) == T0800 + timedelta(seconds=120)
        assert policy.next_attempt_time(T0800, 4) is None
        assert policy.next_attempt_time(T0800, 0) is None

    def test_should_retry_and_exceeded(self):
        policy = RetryPolicy(max_attempts=3)
        assert policy.should_retry(0) is True
        assert policy.should_retry(2) is True
        assert policy.should_retry(3) is False
        assert policy.exceeded(3) is True
        assert policy.exceeded(1) is False

    def test_execute_success_first_try(self):
        outcome = RetryPolicy().execute(lambda: 42, start=T0800)
        assert outcome.ok is True
        assert outcome.value == 42
        assert outcome.attempts == 1

    def test_execute_two_failures_then_success(self):
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("gecici")
            return "ok"

        outcome = RetryPolicy().execute(fn, start=T0800)
        assert outcome.ok is True
        assert outcome.attempts == 3

    def test_execute_all_fail_no_fallback(self):
        def fn():
            raise RuntimeError("kalici")

        outcome = RetryPolicy().execute(fn, start=T0800)
        assert outcome.ok is False
        assert outcome.attempts == 3
        assert "kalici" in outcome.error
        assert outcome.fallback_event is None
        assert len(outcome.attempt_times) == 3

    def test_fallback_event_and_log_on_exhaustion(self):
        logger = MemoryLogger()
        policy = RetryPolicy(fallback_source="price_backup")

        def fn():
            raise RuntimeError("ana kaynak yok")

        outcome = policy.execute(fn, start=T0800, source_name="price", logger=logger, at=T0830)
        assert outcome.ok is False
        event = outcome.fallback_event
        assert event.from_source == "price"
        assert event.to_source == "price_backup"
        assert event.attempts == 3
        assert "ana kaynak yok" in event.reason
        assert (FALLBACK_SWITCHED, {
            "from_source": "price",
            "to_source": "price_backup",
            "reason": "RuntimeError: ana kaynak yok",
            "attempts": 3,
        }) in logger.records

    def test_switch_fallback_without_fallback_source_raises(self):
        policy = RetryPolicy()
        with pytest.raises(ValueError):
            policy.switch_fallback("price", "hata", 3)

    def test_policy_validation(self):
        with pytest.raises(ValueError):
            RetryPolicy(max_attempts=0)
        with pytest.raises(ValueError):
            RetryPolicy(max_attempts=4, delays=(0, 30, 90))  # delays kisa


# =====================================================================
# 8. KAYNAK POLITIKASI (6 test)
# =====================================================================
class TestKaynakPolitikasi:
    def test_default_policies_exact_values(self):
        policies = default_policies()
        assert set(policies) == {"price", "kap", "news", "actions", "restrictions"}
        expected = {
            "price": (5, 60, 10.0, 3),
            "kap": (2, 30, 15.0, 3),
            "news": (4, 40, 10.0, 3),
            "actions": (2, 20, 10.0, 3),
            "restrictions": (2, 20, 10.0, 3),
        }
        for name, (conc, rpm, timeout, retries) in expected.items():
            p = policies[name]
            assert p.source_name == name
            assert (p.concurrency_limit, p.requests_per_minute, p.timeout, p.retry_count) == (
                conc,
                rpm,
                timeout,
                retries,
            )
            assert isinstance(p.backoff, RetryPolicy)

    def test_source_policy_validation(self):
        with pytest.raises(ValueError):
            SourcePolicy("x", concurrency_limit=0, requests_per_minute=10, timeout=5)
        with pytest.raises(ValueError):
            SourcePolicy("x", concurrency_limit=1, requests_per_minute=0, timeout=5)
        with pytest.raises(ValueError):
            SourcePolicy("x", concurrency_limit=1, requests_per_minute=10, timeout=0)
        with pytest.raises(ValueError):
            SourcePolicy("x", concurrency_limit=1, requests_per_minute=10, timeout=5, retry_count=0)

    def test_rate_limiter_allows_up_to_rpm(self):
        clock = lambda: T0800
        limiter = RateLimiter(requests_per_minute=3, clock=clock)
        results = [limiter.acquire() for _ in range(3)]
        assert all(r.allowed and not r.waited for r in results)
        assert limiter.allowed_count == 3
        assert limiter.waited_count == 0
        assert limiter.usage() == 3

    def test_rate_limiter_queues_over_limit_virtual_wait(self):
        clock = lambda: T0800
        limiter = RateLimiter(requests_per_minute=2, clock=clock)
        limiter.acquire()
        limiter.acquire()
        third = limiter.acquire()
        assert third.allowed is True
        assert third.waited is True
        assert third.wait_seconds == 60.0  # en eski damga 60sn sonra dolar
        assert limiter.waited_count == 1
        assert limiter.virtual_wait_total == 60.0

    def test_rate_limiter_window_slides_with_injected_clock(self):
        now = {"t": T0800}
        limiter = RateLimiter(requests_per_minute=2, clock=lambda: now["t"])
        limiter.acquire()
        limiter.acquire()
        assert limiter.acquire().waited is True
        now["t"] = T0800 + timedelta(seconds=61)  # pencere kaydi
        result = limiter.acquire()
        assert result.waited is False
        # kuyruklanan istegin sanal damgasi (t0+60) hala pencerede + yeni istek
        assert limiter.usage() == 2
        now["t"] = T0800 + timedelta(seconds=121)  # tum damgalar dustu
        assert limiter.usage() == 0

    def test_rate_limiter_uses_injected_clock_deterministically(self):
        stamps = []

        class Clock:
            def __call__(self):
                return T0800 + timedelta(seconds=len(stamps))

        limiter = RateLimiter(requests_per_minute=60, clock=Clock())
        for _ in range(5):
            stamps.append(1)
            limiter.acquire()
        # tum damgalar enjekte saatten geldi, pencere icinde -> bekleme yok
        assert limiter.waited_count == 0
        assert limiter.allowed_count == 5
        assert limiter.usage() == 5
