"""BLOK 8 - Fiyat kaynaklari: PriceBar veri modeli + PriceSource arayuzu.

- PriceBar: tek bir islem gununun normalize OHLCV kaydi (SPEC bolum 3).
- PriceSource: fetcher enjeksiyonlu kaynak taban sinifi. fetcher None ise
  kaynak "baglanamadi" davranisi gosterir: SourceUnavailableError.
- LicensedSource (ana, resmi/lisansli API stub'i), YFinanceSource (yedek
  stub — gercek yfinance paketi YOK), GoogleFinanceSource (dogrulama stub'i).

Gercek ag erisimi YOKTUR: tum veri enjekte edilen fetcher'dan gelir.

Fetcher sozlesmesi:
    fetcher(stock_id, days=None, date=None) -> list[dict]
Donen her kayit ham sozluk olur:
    zorunlu: date (veya trade_date), open, high, low, close, volume
    opsiyonel: adjusted_close (veya adj_close), currency, source_timestamp,
               stock_id
Eksik/bozuk alanli kayitlar normalizasyon sirasinda elenir ve loglanir
(BAR_SKIPPED olayi).

Saat enjekte edilebilir (clock parametresi, ISO-8601 UTC string doner).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, List, Optional

from .validator import is_valid_bar

DEFAULT_CURRENCY = "TRY"

BAR_SKIPPED = "BAR_SKIPPED"


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SourceUnavailableError(Exception):
    """Kaynak kullanilamaz (fetcher enjekte edilmedi / baglanti yok)."""


@dataclass
class PriceBar:
    """Normalize edilmis tek gunluk fiyat/hacim kaydi.

    Zorunlu alanlar: stock_id, trade_date (ISO), open, high, low, close,
    volume. Opsiyonel alanlar: adjusted_close, currency, source,
    source_timestamp, collected_timestamp (toplama damgasi — saat enjekte).
    """

    stock_id: str
    trade_date: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    adjusted_close: Optional[float] = None
    currency: str = DEFAULT_CURRENCY
    source: str = ""
    source_timestamp: Optional[str] = None
    collected_timestamp: str = ""


class PriceSource:
    """Fiyat kaynagi arayuzu (fetcher enjeksiyonlu).

    fetcher None ise tum fetch cagrilari SourceUnavailableError firlatir
    (kaynak "baglanamadi" davranisi).
    """

    def __init__(
        self,
        name: str,
        fetcher: Optional[Callable] = None,
        default_currency: str = DEFAULT_CURRENCY,
        clock: Optional[Callable[[], str]] = None,
        logger=None,
    ):
        self.name = name
        self._fetcher = fetcher
        self.default_currency = default_currency
        self._clock = clock or _utcnow
        self._logger = logger

    # ------------------------------------------------------------------ #
    # Loglama
    # ------------------------------------------------------------------ #
    def _log(self, code: str, **fields) -> None:
        lg = self._logger
        if lg is None:
            return
        if callable(lg):
            lg(code, dict(fields))
        elif hasattr(lg, "info"):
            lg.info("%s | %s", code, fields)

    # ------------------------------------------------------------------ #
    # Fetcher cagrisi
    # ------------------------------------------------------------------ #
    def _require_fetcher(self) -> Callable:
        if self._fetcher is None:
            raise SourceUnavailableError(
                "kaynak '%s' icin fetcher enjekte edilmedi" % self.name
            )
        return self._fetcher

    def _call(self, stock_id: str, days=None, date=None) -> list:
        fetcher = self._require_fetcher()
        raw = fetcher(stock_id, days=days, date=date)
        if raw is None:
            return []
        return list(raw)

    # ------------------------------------------------------------------ #
    # Normalizasyon
    # ------------------------------------------------------------------ #
    def _normalize(self, record, stock_id: str) -> Optional[PriceBar]:
        """Ham kaydi PriceBar'a cevirir; eksik/bozuk kayitlari eler (loglar)."""
        if not isinstance(record, dict):
            self._log(BAR_SKIPPED, stock_id=stock_id, reason="record_not_dict")
            return None
        trade_date = record.get("date") or record.get("trade_date")
        if not trade_date:
            self._log(BAR_SKIPPED, stock_id=stock_id, reason="missing_date")
            return None
        try:
            open_ = float(record["open"])
            high = float(record["high"])
            low = float(record["low"])
            close = float(record["close"])
            volume = int(record["volume"])
        except (KeyError, TypeError, ValueError):
            self._log(BAR_SKIPPED, stock_id=stock_id, reason="missing_or_bad_field")
            return None

        adj_raw = record.get("adjusted_close", record.get("adj_close"))
        adjusted_close = None
        if adj_raw is not None:
            try:
                adjusted_close = float(adj_raw)
            except (TypeError, ValueError):
                adjusted_close = None

        currency = record.get("currency") or self.default_currency

        bar = PriceBar(
            stock_id=stock_id,
            trade_date=str(trade_date),
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            adjusted_close=adjusted_close,
            currency=str(currency),
            source=self.name,
            source_timestamp=record.get("source_timestamp"),
            collected_timestamp=self._clock(),
        )
        if not is_valid_bar(bar):
            self._log(BAR_SKIPPED, stock_id=stock_id, reason="invalid_bar")
            return None
        return bar

    # ------------------------------------------------------------------ #
    # Arayuz
    # ------------------------------------------------------------------ #
    def fetch_history(self, stock_id: str, days: int) -> List[PriceBar]:
        """Son `days` gunun barlarini dondurur (tarih sirali, artan)."""
        raw = self._call(stock_id, days=int(days))
        bars = []
        for record in raw:
            bar = self._normalize(record, stock_id)
            if bar is not None:
                bars.append(bar)
        bars.sort(key=lambda b: b.trade_date)
        return bars

    def fetch_latest(self, stock_id: str) -> Optional[PriceBar]:
        """En yeni bar; yoksa None."""
        bars = self.fetch_history(stock_id, 1)
        return bars[-1] if bars else None

    def fetch_date(self, stock_id: str, date: str) -> Optional[PriceBar]:
        """Belirli bir tarihin bar'i; yoksa None."""
        raw = self._call(stock_id, date=str(date))
        for record in raw:
            bar = self._normalize(record, stock_id)
            if bar is not None and bar.trade_date == str(date):
                return bar
        return None


class LicensedSource(PriceSource):
    """Ana kaynak stub'i — resmi/lisansli API ileride baglanacak.

    Gercek API istemcisi YOK; fetcher enjeksiyonu zorunludur. fetcher None
    ise SourceUnavailableError firlatilir.
    """

    def __init__(self, fetcher=None, **kwargs):
        super().__init__("licensed", fetcher=fetcher, **kwargs)


class YFinanceSource(PriceSource):
    """Yedek kaynak stub'i — gercek yfinance paketi KURULMAZ.

    Veri her zaman enjekte fetcher'dan gelir.
    """

    def __init__(self, fetcher=None, **kwargs):
        super().__init__("yfinance", fetcher=fetcher, **kwargs)


class GoogleFinanceSource(PriceSource):
    """Dogrulama kaynagi stub'i (kapanis karsilastirmasi icin)."""

    def __init__(self, fetcher=None, **kwargs):
        super().__init__("google", fetcher=fetcher, **kwargs)
