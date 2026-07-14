"""BLOK 14 - Retry politikasi ve yedek kaynak gecisi.

- Sabit plan: 1. deneme HEMEN, 2. deneme +30sn, 3. deneme +90sn (kumulatif).
- Gercek bekleme YOK: planlanan deneme zamanlari dondurulur (enjekte saat).
- Deneme sayisi asilirsa yedek kaynaga gecis + FALLBACK_SWITCHED logu
  (from_source -> to_source, neden, deneme sayisi).

stdlib only; deterministik; gercek ag YOK; gercek bekleme YOK.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, List, Optional, Sequence

FALLBACK_SWITCHED = "FALLBACK_SWITCHED"

# Sabit gecikme plani (saniye): 1. deneme hemen, 2. +30, 3. +90.
DEFAULT_DELAYS: Sequence[int] = (0, 30, 90)


def _emit(logger: Any, event: str, **fields: Any) -> None:
    """Yapisal log: logger.record varsa onu kullan, yoksa warning."""
    if logger is None:
        return
    record = getattr(logger, "record", None)
    if callable(record):
        record(event, **fields)
        return
    logger.warning("%s %s", event, fields)


@dataclass(frozen=True)
class FallbackEvent:
    """Yedek kaynaga gecis kaydi (FALLBACK_SWITCHED)."""

    from_source: str
    to_source: str
    reason: str
    attempts: int
    at: Optional[datetime] = None


@dataclass(frozen=True)
class RetryOutcome:
    """Bir cagrinin retry sonucu."""

    ok: bool
    value: Any = None
    error: Optional[str] = None
    attempts: int = 0
    attempt_times: List[datetime] = field(default_factory=list)
    fallback_event: Optional[FallbackEvent] = None


class RetryPolicy:
    """Sabit planli retry: hemen / +30sn / +90sn (gercek bekleme yok)."""

    def __init__(
        self,
        max_attempts: int = 3,
        delays: Sequence[int] = DEFAULT_DELAYS,
        fallback_source: Optional[str] = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts >= 1 olmali")
        if len(delays) < max_attempts:
            raise ValueError("delays en az max_attempts uzunlugunda olmali")
        self.max_attempts = max_attempts
        self.delays = tuple(delays)
        self.fallback_source = fallback_source

    # --- plan ---------------------------------------------------------
    def attempt_times(self, start: datetime) -> List[datetime]:
        """Planlanan deneme zamanlari (kumulatif): t0, t0+30, t0+120.

        Gercek bekleme yapilmaz; zamanlar enjekte saat uzerinden hesaplanir.
        """
        times: List[datetime] = []
        offset = 0
        for i in range(self.max_attempts):
            offset += self.delays[i]
            times.append(start + timedelta(seconds=offset))
        return times

    def next_attempt_time(self, start: datetime, attempt_no: int) -> Optional[datetime]:
        """attempt_no (1 tabanli) denemenin planlanan zamani; asimda None."""
        if attempt_no < 1 or attempt_no > self.max_attempts:
            return None
        return self.attempt_times(start)[attempt_no - 1]

    def should_retry(self, attempts_done: int) -> bool:
        """Su ana kadar yapilan deneme sayisina gore devam edilmeli mi?"""
        return attempts_done < self.max_attempts

    def exceeded(self, attempts_done: int) -> bool:
        return attempts_done >= self.max_attempts

    # --- yedek kaynak -------------------------------------------------
    def switch_fallback(
        self,
        from_source: str,
        reason: str,
        attempts: int,
        *,
        logger: Any = None,
        at: Optional[datetime] = None,
    ) -> FallbackEvent:
        """Deneme asiminda yedek kaynaga gec + FALLBACK_SWITCHED logu."""
        if not self.fallback_source:
            raise ValueError("fallback_source tanimli degil")
        event = FallbackEvent(
            from_source=from_source,
            to_source=self.fallback_source,
            reason=reason,
            attempts=attempts,
            at=at,
        )
        _emit(
            logger,
            FALLBACK_SWITCHED,
            from_source=from_source,
            to_source=self.fallback_source,
            reason=reason,
            attempts=attempts,
        )
        return event

    # --- calistirma ---------------------------------------------------
    def execute(
        self,
        fn: Callable[[], Any],
        *,
        start: Optional[datetime] = None,
        source_name: str = "",
        logger: Any = None,
        at: Optional[datetime] = None,
    ) -> RetryOutcome:
        """fn'i en fazla max_attempts kez dene; gercek bekleme YOK.

        Denemeler planlanan zamanlara gore *ard arda* (uykusuz) yapilir.
        Tum denemeler basarisizsa ve fallback_source varsa
        FALLBACK_SWITCHED olayi uretilir (yedek cagrisi yapilmaz;
        yedegin calistirilmasi cagirana/orchestrator'a aittir).
        """
        planned = self.attempt_times(start) if start is not None else []
        last_error: Optional[str] = None
        done = 0
        for attempt_no in range(1, self.max_attempts + 1):
            done = attempt_no
            try:
                value = fn()
            except Exception as exc:  # her deneme izole
                last_error = f"{type(exc).__name__}: {exc}"
                continue
            return RetryOutcome(
                ok=True,
                value=value,
                attempts=done,
                attempt_times=planned[:done],
            )
        event = None
        if self.fallback_source:
            event = self.switch_fallback(
                from_source=source_name,
                reason=last_error or "unknown_error",
                attempts=done,
                logger=logger,
                at=at,
            )
        return RetryOutcome(
            ok=False,
            error=last_error,
            attempts=done,
            attempt_times=planned,
            fallback_event=event,
        )
