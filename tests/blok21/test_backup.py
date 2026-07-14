"""BLOK 21 - test_backup: gunluk yedekleme motoru + zamanlayici (10 test).

Kapsam: sqlite engine record, backup_id format, postgres dump_fn
cagirildi+dosya, is_due ayni gun False, ertesi gun True, run_daily
due-degil None, retention budama, state dosyasi, clock enjekte, engine
secimi. Gercek subprocess/ag YOK (dump_fn sahte); Istanbul gunu zoneinfo.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.ops import backup_run
from app.ops.backup import (
    ENGINE_POSTGRES,
    ENGINE_SQLITE,
    BackupRecord,
    DailyBackupScheduler,
    PostgresBackupEngine,
    SqliteBackupEngine,
)

GUN1 = datetime(2025, 6, 2, 23, 30, 0, tzinfo=timezone.utc)
GUN2 = GUN1 + timedelta(days=1)
GUN3 = GUN1 + timedelta(days=2)


def _db_olustur(path):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE fiyat (symbol TEXT, kapanis REAL)")
    conn.execute("INSERT INTO fiyat VALUES ('AKBNK', 55.5)")
    conn.commit()
    conn.close()


def _sqlite_engine(tmp_path):
    db_path = tmp_path / "xk100.db"
    _db_olustur(db_path)
    return SqliteBackupEngine(str(db_path), str(tmp_path / "yedek"))


def test_sqlite_engine_record_alanlari(tmp_path):
    engine = _sqlite_engine(tmp_path)
    record = engine.run(GUN1)
    assert isinstance(record, BackupRecord)
    assert record.engine == ENGINE_SQLITE
    assert Path(record.path).is_file()
    assert record.size_bytes > 0
    assert record.created_at == "2025-06-02T23:30:00Z"


def test_backup_id_formati(tmp_path):
    record = _sqlite_engine(tmp_path).run(GUN1)
    assert re.fullmatch(r"bkp-\d{8}-\d{6}-sqlite", record.backup_id)
    assert record.backup_id == "bkp-20250602-233000-sqlite"


def test_postgres_engine_dump_fn_cagirildi_ve_dosya(tmp_path):
    cagrilar = []

    def sahte_dump(out_path):
        cagrilar.append(out_path)
        Path(out_path).write_text("-- SQL DUMP\nCREATE TABLE t(x);\n", encoding="utf-8")

    engine = PostgresBackupEngine(str(tmp_path / "yedek"), dump_fn=sahte_dump)
    record = engine.run(GUN1)
    assert len(cagrilar) == 1
    assert record.engine == ENGINE_POSTGRES
    assert record.backup_id.endswith("-postgres")
    assert Path(record.path).suffix == ".sql"
    assert record.size_bytes > 0


def test_is_due_ayni_gun_ikinci_cagrida_false(tmp_path):
    scheduler = DailyBackupScheduler(
        _sqlite_engine(tmp_path), state_path=str(tmp_path / "state.json")
    )
    assert scheduler.is_due(GUN1) is True
    scheduler.run_daily(GUN1)
    assert scheduler.is_due(GUN1) is False


def test_is_due_ertesi_gun_true(tmp_path):
    scheduler = DailyBackupScheduler(
        _sqlite_engine(tmp_path), state_path=str(tmp_path / "state.json")
    )
    scheduler.run_daily(GUN1)
    assert scheduler.is_due(GUN2) is True


def test_run_daily_due_degilse_none(tmp_path):
    scheduler = DailyBackupScheduler(
        _sqlite_engine(tmp_path), state_path=str(tmp_path / "state.json")
    )
    ilk = scheduler.run_daily(GUN1)
    assert ilk is not None
    assert scheduler.run_daily(GUN1) is None


def test_retention_budama_state_izlenir(tmp_path):
    state_path = str(tmp_path / "state.json")
    scheduler = DailyBackupScheduler(
        _sqlite_engine(tmp_path), retention_count=2, state_path=state_path
    )
    r1 = scheduler.run_daily(GUN1)
    r2 = scheduler.run_daily(GUN2)
    r3 = scheduler.run_daily(GUN3)
    with open(state_path, "r", encoding="utf-8") as fh:
        state = json.load(fh)
    assert len(state["records"]) == 2
    assert [r["backup_id"] for r in state["records"]] == [r2.backup_id, r3.backup_id]
    assert not os.path.exists(r1.path)  # en eski yedek dosyasi budandi
    assert os.path.exists(r3.path)


def test_state_dosyasi_icerigi(tmp_path):
    state_path = str(tmp_path / "state.json")
    scheduler = DailyBackupScheduler(_sqlite_engine(tmp_path), state_path=state_path)
    scheduler.run_daily(GUN1)
    with open(state_path, "r", encoding="utf-8") as fh:
        state = json.load(fh)
    kayit = state["records"][0]
    assert kayit["ok"] is True
    assert kayit["engine"] == ENGINE_SQLITE
    # Istanbul gunu (UTC+3): 2025-06-02 23:30 UTC -> 2025-06-03 02:30 IST
    assert kayit["day"] == "2025-06-03"


def test_clock_enjekte_deterministik(tmp_path):
    scheduler = DailyBackupScheduler(
        _sqlite_engine(tmp_path),
        clock=lambda: GUN1,
        state_path=str(tmp_path / "state.json"),
    )
    assert scheduler.is_due() is True  # now verilmedi: clock kullanildi
    record = scheduler.run_daily()
    assert record.created_at == "2025-06-02T23:30:00Z"
    assert scheduler.is_due() is False


def test_engine_secimi_env_ile(tmp_path):
    engine, _ = backup_run.build_engine({"BACKUP_DIR": str(tmp_path)})
    assert isinstance(engine, SqliteBackupEngine)
    engine2, _ = backup_run.build_engine(
        {"BACKUP_ENGINE": "postgres", "BACKUP_DIR": str(tmp_path)}
    )
    assert isinstance(engine2, PostgresBackupEngine)
