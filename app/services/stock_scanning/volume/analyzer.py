"""BLOK 10 - VolumeAnalyzer: seri analizi, eksik gun ve gercek sifir ayrimi
(analyzer.py).

VolumeAnalyzer(config=None, clock=None, zero_volume_explainer=None)

- build_volume_bar(raw_record) -> VolumeBar: BLOK 8 kaydini (PriceBar)
  duck-typing ile okur; TL hacim ayrimini turnover.resolve_turnover ile
  yapar. Eksik gun nedeni (NO_DATA/SOURCE_ERROR/HOLIDAY) kayit
  niteliklerinden cozulur.
- analyze_series(stock_id, volume_bars) -> VolumeMetrics: son gun hacmi,
  avg20, volume_ratio_20, status. Seri tarih sirali dogrulanir; ayni tarih
  tekrari REDDEDILIR (DuplicateDateError), bozuk sira SeriesOrderError.
- classify_gaps(raw_records) -> dict: eksik gunleri HOLIDAY / SOURCE_ERROR /
  NO_DATA olarak ayirir; gercek sifirlar REAL_ZERO listesinde AYRI
  listelenir.

SINYAL KILIDI: donen VolumeMetrics.signal HER ZAMAN None'dir (models
katmaninda zorlanir); bu sinifta AL/SAT/FAVORI ureten kod yolu yoktur.

Deterministik: saat enjekte (clock: date / datetime / ISO str donebilir);
bos seri icin as_of_date clock'tan alinir. Gercek ag YOK.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Dict, List, Optional, Sequence

from .classifier import RATIO_UNDEFINED, classify_volume
from .models import (
    HOLIDAY,
    NO_DATA,
    SOURCE_ERROR,
    TurnoverType,
    VolumeBar,
    VolumeConfig,
    VolumeMetrics,
    VolumeStatus,
)
from .ratio import INSUFFICIENT_WINDOW, compute_ratio_20, valid_volume
from .turnover import read_field, resolve_turnover

# classify_gaps sonuc anahtarlari
REAL_ZERO = "REAL_ZERO"

# analyze_series neden kodlari
EMPTY_SERIES = "EMPTY_SERIES"


class DuplicateDateError(ValueError):
    """Seride ayni trade_date tekrarlandi (BLOK 9 ile uyumlu red)."""


class SeriesOrderError(ValueError):
    """Seri tarih sirali degil veya trade_date gecersiz."""


@dataclass
class GapReport:
    """classify_gaps sonucu (dict'e de cevrilebilir)."""

    holiday: List[str]
    source_error: List[str]
    no_data: List[str]
    real_zero: List[str]

    def to_dict(self) -> Dict[str, List[str]]:
        return {
            HOLIDAY: list(self.holiday),
            SOURCE_ERROR: list(self.source_error),
            NO_DATA: list(self.no_data),
            REAL_ZERO: list(self.real_zero),
        }


def _read_trade_date(record) -> str:
    trade_date = read_field(record, "trade_date", "date")
    if trade_date is None or str(trade_date) == "":
        raise SeriesOrderError("trade_date gerekli: %r" % (record,))
    return str(trade_date)


class VolumeAnalyzer:
    """Hacim serisi analizcisi (saat ve aciklayici enjeksiyonlu)."""

    def __init__(
        self,
        config: Optional[VolumeConfig] = None,
        clock: Optional[Callable] = None,
        zero_volume_explainer: Optional[Callable] = None,
    ):
        self.config = config or VolumeConfig()
        self._clock = clock or (lambda: date.today())
        # (stock_id, trade_date) -> aciklama str | None
        self.zero_volume_explainer = zero_volume_explainer

    # ------------------------------------------------------------------ #
    # Saat (enjekte, deterministik)
    # ------------------------------------------------------------------ #
    def _today_str(self) -> str:
        now = self._clock()
        if isinstance(now, datetime):
            return now.date().isoformat()
        if isinstance(now, date):
            return now.isoformat()
        if isinstance(now, str):
            return now[:10]
        raise TypeError("clock date/datetime/ISO str dondurmeli: %r" % (now,))

    # ------------------------------------------------------------------ #
    # Tek bar uretimi (BLOK 8 kaydi duck-typing)
    # ------------------------------------------------------------------ #
    def build_volume_bar(self, raw_record) -> VolumeBar:
        """Ham kayittan ayrimli VolumeBar uretir.

        Duck-typing: dict veya nitelikli nesne (or. BLOK 8 PriceBar:
        stock_id, trade_date, open, high, low, close, volume, source).
        TL hacim ayrimi turnover.resolve_turnover ile yapilir; tahmin
        yolunda turnover_try=None kalir ve is_estimated=True olur.

        Eksik gun nedeni oncelik sirasiyla: kayit missing_reason alani >
        error/source_error bayragi (SOURCE_ERROR) > is_trading_day False
        (HOLIDAY) > hacim yok (NO_DATA).
        """
        trade_date = _read_trade_date(raw_record)
        stock_id = read_field(raw_record, "stock_id") or ""

        volume_raw = read_field(raw_record, "volume_units", "volume")
        volume_units = None if volume_raw is None else int(volume_raw)

        is_trading_day = read_field(raw_record, "is_trading_day")
        missing_reason = read_field(raw_record, "missing_reason")
        error_flag = read_field(raw_record, "error", "source_error")
        if missing_reason is None:
            if error_flag:
                missing_reason = SOURCE_ERROR
            elif is_trading_day is False:
                missing_reason = HOLIDAY
            elif volume_units is None:
                missing_reason = NO_DATA

        source = read_field(raw_record, "source") or ""
        turnover_try, estimated_turnover_try, turnover_type = resolve_turnover(
            raw_record, config=self.config
        )

        return VolumeBar(
            stock_id=str(stock_id),
            trade_date=trade_date,
            volume_units=volume_units,
            turnover_try=turnover_try,
            estimated_turnover_try=estimated_turnover_try,
            turnover_type=turnover_type,
            source=str(source),
            is_estimated=(turnover_type == TurnoverType.ESTIMATED),
            is_trading_day=is_trading_day,
            missing_reason=missing_reason,
        )

    # ------------------------------------------------------------------ #
    # Seri dogrulama: tarih sirasi + tekrar tarih reddi
    # ------------------------------------------------------------------ #
    @staticmethod
    def _ensure_ordered_unique(bars: Sequence) -> None:
        prev: Optional[str] = None
        for bar in bars:
            day = _read_trade_date(bar)
            if prev is not None:
                if day == prev:
                    raise DuplicateDateError(
                        "tekrar eden trade_date reddedildi: %s" % day
                    )
                if day < prev:
                    raise SeriesOrderError(
                        "seri tarih sirali degil: %s < %s" % (day, prev)
                    )
            prev = day

    # ------------------------------------------------------------------ #
    # Seri analizi
    # ------------------------------------------------------------------ #
    def analyze_series(self, stock_id: str, volume_bars: Sequence) -> VolumeMetrics:
        """VolumeMetrics uretir: son gun, avg20, ratio, status.

        - Seri bos degilse tarih sirasi ve tekrar tarih dogrulanir.
        - Son gun hacmi bilinmiyorsa status=MISSING.
        - Gercek sifir son gun + aciklama yok -> REVIEW_REQUIRED.
        - Pencerede min_valid_days'ten az gecerli gun varsa ratio=None ve
          status_reason=INSUFFICIENT_WINDOW.
        - signal HER ZAMAN None (sinyal kilidi).
        """
        bars = list(volume_bars)
        if not bars:
            return VolumeMetrics(
                stock_id=stock_id,
                as_of_date=self._today_str(),
                status=VolumeStatus.MISSING,
                status_reason=EMPTY_SERIES,
                used_days=0,
            )
        self._ensure_ordered_unique(bars)

        last_bar = bars[-1]
        last_volume = valid_volume(last_bar)
        ratio, avg20, used_days = compute_ratio_20(
            bars,
            window=self.config.window,
            min_valid_days=self.config.min_valid_days,
        )

        zero_explanation = None
        if last_volume == 0 and self.zero_volume_explainer is not None:
            zero_explanation = self.zero_volume_explainer(
                stock_id, _read_trade_date(last_bar)
            )

        status, reason = classify_volume(
            config=self.config,
            last_volume=last_volume,
            avg20=avg20,
            ratio=ratio,
            zero_explanation=zero_explanation,
            missing_reason=read_field(last_bar, "missing_reason"),
        )
        if reason == RATIO_UNDEFINED and used_days < self.config.min_valid_days:
            reason = INSUFFICIENT_WINDOW

        return VolumeMetrics(
            stock_id=stock_id,
            as_of_date=_read_trade_date(last_bar),
            last_volume_units=last_volume,
            avg20_volume_units=avg20,
            volume_ratio_20=ratio,
            status=status,
            status_reason=reason,
            used_days=used_days,
        )

    # ------------------------------------------------------------------ #
    # Eksik gun / gercek sifir ayrimi
    # ------------------------------------------------------------------ #
    def classify_gaps(self, raw_records: Sequence) -> Dict[str, List[str]]:
        """Ham kayitlari eksik-gun nedenine gore siniflandirir.

        Donus anahtarlari: HOLIDAY, SOURCE_ERROR, NO_DATA, REAL_ZERO —
        degerler trade_date listeleri (tarih sirali).

        Gercek sifir: volume_units=0 ve eksik-gun nedeni yok (islem gunu
        ama hacim 0) -> REAL_ZERO listesine; NO_DATA'ya KATILMAZ.
        """
        report = GapReport(holiday=[], source_error=[], no_data=[], real_zero=[])
        for record in raw_records:
            day = str(read_field(record, "trade_date", "date") or "")
            volume = read_field(record, "volume_units", "volume")
            missing_reason = read_field(record, "missing_reason")
            is_trading_day = read_field(record, "is_trading_day")
            error_flag = read_field(record, "error", "source_error")

            if missing_reason == HOLIDAY or (
                missing_reason is None and is_trading_day is False
            ):
                report.holiday.append(day)
                continue
            if missing_reason == SOURCE_ERROR or (
                missing_reason is None and error_flag
            ):
                report.source_error.append(day)
                continue
            if missing_reason == NO_DATA or volume is None:
                report.no_data.append(day)
                continue
            if int(volume) == 0:
                report.real_zero.append(day)
                continue
        result = report.to_dict()
        for days in result.values():
            days.sort()
        return result
