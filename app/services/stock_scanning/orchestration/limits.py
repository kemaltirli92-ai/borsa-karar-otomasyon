"""BLOK 14 - Kaynak bazli politikalar ve rate limiter.

- SourcePolicy: concurrency_limit, requests_per_minute, timeout,
  retry_count (vars. 3), backoff (RetryPolicy).
- Varsayilan politikalar: price/kap/news/actions/restrictions.
- RateLimiter: rpm kovasi (enjekte saat); limit asiminda kuyruklanir
  (sanal bekleme sayilir, gercek bekleme YOK).

stdlib only; deterministik; saat enjekte; gercek ag YOK.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Deque, Dict, Optional

from app.services.stock_scanning.orchestration.retry import RetryPolicy

DEFAULT_TIMEOUT = 10.0
DEFAULT_RETRY_COUNT = 3


@dataclass(frozen=True)
class SourcePolicy:
    """Tek veri kaynagi icin kontrol politikasi."""

    source_name: str
    concurrency_limit: int
    requests_per_minute: int
    timeout: float = DEFAULT_TIMEOUT  # saniye
    retry_count: int = DEFAULT_RETRY_COUNT
    backoff: RetryPolicy = field(default_factory=RetryPolicy)

    def __post_init__(self) -> None:
        if self.concurrency_limit < 1:
            raise ValueError("concurrency_limit >= 1 olmali")
        if self.requests_per_minute < 1:
            raise ValueError("requests_per_minute >= 1 olmali")
        if self.timeout <= 0:
            raise ValueError("timeout > 0 olmali")
        if self.retry_count < 1:
            raise ValueError("retry_count >= 1 olmali")


def _policy(
    name: str,
    concurrency: int,
    rpm: int,
    timeout: float,
    retry_count: int = DEFAULT_RETRY_COUNT,
    fallback_source: Optional[str] = None,
) -> SourcePolicy:
    return SourcePolicy(
        source_name=name,
        concurrency_limit=concurrency,
        requests_per_minute=rpm,
        timeout=timeout,
        retry_count=retry_count,
        backoff=RetryPolicy(max_attempts=retry_count, fallback_source=fallback_source),
    )


def default_policies() -> Dict[str, SourcePolicy]:
    """Varsayilan kaynak politikalari (config'ten okunabilir kopya)."""
    return {
        "price": _policy("price", 5, 60, 10.0, 3, fallback_source="price_backup"),
        "kap": _policy("kap", 2, 30, 15.0, 3, fallback_source="kap_backup"),
        "news": _policy("news", 4, 40, 10.0, 3, fallback_source="news_backup"),
        "actions": _policy("actions", 2, 20, 10.0, 3),
        "restrictions": _policy("restrictions", 2, 20, 10.0, 3),
    }


@dataclass(frozen=True)
class AcquireResult:
    """RateLimiter.acquire sonucu."""

    allowed: bool
    waited: bool
    wait_seconds: float = 0.0


class RateLimiter:
    """requests_per_minute kovasi (enjekte saat).

    Limit icindeki istek hemen gecer. Limit asiminda istek kuyruklanir:
    en eski damganin doldugu ana kadar *sanal* bekleme hesaplanir ve
    sayaçlara yazilir; gercek bekleme YAPILMAZ.
    """

    def __init__(
        self,
        requests_per_minute: int,
        clock: Callable[[], datetime],
        window_seconds: float = 60.0,
    ) -> None:
        if requests_per_minute < 1:
            raise ValueError("requests_per_minute >= 1 olmali")
        self.requests_per_minute = requests_per_minute
        self.clock = clock
        self.window_seconds = window_seconds
        self._stamps: Deque[datetime] = deque()
        self.allowed_count = 0
        self.waited_count = 0
        self.virtual_wait_total = 0.0

    def _prune(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self.window_seconds)
        while self._stamps and self._stamps[0] <= cutoff:
            self._stamps.popleft()

    def acquire(self) -> AcquireResult:
        """Bir istek hakki al; asimda kuyrukla (sanal bekleme sayilir)."""
        now = self.clock()
        self._prune(now)
        if len(self._stamps) < self.requests_per_minute:
            self._stamps.append(now)
            self.allowed_count += 1
            return AcquireResult(allowed=True, waited=False)
        # Limit asimi: en eski damga doldugunda slot acilir (sanal).
        free_at = self._stamps[0] + timedelta(seconds=self.window_seconds)
        wait = max(0.0, (free_at - now).total_seconds())
        self._stamps.popleft()
        self._stamps.append(free_at)
        self.waited_count += 1
        self.virtual_wait_total += wait
        return AcquireResult(allowed=True, waited=True, wait_seconds=wait)

    def usage(self) -> int:
        """Su anki penceredeki kullanim."""
        self._prune(self.clock())
        return len(self._stamps)
