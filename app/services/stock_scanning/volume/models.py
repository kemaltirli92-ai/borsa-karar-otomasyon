"""BLOK 10 - Hacim ve TL Islem Hacmi: veri modeli (models.py).

Iki farkli buyukluk katiyen ayristirilir:
- volume_units: el degisen pay ADEDI (adet)
- TL islem hacmi: turnover_try (kaynaktan gercek) veya
  estimated_turnover_try (formulle tahmin) — ikisi asla karistirilmaz.

Siniflar:
- TurnoverType: OFFICIAL / PROVIDER / ESTIMATED / MISSING
- VolumeStatus: NORMAL / INCREASING / HIGH / ANOMALOUS / MISSING /
  REVIEW_REQUIRED
- VolumeBar: tek gunluk ayrimli hacim kaydi
- VolumeMetrics: seri analizi sonucu (signal HER ZAMAN None — sinyal kilidi)
- VolumeConfig: esikler ve kaynak etiketi ayarlari

Sabitler: NO_DATA / SOURCE_ERROR / HOLIDAY (missing_reason alan degerleri).

Gercek ag YOK; stdlib only; deterministik.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

# ---------------------------------------------------------------------- #
# Eksik gun nedenleri (missing_reason alan degerleri)
# ---------------------------------------------------------------------- #
NO_DATA = "NO_DATA"
SOURCE_ERROR = "SOURCE_ERROR"
HOLIDAY = "HOLIDAY"

MISSING_REASONS = (NO_DATA, SOURCE_ERROR, HOLIDAY)


class TurnoverType(Enum):
    """TL islem hacmi turu.

    OFFICIAL:  borsanin resmi TL hacim alani (config.official_sources).
    PROVIDER:  veri saglayicinin TL hacim alani (resmi olmayan kaynak).
    ESTIMATED: formulle hesaplanan tahmin — asla gercek hacim sayilamaz.
    MISSING:   hacim bilgisi yok.
    """

    OFFICIAL = "OFFICIAL"
    PROVIDER = "PROVIDER"
    ESTIMATED = "ESTIMATED"
    MISSING = "MISSING"


class VolumeStatus(Enum):
    """Hacim durum siniflandirmasi (6 durum)."""

    NORMAL = "NORMAL"
    INCREASING = "INCREASING"
    HIGH = "HIGH"
    ANOMALOUS = "ANOMALOUS"
    MISSING = "MISSING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class SignalLockError(ValueError):
    """Sinyal kilidi ihlali: VolumeMetrics.signal None disinda olamaz."""


def _coerce_turnover_type(value) -> TurnoverType:
    if isinstance(value, TurnoverType):
        return value
    return TurnoverType(str(value))


def _coerce_status(value) -> VolumeStatus:
    if isinstance(value, VolumeStatus):
        return value
    return VolumeStatus(str(value))


@dataclass
class VolumeConfig:
    """Hacim modulu esik/ayar konfigurasyonu.

    window:              ortalama penceresi (islem gunu sayisi, vars. 20)
    min_valid_days:      oran uretmek icin minimum gecerli gun (vars. 5)
    increasing_threshold: INCREASING alt esigi (vars. 1.3)
    high_threshold:      HIGH alt esigi (vars. 2.0)
    anomalous_threshold: ANOMALOUS alt esigi (vars. 5.0)
    estimated_label_required: tahmin uretilen her cikti nesnesinde kaynak
                         etiketi (turnover_type=ESTIMATED + is_estimated)
                         zorunlu (vars. True)
    official_sources:    resmi (OFFICIAL) sayilan kaynak adlari (kucuk harf)
    turnover_fields:     kaynak kaydinda TL hacim alani adaylari
    """

    window: int = 20
    min_valid_days: int = 5
    increasing_threshold: float = 1.3
    high_threshold: float = 2.0
    anomalous_threshold: float = 5.0
    estimated_label_required: bool = True
    official_sources: frozenset = frozenset({"bist", "borsa_istanbul", "official"})
    turnover_fields: tuple = ("turnover_try", "turnover", "tl_turnover")

    def __post_init__(self) -> None:
        if self.window <= 0:
            raise ValueError("window pozitif olmali: %r" % (self.window,))
        if self.min_valid_days <= 0:
            raise ValueError(
                "min_valid_days pozitif olmali: %r" % (self.min_valid_days,)
            )
        if not (0.0 < self.increasing_threshold <= self.high_threshold <= self.anomalous_threshold):
            raise ValueError(
                "esikler artan sirada olmali: %r < %r < %r"
                % (
                    self.increasing_threshold,
                    self.high_threshold,
                    self.anomalous_threshold,
                )
            )
        object.__setattr__(
            self, "official_sources", frozenset(s.lower() for s in self.official_sources)
        )
        object.__setattr__(self, "turnover_fields", tuple(self.turnover_fields))


@dataclass
class VolumeBar:
    """Tek gunluk ayrimli hacim kaydi (SPEC bolum 3).

    volume_units:          el degisen pay adedi; None = hacim bilinmiyor
    turnover_try:          kaynaktan GEREK TL hacim (OFFICIAL/PROVIDER)
    estimated_turnover_try: formulle hesaplanan TAHMIN (ESTIMATED)
    turnover_type:         TurnoverType
    is_estimated:          True sadece ESTIMATED'de
    is_trading_day:        True/False/None (bilinmiyor)
    missing_reason:        None | NO_DATA | SOURCE_ERROR | HOLIDAY

    Katı ayrim kurallari (__post_init__ ile zorlanir):
    - ESTIMATED ise turnover_try daima None (tahmin gercek hacim etiketi
      tasiyamaz) ve is_estimated True olmali.
    - OFFICIAL/PROVIDER ise is_estimated False ve estimated alani None olmali.
    - estimated_turnover_try doluysa turnover_type ESTIMATED olmali.
    """

    stock_id: str
    trade_date: str
    volume_units: Optional[int] = None
    turnover_try: Optional[float] = None
    estimated_turnover_try: Optional[float] = None
    turnover_type: TurnoverType = TurnoverType.MISSING
    source: str = ""
    is_estimated: bool = False
    is_trading_day: Optional[bool] = None
    missing_reason: Optional[str] = None

    def __post_init__(self) -> None:
        self.turnover_type = _coerce_turnover_type(self.turnover_type)
        if self.missing_reason is not None and self.missing_reason not in MISSING_REASONS:
            raise ValueError("gecersiz missing_reason: %r" % (self.missing_reason,))
        if self.volume_units is not None:
            self.volume_units = int(self.volume_units)
            if self.volume_units < 0:
                raise ValueError("volume_units negatif olamaz: %r" % (self.volume_units,))

        ttype = self.turnover_type
        if ttype == TurnoverType.ESTIMATED:
            if self.turnover_try is not None:
                raise ValueError(
                    "ESTIMATED kayitta turnover_try doldurulamaz: tahmin gercek "
                    "hacim etiketi tasiyamaz"
                )
            if not self.is_estimated:
                raise ValueError("ESTIMATED kayitta is_estimated=True olmali")
        elif ttype in (TurnoverType.OFFICIAL, TurnoverType.PROVIDER):
            if self.is_estimated:
                raise ValueError(
                    "%s kayit tahmin olarak etiketlenemez" % ttype.value
                )
            if self.estimated_turnover_try is not None:
                raise ValueError(
                    "%s kayitta estimated_turnover_try doldurulamaz" % ttype.value
                )
        else:  # MISSING
            if self.is_estimated:
                raise ValueError("MISSING kayit tahmin olarak etiketlenemez")
            if self.turnover_try is not None or self.estimated_turnover_try is not None:
                raise ValueError("MISSING kayitta hacim alani doldurulamaz")

    def to_dict(self) -> dict:
        """Serilestirme: tahmin alani her zaman 'estimated_' onekli kalir.

        Tahmin degeri hicbir zaman 'turnover_try' anahtarina tasinamaz —
        ayrim serilestirmede de korunur (SPEC bolum 4).
        """
        return {
            "stock_id": self.stock_id,
            "trade_date": self.trade_date,
            "volume_units": self.volume_units,
            "turnover_try": self.turnover_try,
            "estimated_turnover_try": self.estimated_turnover_try,
            "turnover_type": self.turnover_type.value,
            "source": self.source,
            "is_estimated": self.is_estimated,
            "is_trading_day": self.is_trading_day,
            "missing_reason": self.missing_reason,
        }


@dataclass
class VolumeMetrics:
    """Seri analizi sonucu (SPEC bolum 3).

    signal: HER ZAMAN None — SINYAL KILIDI. Bu modul AL/SAT/FAVORI uretmez;
    signal alanina None disinda deger verilmesi SignalLockError firlatir.

    used_days: ortalama penceresine giren gecerli islem gunu sayisi
    (SPEC bolum 5 'used_days raporu' — VolumeMetrics'e ek raporlama alani).
    """

    stock_id: str
    as_of_date: str
    last_volume_units: Optional[int] = None
    avg20_volume_units: Optional[float] = None
    volume_ratio_20: Optional[float] = None
    status: VolumeStatus = VolumeStatus.MISSING
    status_reason: Optional[str] = None
    used_days: Optional[int] = None
    signal: Optional[str] = None

    def __post_init__(self) -> None:
        self.status = _coerce_status(self.status)
        if self.signal is not None:
            raise SignalLockError(
                "VolumeMetrics.signal her zaman None olmali (sinyal kilidi): %r"
                % (self.signal,)
            )
        if self.avg20_volume_units is not None and self.avg20_volume_units < 0:
            raise ValueError("avg20_volume_units negatif olamaz")
        if self.last_volume_units is not None and self.last_volume_units < 0:
            raise ValueError("last_volume_units negatif olamaz")
