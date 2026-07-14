"""BLOK 14 - Run yonetimi (idempotent run kaydi).

- run_id bicimi: {YYYY-MM-DD}-TARAMA-R{n} (R1 varsayilan).
- AYNI run_id iki kez BASLATILAMAZ (RunAlreadyActiveError):
  aktif run varken yeni start reddedilir, duplicate_attempts++ sayilir,
  kayit yazilmaz.
- Bilincli yeniden tarama (manual/admin/rescan): onceki run COMPLETED/FAILED
  olmali -> yeni run_id R2, R3... + parent_run_id baglantisi.
- Run durumlari: ACTIVE, COMPLETED, FAILED, ABORTED.

stdlib only; deterministik; saat enjekte.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable, Dict, List, Optional, Union

RUN_ACTIVE = "ACTIVE"
RUN_COMPLETED = "COMPLETED"
RUN_FAILED = "FAILED"
RUN_ABORTED = "ABORTED"

TERMINAL_STATUSES = (RUN_COMPLETED, RUN_FAILED, RUN_ABORTED)
# Bilincli yeniden taramaya izin veren onceki-run durumlari.
RESCAN_ALLOWED_STATUSES = (RUN_COMPLETED, RUN_FAILED)
# Bilincli yeniden tarama tetikleyicileri (scheduled R2+ uretemez).
RESCAN_TRIGGERS = ("manual", "admin", "rescan", "critical_rescan")


class RunAlreadyActiveError(Exception):
    """Ayni run_id ikinci kez baslatilamaz (duplicate attempt sayildi)."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        super().__init__(f"Run zaten aktif/mevcut: {run_id}")


class RescanNotAllowedError(Exception):
    """Bilincli yeniden tarama kosulu saglanmadi (onceki run terminal degil)."""


class RunNotFoundError(Exception):
    """Bilinmeyen run_id."""


@dataclass
class ScanRun:
    """Tek tarama calistirmasi kaydi."""

    run_id: str
    run_date: date
    trigger: str
    revision: int
    status: str = RUN_ACTIVE
    parent_run_id: Optional[str] = None
    duplicate_attempts: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    history: List[str] = field(default_factory=list)


class RunRegistry:
    """run_id idempotency + R-surumleri + tek-run kilidi."""

    def __init__(self, clock: Optional[Callable[[], datetime]] = None) -> None:
        self.clock = clock or datetime.now
        self._runs: Dict[str, ScanRun] = {}
        self._order: List[str] = []

    # --- yardimcilar -------------------------------------------------
    @staticmethod
    def _as_date(run_date: Union[date, str, datetime]) -> date:
        if isinstance(run_date, datetime):
            return run_date.date()
        if isinstance(run_date, str):
            return date.fromisoformat(run_date)
        return run_date

    @staticmethod
    def make_run_id(day: date, revision: int) -> str:
        return f"{day.isoformat()}-TARAMA-R{revision}"

    def runs_for_date(self, day: date) -> List[ScanRun]:
        return [self._runs[rid] for rid in self._order if self._runs[rid].run_date == day]

    def active_run(self, day: date) -> Optional[ScanRun]:
        for run in self.runs_for_date(day):
            if run.status == RUN_ACTIVE:
                return run
        return None

    # --- baslat -------------------------------------------------------
    def start_run(self, run_date: Union[date, str, datetime], trigger: str = "scheduled") -> str:
        """Yeni run baslat; kural ihlalinde RunAlreadyActiveError/RescanNotAllowedError."""
        day = self._as_date(run_date)
        existing = self.runs_for_date(day)
        active = self.active_run(day)

        if active is not None:
            # Ayni run_id tekrar baslatma girisimi: say, kayit yazma, reddet.
            active.duplicate_attempts += 1
            raise RunAlreadyActiveError(active.run_id)

        if not existing:
            run_id = self.make_run_id(day, 1)
            self._register(day, run_id, trigger, revision=1, parent_run_id=None)
            return run_id

        latest = existing[-1]
        if trigger not in RESCAN_TRIGGERS:
            # scheduled tekrar R1 baslatmaya calisir -> duplicate say, reddet.
            latest.duplicate_attempts += 1
            raise RunAlreadyActiveError(latest.run_id)

        # Bilincli yeniden tarama: onceki run COMPLETED/FAILED olmali.
        if latest.status not in RESCAN_ALLOWED_STATUSES:
            raise RescanNotAllowedError(
                f"R{latest.revision + 1} icin onceki run COMPLETED/FAILED olmali "
                f"(simdiki: {latest.status})"
            )
        revision = latest.revision + 1
        run_id = self.make_run_id(day, revision)
        self._register(day, run_id, trigger, revision=revision, parent_run_id=latest.run_id)
        return run_id

    def _register(
        self,
        day: date,
        run_id: str,
        trigger: str,
        revision: int,
        parent_run_id: Optional[str],
    ) -> None:
        self._runs[run_id] = ScanRun(
            run_id=run_id,
            run_date=day,
            trigger=trigger,
            revision=revision,
            status=RUN_ACTIVE,
            parent_run_id=parent_run_id,
            started_at=self.clock(),
        )
        self._order.append(run_id)

    # --- tamamla ------------------------------------------------------
    def complete_run(self, run_id: str, status: str = RUN_COMPLETED) -> ScanRun:
        """Run'i terminal duruma tasir (COMPLETED/FAILED/ABORTED)."""
        run = self.get_run(run_id)
        if run is None:
            raise RunNotFoundError(run_id)
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"gecersiz terminal durum: {status}")
        if run.status != RUN_ACTIVE:
            raise ValueError(f"run zaten terminal: {run.status}")
        run.status = status
        run.completed_at = self.clock()
        run.history.append(status)
        return run

    def fail_run(self, run_id: str) -> ScanRun:
        return self.complete_run(run_id, RUN_FAILED)

    def abort_run(self, run_id: str) -> ScanRun:
        return self.complete_run(run_id, RUN_ABORTED)

    # --- sorgu --------------------------------------------------------
    def get_run(self, run_id: str) -> Optional[ScanRun]:
        return self._runs.get(run_id)

    def latest_run(self, run_date: Union[date, str, datetime]) -> Optional[ScanRun]:
        day = self._as_date(run_date)
        runs = self.runs_for_date(day)
        return runs[-1] if runs else None

    def all_runs(self) -> List[ScanRun]:
        return [self._runs[rid] for rid in self._order]
