"""BLOK 14 - Zamanlama, Paralellik ve Durum Makinesi paketi.

Moduller:
- schedule: ScanSchedule (8 dilim), Phase, Europe/Istanbul sabit tz,
  is_trading_day (hafta sonu + enjekte tatil), current_phase, DATA_CUTOFF 09:40.
- states: ScanState (TAM 11), TRANSITIONS gecis tablosu,
  InvalidTransitionError, StockScanStatus.
- limits: SourcePolicy (concurrency/rpm/timeout/retry/backoff),
  varsayilan politikalar, RateLimiter (rpm kovasi, enjekte saat).
- retry: RetryPolicy (hemen/+30sn/+90sn plani, gercek bekleme YOK),
  yedek kaynak gecisi + FALLBACK_SWITCHED logu.
- pool: ControlledPool (max_workers sinirli, gorev izolasyonu,
  use_threads=False deterministik mod, wait_all).
- runs: RunRegistry (run_id idempotency, R1/R2 surumleri,
  duplicate_attempts, ACTIVE/COMPLETED/FAILED/ABORTED).
- orchestrator: ScanOrchestrator (asamali sabah akisi, hata izolasyonu,
  CRITICAL_RESCAN dalgasi, FlowReport).

stdlib only; deterministik (saat enjekte); gercek ag YOK; gercek bekleme YOK.
"""
from app.services.stock_scanning.orchestration.limits import (
    AcquireResult,
    RateLimiter,
    SourcePolicy,
    default_policies,
)
from app.services.stock_scanning.orchestration.orchestrator import (
    COLLECTION_SOURCES,
    FlowReport,
    MemoryLogger,
    PoolLimitExceededError,
    ScanOrchestrator,
)
from app.services.stock_scanning.orchestration.pool import (
    ControlledPool,
    PoolReport,
    PoolTask,
    TaskResult,
)
from app.services.stock_scanning.orchestration.retry import (
    FALLBACK_SWITCHED,
    FallbackEvent,
    RetryOutcome,
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
    ScanRun,
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

__all__ = [
    "AcquireResult",
    "COLLECTION_SOURCES",
    "CONSCIOUS_RESCAN_REASON",
    "ControlledPool",
    "DATA_CUTOFF_TIME",
    "FALLBACK_SWITCHED",
    "FallbackEvent",
    "FlowReport",
    "ISTANBUL_TZ",
    "InvalidTransitionError",
    "MemoryLogger",
    "NOT_TRADING_DAY",
    "OUTSIDE_SCHEDULE",
    "Phase",
    "PhaseWindow",
    "PoolLimitExceededError",
    "PoolReport",
    "PoolTask",
    "RateLimiter",
    "RescanNotAllowedError",
    "RetryOutcome",
    "RetryPolicy",
    "RUN_ABORTED",
    "RUN_ACTIVE",
    "RUN_COMPLETED",
    "RUN_FAILED",
    "RunAlreadyActiveError",
    "RunNotFoundError",
    "RunRegistry",
    "ScanOrchestrator",
    "ScanRun",
    "ScanSchedule",
    "ScanState",
    "SourcePolicy",
    "StockScanStatus",
    "TaskResult",
    "TRANSITIONS",
    "assert_transition",
    "can_transition",
    "default_policies",
]
