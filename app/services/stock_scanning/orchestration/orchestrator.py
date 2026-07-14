"""BLOK 14 - ScanOrchestrator: asamali sabah akisi.

- run_morning_flow(universe): PRECHECK (islem gunu degilse baslamaz,
  NOT_TRADING_DAY), hisse basina WAITING -> COLLECTING_* -> VALIDATING ->
  READY/PARTIAL_DATA/FAILED.
- collectors dict enjekte: {"price","kap","news","actions","restrictions"}.
  Eksik collector -> PARTIAL_DATA (collector_missing nedeni).
- Hata izolasyonu: bir hisse patlarsa diger hisseler devam eder.
- Retry + yedek kaynak: SourcePolicy.backoff + FALLBACK_SWITCHED logu.
- DATA_CUTOFF sonrasi kritik olay listesi -> CRITICAL_RESCAN dalgasi (R2).
- critical_rescan(stock_ids, reason): bilincli yeniden tarama (R-surumu).

stdlib only; deterministik (saat enjekte); gercek ag YOK; gercek bekleme YOK.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence

from app.services.stock_scanning.orchestration.limits import (
    SourcePolicy,
    default_policies,
)
from app.services.stock_scanning.orchestration.pool import ControlledPool
from app.services.stock_scanning.orchestration.retry import FallbackEvent
from app.services.stock_scanning.orchestration.runs import (
    RUN_COMPLETED,
    RunRegistry,
)
from app.services.stock_scanning.orchestration.schedule import (
    NOT_TRADING_DAY,
    ScanSchedule,
)
from app.services.stock_scanning.orchestration.states import (
    CONSCIOUS_RESCAN_REASON,
    ScanState,
    StockScanStatus,
)

# Toplama kaynaklari sirasi (5 asama).
COLLECTION_SOURCES: Sequence[str] = ("price", "kap", "news", "actions", "restrictions")

COLLECTING_STATE: Dict[str, ScanState] = {
    "price": ScanState.COLLECTING_PRICE,
    "kap": ScanState.COLLECTING_KAP,
    "news": ScanState.COLLECTING_NEWS,
    "actions": ScanState.COLLECTING_ACTIONS,
    "restrictions": ScanState.COLLECTING_RESTRICTIONS,
}

# Fiyat verisi kritik: basarisizsa hisse FAILED, diger kaynaklar kismi veri.
CRITICAL_SOURCES = frozenset({"price"})

FLOW_COMPLETED = "COMPLETED"


class PoolLimitExceededError(Exception):
    """pool_factory concurrency_limit'i asan havuz dondurdu."""


class MemoryLogger:
    """Test dostu bellek loggeri (yapisal kayit + mesaj)."""

    def __init__(self) -> None:
        self.records: List[tuple] = []  # (event, fields)
        self.messages: List[tuple] = []  # (level, message)

    def record(self, event: str, **fields: Any) -> None:
        self.records.append((event, dict(fields)))

    def info(self, msg: str, *args: Any) -> None:
        self.messages.append(("info", msg % args if args else msg))

    def warning(self, msg: str, *args: Any) -> None:
        self.messages.append(("warning", msg % args if args else msg))

    def error(self, msg: str, *args: Any) -> None:
        self.messages.append(("error", msg % args if args else msg))


@dataclass
class FlowReport:
    """Bir akisin ozet raporu."""

    run_id: Optional[str]
    status: str
    per_stock: Dict[str, StockScanStatus] = field(default_factory=dict)
    counts: Dict[str, int] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    fallback_logs: List[FallbackEvent] = field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    universe_size: int = 0
    reason: Optional[str] = None
    rescan_report: Optional["FlowReport"] = None

    @property
    def ready(self) -> int:
        return self.counts.get(ScanState.READY.value, 0)

    @property
    def partial(self) -> int:
        return self.counts.get(ScanState.PARTIAL_DATA.value, 0)

    @property
    def failed(self) -> int:
        return self.counts.get(ScanState.FAILED.value, 0)

    @property
    def inactive(self) -> int:
        return self.counts.get(ScanState.INACTIVE.value, 0)


class ScanOrchestrator:
    """Asamali sabah tarama akisi + hisse bazli durum takibi."""

    def __init__(
        self,
        schedule: Optional[ScanSchedule] = None,
        registry: Optional[RunRegistry] = None,
        policies: Optional[Dict[str, SourcePolicy]] = None,
        pool_factory: Optional[Callable[[SourcePolicy], ControlledPool]] = None,
        collectors: Optional[Dict[str, Callable[[str], Any]]] = None,
        logger: Optional[Any] = None,
        clock: Optional[Callable[[], datetime]] = None,
        use_threads: bool = False,
    ) -> None:
        self.clock = clock or datetime.now
        self.schedule = schedule or ScanSchedule()
        self.registry = registry or RunRegistry(clock=self.clock)
        self.policies = policies or default_policies()
        self.collectors: Dict[str, Callable[[str], Any]] = dict(collectors or {})
        self.logger = logger or MemoryLogger()
        self.use_threads = use_threads
        if pool_factory is not None:
            self.pool_factory = pool_factory
        else:
            self.pool_factory = lambda policy: ControlledPool.for_policy(
                policy, use_threads=self.use_threads
            )
        self.statuses: Dict[str, StockScanStatus] = {}

    # --- yardimcilar --------------------------------------------------
    def _now(self) -> datetime:
        return self.clock()

    def _policy_for(self, source: str) -> SourcePolicy:
        policy = self.policies.get(source)
        if policy is None:
            policy = SourcePolicy(
                source_name=source,
                concurrency_limit=1,
                requests_per_minute=60,
                timeout=10.0,
            )
        return policy

    def _phase_label(self, now: datetime) -> str:
        phase = self.schedule.current_phase(now)
        return phase.value if hasattr(phase, "value") else str(phase)

    # --- ana akis ------------------------------------------------------
    def run_morning_flow(
        self,
        universe: Sequence[str],
        *,
        now: Optional[datetime] = None,
        inactive: Optional[Sequence[str]] = None,
        critical_events: Optional[Dict[str, str]] = None,
    ) -> FlowReport:
        """Sabah akisi: PRECHECK -> toplama dalgalari -> kapanis (+ R2 dalgasi)."""
        now = now or self._now()
        started_at = now
        universe = list(universe)

        # PRECHECK: islem gunu degilse baslamaz, run kaydi acilmaz.
        if not self.schedule.is_trading_day(now):
            self.logger.info("PRECHECK reddedildi: %s", NOT_TRADING_DAY)
            return FlowReport(
                run_id=None,
                status=NOT_TRADING_DAY,
                counts={},
                started_at=started_at,
                completed_at=now,
                universe_size=len(universe),
                reason=NOT_TRADING_DAY,
            )

        run_id = self.registry.start_run(now.date(), trigger="scheduled")
        report = FlowReport(
            run_id=run_id,
            status=FLOW_COMPLETED,
            started_at=started_at,
            universe_size=len(universe),
        )
        phase_label = self._phase_label(now)
        inactive_set = set(inactive or [])

        # Her hisse WAITING'den baslar (yeni run surumu: taze durum).
        for stock_id in universe:
            status = StockScanStatus(
                stock_id=stock_id,
                state=ScanState.WAITING,
                phase=phase_label,
                updated_at=now,
            )
            self.statuses[stock_id] = status
            if stock_id in inactive_set:
                status.transition(ScanState.INACTIVE, at=now)

        active_ids = [s for s in universe if s not in inactive_set]
        inactive_ids = [s for s in universe if s in inactive_set]
        self._run_collection_waves(active_ids, now, report)
        self._finalize(active_ids, now, report, inactive_ids=inactive_ids)

        self.registry.complete_run(run_id, RUN_COMPLETED)
        report.completed_at = now

        # DATA_CUTOFF sonrasi kritik olay dalgasi (CRITICAL_RESCAN, R-surumu).
        if critical_events:
            rescan_ids = [s for s in critical_events if s in universe]
            if rescan_ids:
                reason = "; ".join(sorted({critical_events[s] for s in rescan_ids}))
                report.rescan_report = self.critical_rescan(rescan_ids, reason, now=now)
        return report

    # --- toplama dalgalari ---------------------------------------------
    def _run_collection_waves(
        self,
        stock_ids: Sequence[str],
        now: datetime,
        report: FlowReport,
    ) -> Dict[str, Dict[str, List[str]]]:
        """Kaynak bazli dalgalar: her dalga kendi sinirli havuzunda."""
        outcomes: Dict[str, Dict[str, List[str]]] = {
            s: {"ok": [], "missing": [], "failed": []} for s in stock_ids
        }
        for source in COLLECTION_SOURCES:
            eligible = [
                s
                for s in stock_ids
                if not self.statuses[s].is_terminal
                and self.statuses[s].state is not ScanState.INACTIVE
            ]
            if not eligible:
                continue
            policy = self._policy_for(source)
            pool = self.pool_factory(policy)
            if pool.exceeds(policy):
                raise PoolLimitExceededError(
                    f"pool max_workers={pool.max_workers} > "
                    f"concurrency_limit={policy.concurrency_limit} ({source})"
                )
            for stock_id in eligible:
                pool.submit(
                    stock_id,
                    lambda sid=stock_id, src=source: self._collect_one(
                        sid, src, now, report, outcomes
                    ),
                )
            pool.start()
            pool.wait_all(timeout=None)
        return outcomes

    def _collect_one(
        self,
        stock_id: str,
        source: str,
        now: datetime,
        report: FlowReport,
        outcomes: Dict[str, Dict[str, List[str]]],
    ) -> None:
        """Tek hisse x tek kaynak: retry + yedek kaynak + izolasyon."""
        status = self.statuses[stock_id]
        status.transition(COLLECTING_STATE[source], at=now)
        status.phase = source
        collector = self.collectors.get(source)
        if collector is None:
            status.partial_reasons.append(f"collector_missing:{source}")
            outcomes[stock_id]["missing"].append(source)
            return

        policy = self._policy_for(source)
        outcome = policy.backoff.execute(
            lambda: collector(stock_id),
            start=now,
            source_name=source,
            logger=self.logger,
            at=now,
        )
        status.attempts += outcome.attempts
        if outcome.ok:
            status.source_used = source
            outcomes[stock_id]["ok"].append(source)
            return

        # Deneme asimi: yedek kaynak denemesi.
        if outcome.fallback_event is not None:
            report.fallback_logs.append(outcome.fallback_event)
            fallback_name = outcome.fallback_event.to_source
            fallback_collector = self.collectors.get(fallback_name)
            if fallback_collector is not None:
                try:
                    fallback_collector(stock_id)
                except Exception as exc:
                    status.error = f"{type(exc).__name__}: {exc}"
                    status.partial_reasons.append(f"source_failed:{source}")
                    outcomes[stock_id]["failed"].append(source)
                    if source in CRITICAL_SOURCES:
                        status.transition(ScanState.FAILED, at=now, error=status.error)
                    return
                status.source_used = fallback_name
                outcomes[stock_id]["ok"].append(source)
                return
            status.error = f"fallback_unavailable:{fallback_name}"
        else:
            status.error = outcome.error

        status.partial_reasons.append(f"source_failed:{source}")
        outcomes[stock_id]["failed"].append(source)
        if source in CRITICAL_SOURCES:
            status.transition(ScanState.FAILED, at=now, error=status.error)

    def _finalize(
        self,
        stock_ids: Sequence[str],
        now: datetime,
        report: FlowReport,
        inactive_ids: Sequence[str] = (),
    ) -> None:
        """VALIDATING -> READY/PARTIAL_DATA + sayimlar (INACTIVE dahil)."""
        counts = {
            ScanState.READY.value: 0,
            ScanState.PARTIAL_DATA.value: 0,
            ScanState.FAILED.value: 0,
            ScanState.INACTIVE.value: 0,
        }
        for stock_id in stock_ids:
            status = self.statuses[stock_id]
            if status.state is ScanState.FAILED:
                counts[ScanState.FAILED.value] += 1
                report.errors.append(f"{stock_id}: {status.error}")
                continue
            status.transition(ScanState.VALIDATING, at=now)
            if status.partial_reasons:
                status.transition(ScanState.PARTIAL_DATA, at=now)
                counts[ScanState.PARTIAL_DATA.value] += 1
            else:
                status.transition(ScanState.READY, at=now)
                counts[ScanState.READY.value] += 1
        counts[ScanState.INACTIVE.value] = len(inactive_ids)
        report.per_stock = {
            s: self.statuses[s] for s in list(stock_ids) + list(inactive_ids)
        }
        report.counts = counts

    # --- bilincli yeniden tarama ---------------------------------------
    def critical_rescan(
        self,
        stock_ids: Sequence[str],
        reason: str,
        *,
        now: Optional[datetime] = None,
    ) -> FlowReport:
        """Bilincli yeniden tarama dalgasi (R2/R3... parent_run_id ile)."""
        now = now or self._now()
        stock_ids = list(stock_ids)
        run_id = self.registry.start_run(now.date(), trigger="critical_rescan")
        report = FlowReport(
            run_id=run_id,
            status=FLOW_COMPLETED,
            started_at=now,
            universe_size=len(stock_ids),
            reason=reason,
        )
        for stock_id in stock_ids:
            status = self.statuses.get(stock_id)
            if status is None:
                self.statuses[stock_id] = StockScanStatus(
                    stock_id=stock_id, state=ScanState.WAITING, updated_at=now
                )
            elif status.state is ScanState.FAILED:
                # FAILED -> WAITING yalnizca bilincli yeniden taramada.
                status.transition(
                    ScanState.WAITING,
                    reason=CONSCIOUS_RESCAN_REASON,
                    at=now,
                )
                status.error = None
                status.partial_reasons = []
            elif status.state is ScanState.WAITING:
                pass
            else:
                # Terminal/ara durumlar icin yeni run surumu: taze durum.
                fresh = StockScanStatus(
                    stock_id=stock_id, state=ScanState.WAITING, updated_at=now
                )
                fresh.history = list(status.history) + [status.state]
                self.statuses[stock_id] = fresh

        self._run_collection_waves(stock_ids, now, report)
        self._finalize(stock_ids, now, report)
        self.registry.complete_run(run_id, RUN_COMPLETED)
        report.completed_at = now
        return report
