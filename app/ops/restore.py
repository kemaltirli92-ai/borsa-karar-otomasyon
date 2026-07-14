"""BLOK 21 - Guvenlik, Log, Izleme ve Yedekleme: geri yukleme + geri yukleme TESTI.

Kurallar ozeti:
- stdlib only (json, os, shutil, sqlite3, dataclasses, pathlib); gercek
  ag/subprocess YOK.
- CANLI DB'ye DOKUNULMAZ: yedek yalnizca hedef/gecici dizine (work_dir)
  geri yuklenir; canli veritabani yolu bu modulde yazilmaz.
- Hicbir exception SIZDIRILMAZ: tum hatalar RestoreReport(ok=False,
  errors=[...]) olarak raporlanir.
- BLOK 7 arayuzleri yeniden kullanilir (DEGISTIRILMEZ): verify_no_data_loss
  ve manifest semasi (tablo -> satir sayisi + checksum).
- Deterministik: clock enjekte edilebilir; testler gercek saate/diske
  bagli degildir (tmp dizinler kullanilir).
- Puan/bildirim kilidi: bu modul puan/sinyal/musteri bildirimi uretmez.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from app.ops.backup import ENGINE_POSTGRES, ENGINE_SQLITE, BackupRecord
from app.services.stock_scanning.db.backup import (
    _table_checksum,
    verify_no_data_loss,
)


@dataclass(frozen=True)
class RestoreReport:
    """Geri yukleme/dogrulama sonucu (degistirilemez)."""

    ok: bool
    engine: str
    checks: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def _error_text(exc: BaseException) -> str:
    """Hata metni (hicbir exception rapor disina sizmaz)."""
    return "%s: %s" % (type(exc).__name__, exc)


def _manifest_path_for(backup_path: Path) -> Optional[Path]:
    """BLOK 7 adlandirmasi: <kok>.db yaninda <kok>.manifest.json."""
    candidate = backup_path.with_suffix("")
    candidate = candidate.parent / (candidate.name + ".manifest.json")
    return candidate if candidate.is_file() else None


def _verify_manifest(manifest_path: Path, db_path: Path) -> None:
    """Manifest'teki tablo satir sayilari + checksum'lari dogrular.

    Uyumsuzlukta ValueError firlatir (cagiran rapora cevirir).
    """
    with open(str(manifest_path), "r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    tables = manifest.get("tables") if isinstance(manifest, dict) else None
    if not isinstance(tables, dict):
        raise ValueError("manifest semasi gecersiz")
    conn = sqlite3.connect(str(db_path))
    try:
        for table, expected in tables.items():
            count = conn.execute(
                'SELECT COUNT(*) FROM "%s"' % table
            ).fetchone()[0]
            if int(count) != int(expected.get("row_count", -1)):
                raise ValueError(
                    "manifest uyumsuz: %s satir sayisi %s != %s"
                    % (table, count, expected.get("row_count"))
                )
            checksum = _table_checksum(conn, table)
            if checksum != expected.get("checksum"):
                raise ValueError("manifest uyumsuz: %s checksum" % table)
    finally:
        conn.close()


def _integrity_ok(db_path: Path) -> bool:
    """sqlite3 PRAGMA integrity_check sonucu 'ok' mi."""
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        return bool(row) and str(row[0]).lower() == "ok"
    finally:
        conn.close()


def restore_sqlite_backup(backup_record_path: str, target_dir: str) -> RestoreReport:
    """SQLite yedegini hedef dizine geri yukler ve dogrular.

    Manifest yanindaysa tablo sayilari/checksum dogrulanir; kopya
    verify_no_data_loss ile karsilastirilir. Hicbir exception sizdirilmaz.
    """
    checks: List[str] = []
    errors: List[str] = []
    try:
        src = Path(str(backup_record_path))
        if not src.is_file():
            errors.append("yedek dosyasi bulunamadi: %s" % src.name)
            return RestoreReport(ok=False, engine=ENGINE_SQLITE, checks=checks, errors=errors)
        checks.append("backup_exists")

        target = Path(str(target_dir))
        target.mkdir(parents=True, exist_ok=True)
        dst = target / src.name
        shutil.copy2(str(src), str(dst))
        checks.append("copied")

        manifest_path = _manifest_path_for(src)
        if manifest_path is not None:
            _verify_manifest(manifest_path, dst)
            checks.append("manifest_ok")
        else:
            if not _integrity_ok(dst):
                raise ValueError("butunluk kontrolu basarisiz")
            checks.append("integrity_ok")

        verify_no_data_loss(str(src), str(dst))
        checks.append("no_data_loss")
        return RestoreReport(ok=True, engine=ENGINE_SQLITE, checks=checks, errors=errors)
    except Exception as exc:  # hicbir exception sizdirilmaz
        errors.append(_error_text(exc))
        return RestoreReport(ok=False, engine=ENGINE_SQLITE, checks=checks, errors=errors)


def test_restore(
    record: BackupRecord,
    engine: str,
    work_dir: str,
    clock=None,
) -> RestoreReport:
    """Geri yukleme TESTI: CANLI DB'ye dokunmaz, yedegi work_dir'e yukler.

    Butunluk kontrollerini yapar ve raporlar; hata durumunda
    ok=False + errors doner (hicbir zaman exception SIZDIRMAZ).
    """
    checks: List[str] = []
    errors: List[str] = []
    try:
        src = Path(str(record.path))
        if not src.is_file():
            errors.append("yedek dosyasi bulunamadi: %s" % src.name)
            return RestoreReport(ok=False, engine=str(engine), checks=checks, errors=errors)

        work = Path(str(work_dir))
        work.mkdir(parents=True, exist_ok=True)

        if engine == ENGINE_SQLITE:
            report = restore_sqlite_backup(str(src), str(work))
            return RestoreReport(
                ok=report.ok,
                engine=ENGINE_SQLITE,
                checks=list(report.checks),
                errors=list(report.errors),
            )

        if engine == ENGINE_POSTGRES:
            checks.append("backup_exists")
            dst = work / src.name
            shutil.copy2(str(src), str(dst))
            checks.append("copied")
            if dst.stat().st_size <= 0:
                errors.append("sql dump bos")
                return RestoreReport(
                    ok=False, engine=ENGINE_POSTGRES, checks=checks, errors=errors
                )
            checks.append("sql_nonempty")
            return RestoreReport(ok=True, engine=ENGINE_POSTGRES, checks=checks, errors=errors)

        errors.append("bilinmeyen yedek motoru: %s" % engine)
        return RestoreReport(ok=False, engine=str(engine), checks=checks, errors=errors)
    except Exception as exc:  # hicbir exception sizdirilmaz
        errors.append(_error_text(exc))
        return RestoreReport(ok=False, engine=str(engine), checks=checks, errors=errors)
