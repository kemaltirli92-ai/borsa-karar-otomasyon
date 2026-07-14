"""BLOK 14 - Kontrollu paralellik havuzu.

- ControlledPool(max_workers): 100 hisse TEK senkron donguyle CALISTIRILMAZ;
  gorevler max_workers sinirli havuza dagitilir.
- Her gorev try/except ile izole: 1 hisse hata verirse diger 99 DEVAM EDER.
- use_threads=False: sira ile ama AYNI izolasyonla (deterministik mod).
- max_workers asla SourcePolicy concurrency_limit'i asmaz (for_policy/bounded).
- wait_all(timeout) -> (completed, failed, timed_out).

stdlib only; deterministik; gercek ag YOK.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.services.stock_scanning.orchestration.limits import SourcePolicy


@dataclass
class PoolTask:
    """Havuza verilen tek gorev."""

    task_id: str
    fn: Callable[[], Any]


@dataclass
class TaskResult:
    """Gorev sonucu (hata izolasyonu: hata o gorevin sonucuna yazilir)."""

    task_id: str
    ok: bool
    value: Any = None
    error: Optional[str] = None
    timed_out: bool = False


@dataclass
class PoolReport:
    """wait_all ozeti."""

    completed: int
    failed: int
    timed_out: int
    results: Dict[str, TaskResult] = field(default_factory=dict)


class ControlledPool:
    """max_workers sinirli gorev havuzu (thread opsiyonel)."""

    def __init__(self, max_workers: int = 4, use_threads: bool = False) -> None:
        if max_workers < 1:
            raise ValueError("max_workers >= 1 olmali")
        self.max_workers = max_workers
        self.use_threads = use_threads
        self._tasks: List[PoolTask] = []
        self._results: Dict[str, TaskResult] = {}
        self._threads: List[threading.Thread] = []
        self._started = False
        self._peak = 0

    # --- fabrika / sinir kontrolu ------------------------------------
    @classmethod
    def for_policy(
        cls,
        policy: SourcePolicy,
        requested_workers: Optional[int] = None,
        use_threads: bool = False,
    ) -> "ControlledPool":
        """Kaynak politikasi sinirinda havuz: istek asla limiti asamaz."""
        req = requested_workers if requested_workers is not None else policy.concurrency_limit
        return cls(max_workers=min(req, policy.concurrency_limit), use_threads=use_threads)

    @classmethod
    def bounded(cls, requested_workers: int, concurrency_limit: int, use_threads: bool = False) -> "ControlledPool":
        return cls(max_workers=min(requested_workers, concurrency_limit), use_threads=use_threads)

    def exceeds(self, policy: SourcePolicy) -> bool:
        """Havuz kaynak limitini asiyor mu?"""
        return self.max_workers > policy.concurrency_limit

    @property
    def peak_concurrency(self) -> int:
        return self._peak

    @property
    def results(self) -> Dict[str, TaskResult]:
        return dict(self._results)

    @property
    def task_count(self) -> int:
        return len(self._tasks)

    # --- gorev kabulu -------------------------------------------------
    def submit(self, task_id: str, fn: Callable[[], Any]) -> None:
        if self._started:
            raise RuntimeError("pool zaten baslatildi")
        self._tasks.append(PoolTask(task_id=task_id, fn=fn))

    def submit_many(self, tasks: List[PoolTask]) -> None:
        for t in tasks:
            self.submit(t.task_id, t.fn)

    # --- calistirma ---------------------------------------------------
    def _run_one(self, task: PoolTask) -> None:
        """Tek gorev: TAM izolasyon (hata diger gorevlere SIÇRAMAZ)."""
        try:
            value = task.fn()
        except Exception as exc:  # bilincli genis except: izolasyon
            self._results[task.task_id] = TaskResult(
                task_id=task.task_id, ok=False, error=f"{type(exc).__name__}: {exc}"
            )
            return
        self._results[task.task_id] = TaskResult(task_id=task.task_id, ok=True, value=value)

    def start(self) -> None:
        """Gorevleri baslat.

        use_threads=False: sira ile, ayni izolasyonla (deterministik).
        use_threads=True: semaphore(max_workers) sinirli thread'ler.
        """
        if self._started:
            raise RuntimeError("pool zaten baslatildi")
        self._started = True
        if not self.use_threads:
            self._peak = 1 if self._tasks else 0
            for task in self._tasks:
                self._run_one(task)
            return
        semaphore = threading.Semaphore(self.max_workers)
        counter_lock = threading.Lock()
        state = {"current": 0}

        def worker(task: PoolTask) -> None:
            with semaphore:
                with counter_lock:
                    state["current"] += 1
                    if state["current"] > self._peak:
                        self._peak = state["current"]
                try:
                    self._run_one(task)
                finally:
                    with counter_lock:
                        state["current"] -= 1

        for task in self._tasks:
            t = threading.Thread(target=worker, args=(task,), daemon=True)
            self._threads.append(t)
            t.start()

    def wait_all(self, timeout: Optional[float] = None) -> Tuple[int, int, int]:
        """Tum gorevleri bekle -> (completed, failed, timed_out).

        sync modda gorevler start() sirasinda tamamlanmistir.
        timeout suresi icinde bitmeyen gorevler timed_out sayilir.
        """
        if not self._started:
            raise RuntimeError("once start() cagrilmali")
        if self.use_threads:
            deadline = None if timeout is None else time.monotonic() + timeout
            for t in self._threads:
                if deadline is None:
                    t.join()
                else:
                    remaining = deadline - time.monotonic()
                    t.join(max(remaining, 0.0))
            for i, task in enumerate(self._tasks):
                if i < len(self._threads) and self._threads[i].is_alive():
                    if task.task_id not in self._results:
                        self._results[task.task_id] = TaskResult(
                            task_id=task.task_id,
                            ok=False,
                            error="timed_out",
                            timed_out=True,
                        )
        completed = sum(1 for r in self._results.values() if r.ok)
        failed = sum(1 for r in self._results.values() if not r.ok and not r.timed_out)
        timed_out = sum(1 for r in self._results.values() if r.timed_out)
        return completed, failed, timed_out

    def execute(
        self, tasks: List[PoolTask], timeout: Optional[float] = None
    ) -> PoolReport:
        """submit + start + wait_all kisa yolu."""
        self.submit_many(tasks)
        self.start()
        completed, failed, timed_out = self.wait_all(timeout)
        return PoolReport(
            completed=completed,
            failed=failed,
            timed_out=timed_out,
            results=self.results,
        )
