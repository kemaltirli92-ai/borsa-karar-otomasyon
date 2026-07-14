"""BLOK 8 - Fiyat Verisi Toplama modulu (price_collection paketi).

Bilesenler:
- sources.PriceBar / PriceSource / LicensedSource / YFinanceSource /
  GoogleFinanceSource / SourceUnavailableError: veri modeli + fetcher
  enjeksiyonlu kaynak stub'lari (gercek ag YOK).
- config.PriceCollectionConfig / ConfigError: yonetici ayarindan
  degistirilebilir kaynak onceligi, toleranslar; to_dict/from_dict.
- validator: bozuk bar reddi (high<low, negatif fiyat, 3 harf ISO para
  birimi), kapanis farki tolerans hesabi.
- storage.PriceStorage / WriteResult: BLOK 7 stock_prices_daily tablosuna
  raw yazim, unique anahtarla kopya engeli, bellek ici mod (conn=None).
- collector.PriceCollector / CollectionResult / ValidationResult:
  bootstrap (260+ gun), incremental_update + son 10 gun recheck,
  validate_against (kaynaklar arasi dogrulama).

Dis bagimlilik yoktur (stdlib). Dosya/identifier ASCII; docstring'ler
Turkce. Deterministik: saat her yerde enjekte edilebilir.
"""
from .collector import (
    BAR_REJECTED,
    FAILED,
    OK,
    PARTIAL,
    PRICE_DATA_MISSING,
    PRICE_SOURCE_DIVERGENCE,
    RECHECK_UPDATED,
    SOURCE_SWITCHED,
    STALE_PRICE_DATA,
    VALIDATION_SOURCE_UNAVAILABLE,
    WRONG_CURRENCY,
    CollectionResult,
    PriceCollector,
    ValidationResult,
)
from .config import KNOWN_SOURCES, MIN_BOOTSTRAP_DAYS, ConfigError, PriceCollectionConfig
from .sources import (
    BAR_SKIPPED,
    DEFAULT_CURRENCY,
    GoogleFinanceSource,
    LicensedSource,
    PriceBar,
    PriceSource,
    SourceUnavailableError,
    YFinanceSource,
)
from .storage import PriceStorage, WriteResult
from .validator import (
    BAD_CURRENCY,
    BAD_DATE,
    HIGH_LT_LOW,
    HIGH_LT_MAX_OC,
    NEGATIVE_PRICE,
    NEGATIVE_VOLUME,
    close_diff_pct,
    is_iso_currency,
    is_iso_date,
    is_valid_bar,
    validate_bar,
    within_close_tolerance,
)

__all__ = [
    # sources
    "PriceBar",
    "PriceSource",
    "LicensedSource",
    "YFinanceSource",
    "GoogleFinanceSource",
    "SourceUnavailableError",
    "DEFAULT_CURRENCY",
    "BAR_SKIPPED",
    # config
    "PriceCollectionConfig",
    "ConfigError",
    "KNOWN_SOURCES",
    "MIN_BOOTSTRAP_DAYS",
    # validator
    "validate_bar",
    "is_valid_bar",
    "is_iso_currency",
    "is_iso_date",
    "close_diff_pct",
    "within_close_tolerance",
    "NEGATIVE_PRICE",
    "NEGATIVE_VOLUME",
    "HIGH_LT_LOW",
    "HIGH_LT_MAX_OC",
    "BAD_CURRENCY",
    "BAD_DATE",
    # storage
    "PriceStorage",
    "WriteResult",
    # collector
    "PriceCollector",
    "CollectionResult",
    "ValidationResult",
    "OK",
    "PRICE_DATA_MISSING",
    "PARTIAL",
    "FAILED",
    "SOURCE_SWITCHED",
    "PRICE_SOURCE_DIVERGENCE",
    "VALIDATION_SOURCE_UNAVAILABLE",
    "STALE_PRICE_DATA",
    "WRONG_CURRENCY",
    "BAR_REJECTED",
    "RECHECK_UPDATED",
]
