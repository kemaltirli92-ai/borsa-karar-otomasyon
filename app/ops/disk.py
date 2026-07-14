"""BLOK 21 - Guvenlik, Log, Izleme ve Yedekleme: disk kullanim kontrolu.

Kurallar ozeti:
- stdlib only (shutil, dataclasses); gercek ag/subprocess YOK.
- Deterministik: disk istatistikleri stat_provider ile ENJEKTE edilir
  (default shutil.disk_usage sarici); testler gercek diske bagli degildir.
- Esik kurali: used_pct >= critical_pct -> CRITICAL; >= warn_pct -> WARN;
  aksi halde OK (sinir degerleri WARN/CRITICAL'a dahildir).
- total = 0 ise used_pct = 0.0 ve seviye OK (sifira bolunme YOK).
- Puan/bildirim kilidi: bu modul puan/sinyal/musteri bildirimi uretmez.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

DISK_OK = "OK"
DISK_WARN = "WARN"
DISK_CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class DiskStatus:
    """Disk kullanim goruntusu (degistirilemez)."""

    path: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    used_pct: float
    level: str


def _default_stat_provider(path: str) -> Tuple[int, int, int]:
    """shutil.disk_usage sarici -> (total, used, free)."""
    usage = shutil.disk_usage(path)
    return (int(usage.total), int(usage.used), int(usage.free))


def check_disk_usage(
    path: str = "/",
    warn_pct: float = 80.0,
    critical_pct: float = 95.0,
    stat_provider: Optional[Callable[[str], Tuple[int, int, int]]] = None,
) -> DiskStatus:
    """Disk kullanim seviyesini hesapla (stat_provider enjekte edilebilir)."""
    provider = stat_provider or _default_stat_provider
    total, used, free = provider(path)
    total = int(total)
    used = int(used)
    free = int(free)
    if total <= 0:
        used_pct = 0.0
        level = DISK_OK
    else:
        used_pct = (used / total) * 100.0
        if used_pct >= critical_pct:
            level = DISK_CRITICAL
        elif used_pct >= warn_pct:
            level = DISK_WARN
        else:
            level = DISK_OK
    return DiskStatus(
        path=str(path),
        total_bytes=total,
        used_bytes=used,
        free_bytes=free,
        used_pct=used_pct,
        level=level,
    )
