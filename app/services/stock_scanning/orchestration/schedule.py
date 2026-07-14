"""BLOK 14 - Sabah tarama zaman plani (8 dilim).

- Europe/Istanbul saat dilimi SABIT (zoneinfo; disa enjekte edilemez).
- ScanSchedule: 8 dilim (config'ten okunabilir, varsayilanlar SABIT).
- DATA_CUTOFF 09:40 sabit nokta (degistirilemez kural).
- is_trading_day: hafta sonu + enjekte tatil.
- current_phase(now): NOT_TRADING_DAY / OUTSIDE_SCHEDULE / Phase.

stdlib only; saat enjekte; gercek ag YOK.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import Enum
from typing import FrozenSet, Optional, Tuple, Union
from zoneinfo import ZoneInfo

# Europe/Istanbul SABIT kurali: tz disaridan enjekte edilemez.
ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")

# DATA_CUTOFF sabit noktasi: 09:40 (degistirilemez).
DATA_CUTOFF_TIME = time(9, 40)

NOT_TRADING_DAY = "NOT_TRADING_DAY"
OUTSIDE_SCHEDULE = "OUTSIDE_SCHEDULE"


class Phase(str, Enum):
    """Sabah planinin 8 dilimi."""

    PRECHECK = "PRECHECK"  # 08:00 nokta
    COLLECTION = "COLLECTION"  # 08:00-08:45
    CLEANING = "CLEANING"  # 08:45-09:00
    RECOVERY = "RECOVERY"  # 09:00-09:30
    PACKAGING = "PACKAGING"  # 09:30-09:35
    ANOMALY_CHECK = "ANOMALY_CHECK"  # 09:35-09:40
    DATA_CUTOFF = "DATA_CUTOFF"  # 09:40 nokta (SABIT)
    CRITICAL_RESCAN = "CRITICAL_RESCAN"  # 09:40-09:45


@dataclass(frozen=True)
class PhaseWindow:
    """Tek dilim: point=True ise start==end tam an (nokta dilim)."""

    phase: Phase
    start: time
    end: time
    order: int
    point: bool = False

    def contains(self, t: time) -> bool:
        if self.point:
            return t == self.start
        return self.start <= t < self.end


def _default_windows() -> Tuple[PhaseWindow, ...]:
    """Varsayilan 8 dilim (SABIT)."""
    return (
        PhaseWindow(Phase.PRECHECK, time(8, 0), time(8, 0), 1, point=True),
        PhaseWindow(Phase.COLLECTION, time(8, 0), time(8, 45), 2),
        PhaseWindow(Phase.CLEANING, time(8, 45), time(9, 0), 3),
        PhaseWindow(Phase.RECOVERY, time(9, 0), time(9, 30), 4),
        PhaseWindow(Phase.PACKAGING, time(9, 30), time(9, 35), 5),
        PhaseWindow(Phase.ANOMALY_CHECK, time(9, 35), time(9, 40), 6),
        PhaseWindow(Phase.DATA_CUTOFF, DATA_CUTOFF_TIME, DATA_CUTOFF_TIME, 7, point=True),
        PhaseWindow(Phase.CRITICAL_RESCAN, time(9, 40), time(9, 45), 8),
    )


@dataclass(frozen=True)
class ScanSchedule:
    """Zaman plani: 8 dilim + enjekte tatil listesi.

    timezone alani SABIT: Europe/Istanbul (zoneinfo). Disaridan
    baska bir tz verilemez (sabit kural).
    """

    windows: Tuple[PhaseWindow, ...] = field(default_factory=_default_windows)
    holidays: FrozenSet[date] = field(default_factory=frozenset)
    timezone: ZoneInfo = field(default=ISTANBUL_TZ, compare=False)

    def __post_init__(self) -> None:
        if self.timezone is not ISTANBUL_TZ and str(self.timezone) != "Europe/Istanbul":
            raise ValueError("timezone sabit kural: Europe/Istanbul")
        if len(self.windows) != 8:
            raise ValueError("ScanSchedule tam 8 dilim icermeli")
        orders = [w.order for w in self.windows]
        if orders != sorted(orders):
            raise ValueError("dilimler order alanina gore sirali olmali")
        cutoff = [w for w in self.windows if w.phase is Phase.DATA_CUTOFF]
        if not cutoff or cutoff[0].start != DATA_CUTOFF_TIME or not cutoff[0].point:
            raise ValueError("DATA_CUTOFF 09:40 nokta dilimi SABIT olmali")

    # --- yardimcilar -------------------------------------------------
    def _to_istanbul(self, now: datetime) -> datetime:
        """now'u Istanbul saatine cevir (naive -> Istanbul varsayilir)."""
        if now.tzinfo is None:
            return now.replace(tzinfo=ISTANBUL_TZ)
        return now.astimezone(ISTANBUL_TZ)

    def with_holidays(self, *days: Union[date, str]) -> "ScanSchedule":
        """Enjekte tatil(ler) eklenmis yeni schedule (frozen)."""
        parsed = set(self.holidays)
        for d in days:
            if isinstance(d, str):
                parsed.add(date.fromisoformat(d))
            else:
                parsed.add(d)
        return ScanSchedule(windows=self.windows, holidays=frozenset(parsed))

    def window_for(self, phase: Phase) -> PhaseWindow:
        for w in self.windows:
            if w.phase is phase:
                return w
        raise KeyError(phase)

    # --- kurallar ----------------------------------------------------
    def is_trading_day(self, now: Union[datetime, date]) -> bool:
        """Hafta sonu ve enjekte tatil disindaki gunler islem gunudur."""
        if isinstance(now, datetime):
            day = self._to_istanbul(now).date()
        else:
            day = now
        if day.weekday() >= 5:  # 5=Cumartesi, 6=Pazar
            return False
        return day not in self.holidays

    def current_phase(self, now: datetime) -> Union[Phase, str]:
        """Simdiki dilim; islem gunu degilse NOT_TRADING_DAY, plan disi ise OUTSIDE_SCHEDULE."""
        local = self._to_istanbul(now)
        if not self.is_trading_day(local):
            return NOT_TRADING_DAY
        t = local.time().replace(microsecond=0)
        for w in sorted(self.windows, key=lambda w: w.order):
            if w.contains(t):
                return w.phase
        return OUTSIDE_SCHEDULE

    @property
    def data_cutoff(self) -> time:
        """Normal veri kesim zamani: 09:40 SABIT."""
        return DATA_CUTOFF_TIME

    def phase_order(self, phase: Phase) -> int:
        return self.window_for(phase).order
