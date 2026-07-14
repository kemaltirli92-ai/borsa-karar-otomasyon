"""BLOK 21 - Guvenlik, Log, Izleme ve Yedekleme: gunluk yedekleme (motor soyutlamasi).

Kurallar ozeti:
- stdlib only (json, os, zoneinfo, dataclasses, datetime); gercek
  subprocess/ag YOK — pg_dump gibi dis araclar enjekte dump_fn ile
  soyutlanir (testlerde sahte fonksiyon).
- Deterministik: clock enjekte edilir; gun siniri Europe/Istanbul
  (zoneinfo) ile hesaplanir; state dosyasi enjekte state_path'te tutulur.
- BLOK 7 arayuzu yeniden kullanilir (DEGISTIRILMEZ): backup_db.
- is_due: bugun (Istanbul gunu) icin basarili yedek YOKSA True; ayni gun
  2. cagrida False. run_daily: due degilse None dondurur.
- retention_count budamasi state dosyasindan izlenir: en eski kayitlar
  silinir (dosyasi da best-effort kaldirilir).
- Puan/bildirim kilidi: bu modul puan/sinyal/musteri bildirimi uretmez.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from app.services.stock_scanning.db.backup import backup_db

ENGINE_SQLITE = "sqlite"
ENGINE_POSTGRES = "postgres"

ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")


def _utc_now() -> datetime:
    """Default clock sarici (enjekte clock kullanilmadiginda)."""
    return datetime.now(timezone.utc)


def _iso_z(value: datetime) -> str:
    """datetime'i ISO-8601 'Z' bicimine cevirir."""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat() + "Z"


def _stamp(value: datetime) -> str:
    """Yedek kimligi icin gun-saat damgasi: YYYYMMDD-HHMMSS."""
    return value.strftime("%Y%m%d-%H%M%S")


@dataclass(frozen=True)
class BackupRecord:
    """Tek yedegi tanimlayan kayit (degistirilemez)."""

    backup_id: str
    engine: str
    path: str
    created_at: str
    size_bytes: int


class SqliteBackupEngine:
    """Birincil motor: BLOK 7 backup_db ile SQLite dosya kopyasi + manifest."""

    def __init__(
        self,
        db_path: str,
        backup_dir: str,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self.db_path = str(db_path)
        self.backup_dir = str(backup_dir)
        self._clock = clock or _utc_now

    def run(self, now: datetime) -> BackupRecord:
        backup_id = "bkp-%s-%s" % (_stamp(now), ENGINE_SQLITE)
        created_at = _iso_z(now)
        result = backup_db(self.db_path, self.backup_dir, clock=lambda: created_at)
        path = result.get("backup_path") or ""
        size = os.path.getsize(path) if path and os.path.isfile(path) else 0
        return BackupRecord(
            backup_id=backup_id,
            engine=ENGINE_SQLITE,
            path=str(path),
            created_at=created_at,
            size_bytes=int(size),
        )


class PostgresBackupEngine:
    """pg_dump-UYUMLU SQL dump motoru; gercek dis arac cagrisi YOK.

    dump_fn: callable(out_path: Path) -> None — SQL dump'u out_path'e
    yazar (ENJEKTE; testlerde sahte fonksiyon).
    """

    def __init__(
        self,
        backup_dir: str,
        dump_fn: Callable[[Path], None],
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self.backup_dir = str(backup_dir)
        self._dump_fn = dump_fn
        self._clock = clock or _utc_now

    def run(self, now: datetime) -> BackupRecord:
        os.makedirs(self.backup_dir, exist_ok=True)
        backup_id = "bkp-%s-%s" % (_stamp(now), ENGINE_POSTGRES)
        out_path = Path(self.backup_dir) / (backup_id + ".sql")
        self._dump_fn(out_path)
        size = os.path.getsize(str(out_path)) if out_path.is_file() else 0
        return BackupRecord(
            backup_id=backup_id,
            engine=ENGINE_POSTGRES,
            path=str(out_path),
            created_at=_iso_z(now),
            size_bytes=int(size),
        )


class DailyBackupScheduler:
    """Gunluk (Europe/Istanbul gunu) yedekleme zamanlayici + budama.

    state_path: son yedek kayitlarinin JSON'da tutuldugu dosya
    (deterministik test icin enjekte edilir).
    """

    def __init__(
        self,
        engine,
        clock: Optional[Callable[[], datetime]] = None,
        retention_count: int = 14,
        state_path: Optional[str] = None,
    ):
        self.engine = engine
        self._clock = clock or _utc_now
        self.retention_count = int(retention_count)
        self.state_path = str(state_path) if state_path else None

    # ------------------------------------------------------------------ #
    # ic yardimcilar
    # ------------------------------------------------------------------ #
    def _now(self, now: Optional[datetime]) -> datetime:
        return now if now is not None else self._clock()

    @staticmethod
    def _istanbul_day(now: datetime) -> str:
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return now.astimezone(ISTANBUL_TZ).strftime("%Y-%m-%d")

    def _load_state(self) -> Dict[str, object]:
        if not self.state_path or not os.path.isfile(self.state_path):
            return {"records": []}
        try:
            with open(self.state_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (ValueError, OSError):
            return {"records": []}
        if not isinstance(data, dict):
            return {"records": []}
        records = data.get("records")
        if not isinstance(records, list):
            data["records"] = []
        return data

    def _save_state(self, state: Dict[str, object]) -> None:
        if not self.state_path:
            return
        parent = os.path.dirname(self.state_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(self.state_path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=True, indent=2, sort_keys=True)

    # ------------------------------------------------------------------ #
    # genel API
    # ------------------------------------------------------------------ #
    def is_due(self, now: Optional[datetime] = None) -> bool:
        """Bugun (Europe/Istanbul gunu) icin basarili yedek YOKSA True."""
        now = self._now(now)
        day = self._istanbul_day(now)
        state = self._load_state()
        for record in state.get("records", []):
            if isinstance(record, dict) and record.get("day") == day and record.get("ok"):
                return False
        return True

    def run_daily(self, now: Optional[datetime] = None) -> Optional[BackupRecord]:
        """Due degilse None; due ise yedek al + state guncelle + budama."""
        now = self._now(now)
        if not self.is_due(now):
            return None
        record = self.engine.run(now)
        day = self._istanbul_day(now)

        state = self._load_state()
        records: List[dict] = list(state.get("records", []))
        entry = asdict(record)
        entry["day"] = day
        entry["ok"] = True
        records.append(entry)

        # Budama: retention_count'tan fazla kayit en eskiden silinir
        # (yedek dosyasi best-effort kaldirilir; state dosyasindan izlenir).
        while len(records) > self.retention_count:
            old = records.pop(0)
            old_path = old.get("path") if isinstance(old, dict) else None
            if old_path:
                try:
                    os.remove(str(old_path))
                except OSError:
                    pass

        state["records"] = records
        self._save_state(state)
        return record
