"""BLOK 10 - Hacim durum siniflandirici (classifier.py).

classify_volume(...) -> (VolumeStatus, reason)

Esikler config'ten (VolumeConfig, varsayilanlar):
- ratio >= anomalous_threshold (5.0)  -> ANOMALOUS
- ratio >= high_threshold (2.0)       -> HIGH
- ratio >= increasing_threshold (1.3) -> INCREASING
- 0 <= ratio < increasing_threshold   -> NORMAL
- son gun hacmi MISSING               -> MISSING
- gercek sifir hacim + aciklama yok   -> REVIEW_REQUIRED (islem durdurma suphesi)
- gercek sifir hacim + aciklama var   -> NORMAL (aciklanmis sifir)
- hacim biliniyor ama ratio tanim belirsiz  -> REVIEW_REQUIRED (RATIO_UNDEFINED)

ANOMALOUS + tek gunluk izole ani sicrama (onceki gunler ANOMALOUS degil)
-> durum yine ANOMALOUS kalir; yumusatma/indirgeme YOKTUR.

SINYAL KILIDI: bu modul (ve tum volume paketi) AL/SAT/FAVORI ciktisi
uretmez. Donus degeri sadece (VolumeStatus, reason) ikilisidir; sinyal
tasiyan tek alan VolumeMetrics.signal'dir ve o da HER ZAMAN None'dir
(models.SignalLockError ile zorlanir).
"""
from __future__ import annotations

from typing import Optional, Tuple

from .models import VolumeConfig, VolumeStatus

# Neden kodlari
LAST_VOLUME_MISSING = "LAST_VOLUME_MISSING"
ZERO_VOLUME_WITHOUT_EXPLANATION = "ZERO_VOLUME_WITHOUT_EXPLANATION"
ZERO_VOLUME_EXPLAINED = "ZERO_VOLUME_EXPLAINED"
RATIO_UNDEFINED = "RATIO_UNDEFINED"


def _ge_reason(threshold: float) -> str:
    return "ratio>=%g" % threshold


def _lt_reason(threshold: float) -> str:
    return "ratio<%g" % threshold


def classify_volume(
    metrics=None,
    config: Optional[VolumeConfig] = None,
    *,
    last_volume: Optional[int] = None,
    avg20: Optional[float] = None,
    ratio: Optional[float] = None,
    zero_explanation: Optional[str] = None,
    missing_reason: Optional[str] = None,
) -> Tuple[VolumeStatus, str]:
    """Hacim durumunu siniflandirir.

    metrics: VolumeMetrics benzeri nesne (duck-typing: last_volume_units,
             avg20_volume_units, volume_ratio_20, missing_reason nitelikleri)
             verilirse degerler oradan okunur; acik kwargs degerleri
             ustune yazar. metrics None ise kwargs zorunludur.

    Donus: (VolumeStatus, neden_kodu). Esikler config'ten okunur.
    """
    cfg = config or VolumeConfig()

    if metrics is not None:
        if last_volume is None:
            last_volume = getattr(metrics, "last_volume_units", None)
        if avg20 is None:
            avg20 = getattr(metrics, "avg20_volume_units", None)
        if ratio is None:
            ratio = getattr(metrics, "volume_ratio_20", None)
        if missing_reason is None:
            missing_reason = getattr(metrics, "missing_reason", None)

    # 1) Son gun hacmi bilinmiyor -> MISSING
    if last_volume is None:
        return VolumeStatus.MISSING, (missing_reason or LAST_VOLUME_MISSING)

    last_volume = int(last_volume)
    if last_volume < 0:
        raise ValueError("last_volume negatif olamaz: %r" % (last_volume,))

    # 2) Gercek sifir hacim: aciklama yoksa REVIEW_REQUIRED
    #    (islem durdurma suphesi), aciklama varsa NORMAL.
    if last_volume == 0:
        if zero_explanation:
            return VolumeStatus.NORMAL, ZERO_VOLUME_EXPLAINED
        return VolumeStatus.REVIEW_REQUIRED, ZERO_VOLUME_WITHOUT_EXPLANATION

    # 3) Hacim var ama oran tanim belirsiz (avg20==0 / yetersiz pencere / None)
    if ratio is None:
        return VolumeStatus.REVIEW_REQUIRED, RATIO_UNDEFINED

    ratio = float(ratio)
    if ratio < 0:
        raise ValueError("ratio negatif olamaz: %r" % (ratio,))

    # 4) Esik siniflandirmasi (config'ten). Izole tek gunluk sicrama da
    #    dahil her ratio>=anomalous ANOMALOUS kalir (indirgeme yok).
    if ratio >= cfg.anomalous_threshold:
        return VolumeStatus.ANOMALOUS, _ge_reason(cfg.anomalous_threshold)
    if ratio >= cfg.high_threshold:
        return VolumeStatus.HIGH, _ge_reason(cfg.high_threshold)
    if ratio >= cfg.increasing_threshold:
        return VolumeStatus.INCREASING, _ge_reason(cfg.increasing_threshold)
    return VolumeStatus.NORMAL, _lt_reason(cfg.increasing_threshold)
