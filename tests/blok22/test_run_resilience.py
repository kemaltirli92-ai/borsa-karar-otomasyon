"""BLOK 22 - test_run_resilience: run dayanikliligi kabul testleri (11 test).

Kapsam: ayni run_id: RunAlreadyActiveError / idempotent, R2 kurali (2);
hata izolasyonu: 1 sembol patlar, 99 devam + sayaclar (2); VPS restart:
ACTIVE->ABORTED + cift tarama engeli + yayin korunur (3); 09:35:
durations toplamiyla finish<=09:35 True + asimda False (2); gunler
arasi bagimsizlik: farkli gun kendi R1'i + 09:35 tam sinir degeri (2).
GERCEK BLOK 14/21 modulleri + StagingRunner kullanilir.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.acceptance.staging import STATE_FAILED, STATE_READY, StagingRunner
from app.ops.recovery import (
    ABORT_REASON_VPS_RESTART,
    BootRecovery,
    FileRunStateStore,
    PublishedStore,
)
from app.services.stock_scanning.orchestration.pool import ControlledPool
from app.services.stock_scanning.orchestration.runs import (
    RUN_COMPLETED,
    RunAlreadyActiveError,
    RunRegistry,
)
from tests.blok22.conftest import (
    FIXED_NOW,
    make_universe,
    price_series,
    universe_symbols,
)

DAY = "2025-06-03"
FIXED = datetime(2025, 6, 3, 8, 0, 0, tzinfo=timezone.utc)


# 1) ayni run_id: idempotens + R2 kurali ------------------------------------------
def test_same_run_id_second_start_raises():
    registry = RunRegistry(clock=lambda: FIXED_NOW)
    run_id = registry.start_run(DAY, trigger="scheduled")
    assert run_id == f"{DAY}-TARAMA-R1"
    with pytest.raises(RunAlreadyActiveError):
        registry.start_run(DAY, trigger="scheduled")


def test_rescan_after_completion_gets_r2():
    registry = RunRegistry(clock=lambda: FIXED_NOW)
    run_id = registry.start_run(DAY, trigger="scheduled")
    registry.complete_run(run_id, RUN_COMPLETED)
    r2 = registry.start_run(DAY, trigger="manual")
    assert r2 == f"{DAY}-TARAMA-R2"  # bilincli yeniden tarama: R2


# 2) hata izolasyonu ----------------------------------------------------------------
def test_pool_error_isolation_one_fails_others_continue():
    pool = ControlledPool(max_workers=4, use_threads=False)
    for i in range(100):
        if i == 42:
            pool.submit(f"s{i:03d}", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        else:
            pool.submit(f"s{i:03d}", lambda i=i: i)
    pool.start()  # blok14 kalibi: submit -> start -> wait_all
    completed, failed, timed_out = pool.wait_all(timeout=10)
    # blok14: wait_all donus degerleri int sayaclardir
    assert completed == 99   # 99 devam etti
    assert failed == 1       # 1 sembol patladi
    assert timed_out == 0


def test_staging_fail_symbol_isolated_counts():
    book = make_universe(identity_factory(), universe_symbols(100))
    runner = StagingRunner(
        book,
        _fetchers(price=price_series("X007", DAY)),
        fail_symbols={"X007"},
    )
    report = runner.run(DAY)
    assert report.failed == 1
    assert report.ready == 99
    assert report.missing_total == 0
    failed = [r for r in report.results if r.state == STATE_FAILED]
    assert [r.symbol for r in failed] == ["X007"]
    others = [r for r in report.results if r.symbol != "X007"]
    assert all(r.state == STATE_READY for r in others)


# 3) VPS restart guvenligi ------------------------------------------------------------
def test_vps_restart_active_run_aborted(tmp_path):
    store = FileRunStateStore(str(tmp_path / "runs.json"), clock=lambda: FIXED)
    store.upsert("run-1", "ACTIVE", {"day": DAY, "revision": 1})
    report = BootRecovery(store, clock=lambda: FIXED).recover()
    assert report["aborted"] == ["run-1"]
    run = [r for r in store.list_runs() if r["run_id"] == "run-1"][0]
    assert run["status"] == "ABORTED"
    assert run["reason"] == ABORT_REASON_VPS_RESTART


def test_vps_restart_double_scan_prevented(tmp_path):
    store = FileRunStateStore(str(tmp_path / "runs.json"), clock=lambda: FIXED)
    store.upsert("run-1", "COMPLETED", {"day": DAY, "revision": 1})
    recovery = BootRecovery(store, clock=lambda: FIXED)
    assert recovery.should_start_scan(DAY, revision=1) is False  # cift tarama YOK
    assert recovery.should_start_scan("2025-06-04", revision=1) is True


def test_vps_restart_published_envelope_preserved(tmp_path):
    path = str(tmp_path / "published.json")
    PublishedStore(path).save({"day": DAY, "status": "PUBLISHED", "items": 100})
    # restart sonrasi yayinlanmis paket korunur
    restored = PublishedStore(path).load_last()
    assert restored == {"day": DAY, "status": "PUBLISHED", "items": 100}


# 4) 09:35 bitis kurali ---------------------------------------------------------------
def identity_factory():
    from app.services.stock_scanning.symbol_identity import SymbolIdentityService

    return SymbolIdentityService(clock=lambda: FIXED_NOW)


def _fetchers(price=None):
    bars = price if price is not None else price_series("X001", DAY)
    return {
        "price": lambda symbol: price_series(symbol, DAY),
        "volume": lambda symbol: [1000, 1000, 1000],
        "kap": lambda symbol: [],
        "news": lambda symbol: [],
        "actions": lambda symbol: [],
        "restrictions": lambda symbol: [],
    }


def test_finish_by_0935_true_with_normal_durations():
    book = make_universe(identity_factory(), universe_symbols(100))
    runner = StagingRunner(
        book, _fetchers(), durations={"per_symbol_seconds": 3.0}
    )
    report = runner.run(DAY)
    # 08:00 + 100*3sn = 08:05 -> 09:35'ten once
    assert report.finish_by_0935 is True
    assert report.finished_at == f"{DAY}T08:05:00"


def test_finish_by_0935_false_on_overrun():
    book = make_universe(identity_factory(), universe_symbols(100))
    runner = StagingRunner(
        book, _fetchers(), durations={"per_symbol_seconds": 120.0}
    )
    report = runner.run(DAY)
    # 08:00 + 100*120sn = 11:20 -> 09:35 ASIMI
    assert report.finish_by_0935 is False


# 5) gunler arasi bagimsizlik + 09:35 tam sinir degeri ----------------------------------
def test_different_day_run_gets_own_r1():
    registry = RunRegistry(clock=lambda: FIXED_NOW)
    r1 = registry.start_run(DAY, trigger="scheduled")
    assert r1 == f"{DAY}-TARAMA-R1"
    # ayni gun aktifken BASKA gunun run'i bagimsiz acilir (kendi R1'i)
    r_next = registry.start_run("2025-06-04", trigger="scheduled")
    assert r_next == "2025-06-04-TARAMA-R1"


def test_finish_by_0935_boundary_exactly_0935_true():
    book = make_universe(identity_factory(), universe_symbols(100))
    runner = StagingRunner(
        book, _fetchers(), durations={"per_symbol_seconds": 57.0}
    )
    report = runner.run(DAY)
    # 08:00 + 100*57sn = 09:35:00 tam sinirda -> <= kurali True
    assert report.finished_at == f"{DAY}T09:35:00"
    assert report.finish_by_0935 is True
