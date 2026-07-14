"""BLOK 21 - Guvenlik, Log, Izleme ve Yedekleme: arsiv + saklama suresi.

Kurallar ozeti:
- stdlib only (os, pathlib, datetime); gercek ag/subprocess YOK.
- Deterministik: dosya yasina karar 'now' parametresi (default enjekte
  clock) ile verilir; testler gercek saate bagli degildir.
- Yalniz RAW_KINDS ("raw_html", "raw_api") budanır; STRUCTURED_KINDS
  ("price", "kap", "scan_result") KALICIdir — retention ASLA silmez.
- Dosya adi guvenli hale getirilir (path traversal engellenir: "..", "/",
  "\\" -> "_").
- Puan/bildirim kilidi: bu modul puan/sinyal/musteri bildirimi uretmez.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Union

RAW_KINDS = ("raw_html", "raw_api")  # sinirli saklama
STRUCTURED_KINDS = ("price", "kap", "scan_result")  # KALICI — retention ASLA silmez
ALL_KINDS = RAW_KINDS + STRUCTURED_KINDS

_SECONDS_PER_DAY = 86400.0


def _utc_now() -> datetime:
    """Default clock sarici (enjekte clock kullanilmadiginda)."""
    return datetime.now(timezone.utc)


def _safe_name(name: str) -> str:
    """Path traversal temizligi: '..', '/', '\\' -> '_'."""
    safe = str(name)
    for token in ("..", "/", "\\"):
        safe = safe.replace(token, "_")
    return safe or "_"


def _to_timestamp(value: datetime) -> float:
    """Naive datetime'i UTC kabul ederek epoch saniyesine cevirir."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


class ArchiveStore:
    """Kind bazli arsiv deposu + ham veri saklama suresi budamasi."""

    def __init__(
        self,
        root_dir: Union[str, Path],
        clock: Optional[Callable[[], datetime]] = None,
        raw_retention_days: int = 14,
    ):
        self.root = Path(root_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self._clock = clock or _utc_now
        self.raw_retention_days = int(raw_retention_days)
        for kind in ALL_KINDS:
            (self.root / kind).mkdir(exist_ok=True)

    def _kind_dir(self, kind: str) -> Path:
        if kind not in ALL_KINDS:
            raise ValueError("bilinmeyen arsiv turu: %r" % (kind,))
        return self.root / kind

    def put(self, kind: str, name: str, content: bytes) -> Path:
        """Icerigi kind/<guvenli-ad> olarak yazar; dosya yolunu dondurur."""
        target = self._kind_dir(kind) / _safe_name(name)
        target.write_bytes(bytes(content))
        return target

    def list(self, kind: str) -> List[Path]:
        """Kind altindaki dosyalari ad sirasiyla listeler."""
        kind_dir = self._kind_dir(kind)
        return sorted(p for p in kind_dir.iterdir() if p.is_file())

    def apply_retention(self, now: Optional[datetime] = None) -> Dict[str, object]:
        """RAW_KINDS icinde saklama suresi asmis dosyalari siler.

        STRUCTURED_KINDS'a ASLA dokunmaz. Yas karari 'now' (default clock())
        ile dosya mtime'i farkindan hesaplanir (deterministik).
        Rapor: {"deleted": [str...], "kept_raw": n, "kept_structured": n}.
        """
        now = now if now is not None else self._clock()
        now_ts = _to_timestamp(now)
        max_age = self.raw_retention_days * _SECONDS_PER_DAY

        deleted: List[str] = []
        kept_raw = 0
        for kind in RAW_KINDS:
            for path in sorted((self.root / kind).iterdir()):
                if not path.is_file():
                    continue
                age = now_ts - os.path.getmtime(str(path))
                if age > max_age:
                    try:
                        os.remove(str(path))
                        deleted.append(str(path))
                    except OSError:
                        kept_raw += 1
                else:
                    kept_raw += 1

        kept_structured = 0
        for kind in STRUCTURED_KINDS:
            for path in (self.root / kind).iterdir():
                if path.is_file():
                    kept_structured += 1

        return {
            "deleted": deleted,
            "kept_raw": kept_raw,
            "kept_structured": kept_structured,
        }
