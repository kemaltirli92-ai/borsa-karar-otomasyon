"""BLOK 10 - TL hacim ayrimi (turnover.py).

resolve_turnover(raw_record, ohlc=None, config=None)
    -> (turnover_try, estimated_turnover_try, turnover_type)

Kurallar (SPEC bolum 4):
1. Kaynakta resmi/saglayici TL hacim alani (config.turnover_fields) varsa
   -> turnover_try dolar, estimated_turnover_try=None,
      turnover_type = OFFICIAL (kaynak config.official_sources icindeyse)
                    | PROVIDER (diger kaynaklar).
2. TL hacim alani yoksa ve hacim (adet) varsa
   -> estimated_turnover_try = ((open+high+low+close)/4) * volume_units,
      turnover_type = ESTIMATED, turnover_try = None (KARISTIRILMAZ).
3. Hacim yoksa -> turnover_type = MISSING, ikisi de None.

Tahmin asla "gercek hacim" etiketi tasiyamaz: ESTIMATED yolunda donen
turnover_try daima None'dir ve VolumeBar uzerinde de None kalir.

raw_record duck-typing ile okunur: dict (anahtar) veya nitelikli nesne
(BLOK 8 PriceBar: open/high/low/close/volume/source).
"""
from __future__ import annotations

from typing import Optional, Tuple

from .models import TurnoverType, VolumeConfig


def read_field(record, *names):
    """Ham kayittan alan okur (dict anahtari veya nitelik). Yoksa None."""
    for name in names:
        if isinstance(record, dict):
            if name in record:
                return record[name]
        elif hasattr(record, name):
            return getattr(record, name)
    return None


def _source_label(record) -> str:
    source = read_field(record, "source")
    return str(source) if source is not None else ""


def _find_turnover_value(record, config: VolumeConfig):
    """Kaynak kaydinda TL hacim alani arar; bulursa float degeri doner."""
    for field_name in config.turnover_fields:
        value = read_field(record, field_name)
        if value is not None:
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ValueError(
                    "TL hacim alani sayisal degil: %s=%r" % (field_name, value)
                )
            if value < 0:
                raise ValueError("TL hacim negatif olamaz: %r" % (value,))
            return value
    return None


def _read_volume_units(record) -> Optional[int]:
    volume = read_field(record, "volume_units", "volume")
    if volume is None:
        return None
    try:
        volume = int(volume)
    except (TypeError, ValueError):
        raise ValueError("hacim (adet) sayisal degil: %r" % (volume,))
    if volume < 0:
        raise ValueError("hacim (adet) negatif olamaz: %r" % (volume,))
    return volume


def estimate_turnover(ohlc, volume_units: int) -> float:
    """Tahmin formulu: ((O+H+L+C)/4) x V.

    ohlc: (open, high, low, close) — hicbiri None olamaz.
    """
    if ohlc is None or len(ohlc) != 4 or any(x is None for x in ohlc):
        raise ValueError(
            "tahmin icin tam OHLC gerekli (open, high, low, close): %r" % (ohlc,)
        )
    open_, high, low, close = (float(x) for x in ohlc)
    typical_price = (open_ + high + low + close) / 4.0
    return typical_price * int(volume_units)


def resolve_turnover(
    raw_record, ohlc=None, config: Optional[VolumeConfig] = None
) -> Tuple[Optional[float], Optional[float], TurnoverType]:
    """Ham kayit icin TL hacim ayrimini cozer (SPEC bolum 4).

    Donus: (turnover_try, estimated_turnover_try, turnover_type).
    - OFFICIAL/PROVIDER: turnover_try dolu, estimated None.
    - ESTIMATED:         estimated dolu, turnover_try=None (KARISTIRILMAZ).
    - MISSING:           ikisi de None (hacim yok).
    """
    cfg = config or VolumeConfig()

    # 1) Kaynakta resmi/saglayici TL hacim alani var mi?
    turnover_value = _find_turnover_value(raw_record, cfg)
    if turnover_value is not None:
        source = _source_label(raw_record).lower()
        ttype = (
            TurnoverType.OFFICIAL
            if source in cfg.official_sources
            else TurnoverType.PROVIDER
        )
        return turnover_value, None, ttype

    # 2) Hacim (adet) var mi?
    volume_units = _read_volume_units(raw_record)
    if volume_units is None:
        return None, None, TurnoverType.MISSING

    # 3) Tahmin uret (OHLC kayittan veya parametreden)
    if ohlc is None:
        ohlc = (
            read_field(raw_record, "open"),
            read_field(raw_record, "high"),
            read_field(raw_record, "low"),
            read_field(raw_record, "close"),
        )
    estimated = estimate_turnover(ohlc, volume_units)
    return None, estimated, TurnoverType.ESTIMATED
