"""BLOK 9 - Islem gunu takvimi (calendar.py).

TradingCalendar: bir tarihin gecerli islem gunu olup olmadigini soyler.

Kurallar (SPEC BLOK 9 bolum 5):
- Hafta sonu (varsayilan weekday 5=Cumartesi, 6=Pazar; `weekend` parametresi
  ile degistirilebilir) islem gunu degildir.
- Resmi tatiller ENJEKTE edilir: ISO tarih string seti veya
  callable(date_str) -> bool. Varsayilan: tatil yok (sadece hafta sonu).
- Gelecek tarih islem gunu sayilmaz (FUTURE_DATE). "Bugun" enjekte saatten
  gelir (clock: date / datetime / ISO str donebilir); varsayilan date.today.

non_trading_reason(date_str) -> None | neden kodu:
    WEEKEND | HOLIDAY | FUTURE_DATE | INVALID_DATE
is_trading_day(date_str) -> bool (neden None ise True).

Gercek ag erisimi YOKTUR; stdlib only; deterministik.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Callable, Optional, Set, Union

# Neden kodlari
WEEKEND = "WEEKEND"
HOLIDAY = "HOLIDAY"
FUTURE_DATE = "FUTURE_DATE"
INVALID_DATE = "INVALID_DATE"

HolidaySource = Union[Set[str], Callable[[str], bool], None]


def _coerce_date(value) -> Optional[date]:
    """date/datetime/ISO string -> date; gecersizse None."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


class TradingCalendar:
    """Islem gunu takvimi (hafta sonu + enjekte tatil + gelecek tarih)."""

    def __init__(
        self,
        holidays: HolidaySource = None,
        weekend=(5, 6),
        clock: Optional[Callable] = None,
    ):
        if holidays is not None and not callable(holidays):
            holidays = {str(h) for h in holidays}
        self._holidays = holidays
        self.weekend = tuple(weekend)
        self._clock = clock or date.today

    # ------------------------------------------------------------------ #
    # Saat (enjekte)
    # ------------------------------------------------------------------ #
    def today(self) -> date:
        """Enjekte saatten 'bugun'."""
        now = self._clock()
        d = _coerce_date(now)
        if d is None:
            raise TypeError("clock date/datetime/ISO str dondurmeli: %r" % (now,))
        return d

    # ------------------------------------------------------------------ #
    # Tatil kontrolu
    # ------------------------------------------------------------------ #
    def is_holiday(self, date_str: str) -> bool:
        """Tarih enjekte tatil listesinde/callable'inda mi?"""
        if self._holidays is None:
            return False
        if callable(self._holidays):
            return bool(self._holidays(str(date_str)))
        return str(date_str) in self._holidays

    # ------------------------------------------------------------------ #
    # Islem gunu kontrolu
    # ------------------------------------------------------------------ #
    def non_trading_reason(self, date_str) -> Optional[str]:
        """Islem gunu degilse neden kodu; islem gunuyse None.

        Oncelik sirasi: INVALID_DATE > FUTURE_DATE > WEEKEND > HOLIDAY.
        """
        d = _coerce_date(date_str)
        if d is None:
            return INVALID_DATE
        if d > self.today():
            return FUTURE_DATE
        if d.weekday() in self.weekend:
            return WEEKEND
        if self.is_holiday(d.isoformat()):
            return HOLIDAY
        return None

    def is_trading_day(self, date_str) -> bool:
        """Tarih gecerli bir islem gunu mu?"""
        return self.non_trading_reason(date_str) is None
