"""BLOK 8 - Fiyat toplama konfigurasyonu (config.py).

PriceCollectionConfig: yonetici ayarindan degistirilebilir fiyat kaynak
konfigi (SPEC bolum 5).

- source_priority: kaynak deneme sirasi (set_priority ile degistirilir;
  bilinmeyen kaynak adi REDDEDILIR).
- validation_source: kaynaklar arasi dogrulama kaynagi (or. "google").
- close_tolerance_pct: kapanis farki toleransi (yuzde).
- bootstrap_days: ilk kurulum gun sayisi (min 260).
- recheck_days: her guncellemede tekrar kontrol edilecek son gun sayisi (10).
- allowed_currencies: kabul edilen para birimleri (varsayilan {"TRY"}).
- stale_days_limit: eski veri esigi (gun).

to_dict/from_dict ile JSON'a/yonetici paneline yazilip okunabilir.
Dis bagimlilik yoktur (stdlib: dataclasses, typing).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Set

from .validator import is_iso_currency

KNOWN_SOURCES = ("licensed", "yfinance", "google")

MIN_BOOTSTRAP_DAYS = 260


class ConfigError(ValueError):
    """Gecersiz fiyat toplama konfigurasyonu."""


@dataclass
class PriceCollectionConfig:
    """Fiyat verisi toplama ayarlari (yonetici panelinden duzenlenebilir)."""

    source_priority: List[str] = field(default_factory=lambda: ["licensed", "yfinance"])
    validation_source: str = "google"
    close_tolerance_pct: float = 0.5
    bootstrap_days: int = MIN_BOOTSTRAP_DAYS
    recheck_days: int = 10
    allowed_currencies: Set[str] = field(default_factory=lambda: {"TRY"})
    stale_days_limit: int = 7

    def __post_init__(self) -> None:
        self.source_priority = list(self.source_priority)
        self.allowed_currencies = set(self.allowed_currencies)
        self._validate()

    # ------------------------------------------------------------------ #
    # Dogrulama
    # ------------------------------------------------------------------ #
    def _validate_priority(self, priority) -> None:
        if not isinstance(priority, (list, tuple)) or not priority:
            raise ConfigError("source_priority bos olamaz")
        unknown = [name for name in priority if name not in KNOWN_SOURCES]
        if unknown:
            raise ConfigError(
                "bilinmeyen kaynak adi: %s (bilinenler: %s)"
                % (", ".join(str(u) for u in unknown), ", ".join(KNOWN_SOURCES))
            )

    def _validate(self) -> None:
        self._validate_priority(self.source_priority)
        if self.validation_source not in KNOWN_SOURCES:
            raise ConfigError(
                "bilinmeyen dogrulama kaynagi: %r" % (self.validation_source,)
            )
        if isinstance(self.close_tolerance_pct, bool) or not isinstance(
            self.close_tolerance_pct, (int, float)
        ) or self.close_tolerance_pct < 0:
            raise ConfigError("close_tolerance_pct negatif olamaz")
        if isinstance(self.bootstrap_days, bool) or not isinstance(self.bootstrap_days, int):
            raise ConfigError("bootstrap_days tamsayi olmali")
        if self.bootstrap_days < MIN_BOOTSTRAP_DAYS:
            raise ConfigError(
                "bootstrap_days en az %d olmali (verilen: %d)"
                % (MIN_BOOTSTRAP_DAYS, self.bootstrap_days)
            )
        if isinstance(self.recheck_days, bool) or not isinstance(self.recheck_days, int):
            raise ConfigError("recheck_days tamsayi olmali")
        if self.recheck_days < 1:
            raise ConfigError("recheck_days en az 1 olmali")
        if isinstance(self.stale_days_limit, bool) or not isinstance(
            self.stale_days_limit, int
        ) or self.stale_days_limit < 0:
            raise ConfigError("stale_days_limit negatif olamaz")
        if not self.allowed_currencies:
            raise ConfigError("allowed_currencies bos olamaz")
        bad = [c for c in self.allowed_currencies if not is_iso_currency(c)]
        if bad:
            raise ConfigError(
                "gecersiz para birimi kodu: %s" % ", ".join(str(c) for c in bad)
            )

    # ------------------------------------------------------------------ #
    # Yonetici ayari
    # ------------------------------------------------------------------ #
    def set_priority(self, priority) -> None:
        """Kaynak onceligini yonetici ayarindan degistirir.

        Bilinmeyen kaynak adi iceren liste ConfigError ile REDDEDILIR;
        bu durumda mevcut oncelik korunur.
        """
        self._validate_priority(priority)
        self.source_priority = list(priority)

    # ------------------------------------------------------------------ #
    # Serilestirme
    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict:
        """JSON'a yazilabilir sozluk (allowed_currencies sirali liste)."""
        return {
            "source_priority": list(self.source_priority),
            "validation_source": self.validation_source,
            "close_tolerance_pct": float(self.close_tolerance_pct),
            "bootstrap_days": int(self.bootstrap_days),
            "recheck_days": int(self.recheck_days),
            "allowed_currencies": sorted(self.allowed_currencies),
            "stale_days_limit": int(self.stale_days_limit),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PriceCollectionConfig":
        """Sozlukten config olusturur; gecersiz degerler ConfigError firlatir."""
        if not isinstance(data, dict):
            raise ConfigError("config verisi sozluk olmali")
        known_keys = {
            "source_priority",
            "validation_source",
            "close_tolerance_pct",
            "bootstrap_days",
            "recheck_days",
            "allowed_currencies",
            "stale_days_limit",
        }
        kwargs = {k: v for k, v in data.items() if k in known_keys}
        return cls(**kwargs)
