"""BLOK 10 - 20 gunluk hacim orani (ratio.py).

Temel kurallar (SPEC bolum 5):
- Son gun KENDI ORTALAMASINA DAHIL EDILMEZ: ortalama, son gun HARIC onceki
  `window` gecerli islem gununun ortalamasidir (exclude_last varsayilan True).
- Eksik gun (NO_DATA/SOURCE_ERROR/HOLIDAY, yani hacmi bilinmeyen gun)
  ortalamaya KATILMAZ ve pencereyi doldurmaz: pencere gecerli gunlerden
  kayar. Tatil/kaynak hatasi SIFIR hacim olarak EKLENMEZ.
- Gercek sifir hacim (islem gunu, volume_units=0, missing_reason yok)
  ortalamaya 0 olarak KATILIR; eksik hacim (volume_units=None) KATILMAZ.
  Ikisi ayrıştirilir (VolumeBar.volume_units=0 vs None).
- volume_ratio: avg20 > 0 ise last/avg20; avg20 == 0 veya taraflardan biri
  None ise None (sifira bolme yok).
- compute_ratio_20: pencerede window'dan az gecerli gun varsa eldekiyle
  hesaplar ama used_days raporlar; min_valid_days (vars. 5) altindaysa
  ratio=None (INSUFFICIENT_WINDOW durumunu cagiran taraf raporlar).

Bar'lar duck-typing ile okunur: volume_units, missing_reason, is_trading_day
nitelikleri (VolumeBar, SimpleNamespace veya dict).
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

# compute_ratio_20 yetersiz pencere nedeni (cagiran taraf status_reason'a tasir)
INSUFFICIENT_WINDOW = "INSUFFICIENT_WINDOW"


def _get(bar, name):
    """Bar'dan alan okur (dict anahtari veya nitelik)."""
    if isinstance(bar, dict):
        return bar.get(name)
    return getattr(bar, name, None)


def valid_volume(bar) -> Optional[int]:
    """Bar'in gecerli hacim degeri; gecersizse None.

    Gecersiz (ortalamaya katilmaz):
    - volume_units None (hacim bilinmiyor / eksik gun)
    - missing_reason dolu (NO_DATA/SOURCE_ERROR/HOLIDAY)
    - is_trading_day acikca False (tatil)

    Gecerli sifir: volume_units=0 ve yukaridakilerden hicbiri yok ->
    0 doner (ortalamaya 0 olarak katilir). Boylece gercek sifir ile
    eksik hacim AYRISTIRILIR.
    """
    volume = _get(bar, "volume_units")
    if volume is None:
        return None
    if _get(bar, "missing_reason") is not None:
        return None
    if _get(bar, "is_trading_day") is False:
        return None
    volume = int(volume)
    if volume < 0:
        raise ValueError("volume_units negatif olamaz: %r" % (volume,))
    return volume


def window_volumes(
    bars: Sequence, window: int = 20, exclude_last: bool = True
) -> List[int]:
    """Pencereye giren gecerli hacim degerleri (tarih sirasi korunur).

    exclude_last=True ise serinin SON BAR'I adaylardan cikarilir (son gun
    kendi ortalamasina dahil edilmez). Eksik gunler atlanir; pencere
    gecerli gunlerden kayar (son `window` gecerli deger alinir).
    """
    if window <= 0:
        raise ValueError("window pozitif olmali: %r" % (window,))
    seq = list(bars)
    if exclude_last and seq:
        seq = seq[:-1]
    values: List[int] = []
    for bar in seq:
        volume = valid_volume(bar)
        if volume is not None:
            values.append(volume)
    return values[-window:]


def avg_volume(
    bars: Sequence, window: int = 20, exclude_last: bool = True
) -> Optional[float]:
    """Son gun haric onceki `window` gecerli islem gununun hacim ortalamasi.

    Gecerli gun yoksa None. Gercek sifir hacimler 0 olarak katilir.
    """
    values = window_volumes(bars, window=window, exclude_last=exclude_last)
    if not values:
        return None
    return sum(values) / len(values)


def volume_ratio(last_volume: Optional[float], avg20: Optional[float]) -> Optional[float]:
    """Hacim orani = son gun hacmi / avg20.

    avg20 == 0 -> None (tanim belirsiz, sifira bolme yok). Taraflardan biri
    None ise None.
    """
    if last_volume is None or avg20 is None:
        return None
    if avg20 == 0:
        return None
    return last_volume / avg20


def compute_ratio_20(
    series: Sequence, window: int = 20, min_valid_days: int = 5
) -> Tuple[Optional[float], Optional[float], int]:
    """Seri icin (volume_ratio_20, avg20_volume_units, used_days) uretir.

    - used_days: pencereye giren gecerli islem gunu sayisi (en fazla window).
    - Pencerede window'dan az gecerli gun varsa eldekiyle hesaplanir ve
      used_days raporlanir.
    - used_days < min_valid_days ise ratio=None (yetersiz pencere; cagiran
      taraf INSUFFICIENT_WINDOW olarak isaretler). avg20 yine de raporlanir
      (gecerli gun varsa), tanilama amaclidir.
    - avg20 == 0 ise ratio=None (sifira bolme yok).
    """
    if min_valid_days <= 0:
        raise ValueError("min_valid_days pozitif olmali: %r" % (min_valid_days,))
    bars = list(series)
    values = window_volumes(bars, window=window, exclude_last=True)
    used_days = len(values)
    avg20 = (sum(values) / used_days) if used_days else None
    last = valid_volume(bars[-1]) if bars else None
    if used_days < min_valid_days:
        return None, avg20, used_days
    return volume_ratio(last, avg20), avg20, used_days
