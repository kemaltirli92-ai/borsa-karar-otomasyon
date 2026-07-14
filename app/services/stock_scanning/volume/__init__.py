"""BLOK 10 - Hacim ve TL Islem Hacmi modulu (volume paketi).

Ayrimlar:
- volume_units (pay adedi) vs TL islem hacmi (turnover_try gercek /
  estimated_turnover_try tahmin) — asla karistirilmaz.
- Gercek sifir hacim (volume_units=0) vs eksik hacim (volume_units=None).
- Tatil/kaynak hatasi pencereye sifir girmez; pencere gecerli gunlerden kayar.

SINYAL KILIDI: VolumeMetrics.signal HER ZAMAN None; bu pakette AL/SAT/FAVORI
ureten hicbir kod yolu yoktur.

Gercek ag YOK; stdlib only; deterministik (saat enjekte).
"""
from .analyzer import (
    EMPTY_SERIES,
    REAL_ZERO,
    DuplicateDateError,
    GapReport,
    SeriesOrderError,
    VolumeAnalyzer,
)
from .classifier import (
    LAST_VOLUME_MISSING,
    RATIO_UNDEFINED,
    ZERO_VOLUME_EXPLAINED,
    ZERO_VOLUME_WITHOUT_EXPLANATION,
    classify_volume,
)
from .models import (
    HOLIDAY,
    MISSING_REASONS,
    NO_DATA,
    SOURCE_ERROR,
    SignalLockError,
    TurnoverType,
    VolumeBar,
    VolumeConfig,
    VolumeMetrics,
    VolumeStatus,
)
from .ratio import (
    INSUFFICIENT_WINDOW,
    avg_volume,
    compute_ratio_20,
    valid_volume,
    volume_ratio,
    window_volumes,
)
from .turnover import estimate_turnover, read_field, resolve_turnover

__all__ = [
    # models
    "HOLIDAY",
    "MISSING_REASONS",
    "NO_DATA",
    "SOURCE_ERROR",
    "SignalLockError",
    "TurnoverType",
    "VolumeBar",
    "VolumeConfig",
    "VolumeMetrics",
    "VolumeStatus",
    # turnover
    "estimate_turnover",
    "read_field",
    "resolve_turnover",
    # ratio
    "INSUFFICIENT_WINDOW",
    "avg_volume",
    "compute_ratio_20",
    "valid_volume",
    "volume_ratio",
    "window_volumes",
    # classifier
    "LAST_VOLUME_MISSING",
    "RATIO_UNDEFINED",
    "ZERO_VOLUME_EXPLAINED",
    "ZERO_VOLUME_WITHOUT_EXPLANATION",
    "classify_volume",
    # analyzer
    "EMPTY_SERIES",
    "REAL_ZERO",
    "DuplicateDateError",
    "GapReport",
    "SeriesOrderError",
    "VolumeAnalyzer",
]
