"""BLOK 21 - test_restore: geri yukleme + geri yukleme TESTI (6 test).

Kapsam: sqlite yedek->test_restore ok, checks icerigi, bozuk/missing dosya
ok=False errors, canli DB dokunulmaz, postgres sql bos-degil kontrol,
rapor alanlari. Hicbir test canli DB'ye dokunmaz; tum dizinler tmp_path.
"""
from __future__ import annotations

import sqlite3
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path

from app.ops.backup import ENGINE_POSTGRES, ENGINE_SQLITE, BackupRecord, SqliteBackupEngine
from app.ops.restore import RestoreReport
from app.ops.restore import test_restore as run_restore_test  # pytest toplamasin diye takma ad

GUN = datetime(2025, 6, 2, 23, 30, 0, tzinfo=timezone.utc)


def _yedek_olustur(tmp_path):
    db_path = tmp_path / "canli.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE fiyat (symbol TEXT, kapanis REAL)")
    conn.execute("INSERT INTO fiyat VALUES ('AKBNK', 55.5)")
    conn.execute("INSERT INTO fiyat VALUES ('YKBNK', 21.0)")
    conn.commit()
    conn.close()
    engine = SqliteBackupEngine(str(db_path), str(tmp_path / "yedek"))
    return db_path, engine.run(GUN)


def test_sqlite_yedek_test_restore_ok(tmp_path):
    _, record = _yedek_olustur(tmp_path)
    rapor = run_restore_test(record, ENGINE_SQLITE, str(tmp_path / "geri"))
    assert isinstance(rapor, RestoreReport)
    assert rapor.ok is True
    assert rapor.errors == []


def test_checks_icerigi_manifest_ve_kayip_kontrolu(tmp_path):
    _, record = _yedek_olustur(tmp_path)
    rapor = run_restore_test(record, ENGINE_SQLITE, str(tmp_path / "geri"))
    assert "backup_exists" in rapor.checks
    assert "copied" in rapor.checks
    assert "manifest_ok" in rapor.checks  # BLOK 7 manifesti yedegin yaninda
    assert "no_data_loss" in rapor.checks


def test_olmayan_dosya_ok_false_exception_sizmaz(tmp_path):
    kayip = BackupRecord("bkp-x-sqlite", ENGINE_SQLITE, str(tmp_path / "yok.db"), "2025-06-02T00:00:00Z", 0)
    rapor = run_restore_test(kayip, ENGINE_SQLITE, str(tmp_path / "geri"))
    assert rapor.ok is False
    assert rapor.errors  # hata rapora yazildi, exception firlatilmadi


def test_canli_db_dokunulmaz(tmp_path):
    db_path, record = _yedek_olustur(tmp_path)
    onceki = Path(db_path).read_bytes()
    work = tmp_path / "geri"
    rapor = run_restore_test(record, ENGINE_SQLITE, str(work))
    assert rapor.ok is True
    assert Path(db_path).read_bytes() == onceki  # canli DB birebir ayni
    kopya = work / Path(record.path).name
    assert kopya.is_file() and kopya != Path(db_path)
    assert str(db_path) not in kopya.parts  # geri yukleme work_dir'e yapildi


def test_postgres_sql_bos_degil_kontrolu(tmp_path):
    dolu = tmp_path / "bkp-20250602-233000-postgres.sql"
    dolu.write_text("-- dump\nCREATE TABLE t(x);\n", encoding="utf-8")
    rec_dolu = BackupRecord("bkp-1-postgres", ENGINE_POSTGRES, str(dolu), "2025-06-02T23:30:00Z", dolu.stat().st_size)
    rapor = run_restore_test(rec_dolu, ENGINE_POSTGRES, str(tmp_path / "g1"))
    assert rapor.ok is True
    assert "sql_nonempty" in rapor.checks

    bos = tmp_path / "bos.sql"
    bos.write_text("", encoding="utf-8")
    rec_bos = BackupRecord("bkp-2-postgres", ENGINE_POSTGRES, str(bos), "2025-06-02T23:30:00Z", 0)
    rapor2 = run_restore_test(rec_bos, ENGINE_POSTGRES, str(tmp_path / "g2"))
    assert rapor2.ok is False
    assert rapor2.errors


def test_rapor_alanlari_ve_bozuk_dosya(tmp_path):
    bozuk = tmp_path / "bozuk.db"
    bozuk.write_bytes(b"bu-bir-sqlite-degil" * 10)
    rec = BackupRecord("bkp-bozuk-sqlite", ENGINE_SQLITE, str(bozuk), "2025-06-02T23:30:00Z", bozuk.stat().st_size)
    rapor = run_restore_test(rec, ENGINE_SQLITE, str(tmp_path / "geri"))
    assert {f.name for f in fields(RestoreReport)} == {"ok", "engine", "checks", "errors"}
    assert rapor.ok is False  # integrity check basarisiz, exception sizmadi
    assert rapor.engine == ENGINE_SQLITE
    assert "backup_exists" in rapor.checks and "copied" in rapor.checks
    assert rapor.errors
