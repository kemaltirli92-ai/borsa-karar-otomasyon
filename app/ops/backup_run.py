"""BLOK 21 - Guvenlik, Log, Izleme ve Yedekleme: gunluk yedekleme giris noktasi.

systemd xk100-backup.service tarafindan `python -m app.ops.backup_run`
ile cagrilir. Modul import edildiginde hicbir is YAPMAZ; yalnizca main()
cagrildiginda calisir (gercek DB yoksa bile import hatasiz yuklenir).

Kurallar ozeti:
- stdlib only; gercek ag/subprocess YOK: postgres motoru icin dump_fn
  burada yer tutucudur (gercek pg_dump entegrasyonu dis katmandadir;
  bu modul dis arac CALISTIRMAZ).
- Deterministik: scheduler/engine clock'u modul icindeki UTC saricidir;
  testler enjekte clock kullanir, main() testlerde cagrilmaz.
- env: BACKUP_ENGINE (default sqlite), DATABASE_PATH, BACKUP_DIR,
  BACKUP_RETENTION_COUNT (default 14).
- Puan/bildirim kilidi: bu modul puan/sinyal/musteri bildirimi uretmez.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional

from app.ops.backup import (
    ENGINE_POSTGRES,
    ENGINE_SQLITE,
    DailyBackupScheduler,
    PostgresBackupEngine,
    SqliteBackupEngine,
)

DEFAULT_BACKUP_DIR = "yedekler"
DEFAULT_DB_PATH = "db/xk100.db"
DEFAULT_RETENTION_COUNT = 14
STATE_FILENAME = "backup_state.json"


def _pg_dump_placeholder(out_path: Path) -> None:
    """Yer tutucu: gercek pg_dump cagrisi bu modulde YAPILMAZ (subprocess YOK).

    VPS uzerinde gercek dump icin dis bir sarici dump_fn enjekte etmelidir;
    bu giris noktasi bilincli olarak dis arac calistirmaz.
    """
    raise RuntimeError(
        "postgres dump_fn enjekte edilmedi; bu modul dis arac calistirmaz"
    )


def build_engine(environ: Optional[Dict[str, str]] = None):
    """env'den BACKUP_ENGINE/DATABASE_PATH/BACKUP_DIR okuyup motor kurar."""
    env = os.environ if environ is None else environ
    engine_name = (env.get("BACKUP_ENGINE") or ENGINE_SQLITE).strip() or ENGINE_SQLITE
    backup_dir = (env.get("BACKUP_DIR") or DEFAULT_BACKUP_DIR).strip() or DEFAULT_BACKUP_DIR
    if engine_name == ENGINE_POSTGRES:
        return PostgresBackupEngine(backup_dir, dump_fn=_pg_dump_placeholder), backup_dir
    db_path = (env.get("DATABASE_PATH") or DEFAULT_DB_PATH).strip() or DEFAULT_DB_PATH
    return SqliteBackupEngine(db_path, backup_dir), backup_dir


def main(environ: Optional[Dict[str, str]] = None) -> int:
    """Gunluk yedegi calistirir (due degilse is yapmaz). Donus: cikti kodu."""
    env = os.environ if environ is None else environ
    engine, backup_dir = build_engine(env)
    try:
        retention = int(env.get("BACKUP_RETENTION_COUNT") or DEFAULT_RETENTION_COUNT)
    except (TypeError, ValueError):
        retention = DEFAULT_RETENTION_COUNT
    state_path = os.path.join(backup_dir, STATE_FILENAME)
    scheduler = DailyBackupScheduler(
        engine, retention_count=retention, state_path=state_path
    )
    record = scheduler.run_daily()
    if record is not None:
        print("yedek alindi: %s (%s bayt)" % (record.path, record.size_bytes))
    else:
        print("bugun icin yedek zaten var; atlandi")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
