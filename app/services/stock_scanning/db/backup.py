"""BLOK 7 - Yedek + kayip kontrolu (backup.py).

- backup_db(db_path, backup_dir): timestamp'li kopya (shutil) + yaninda
  manifest JSON (tablo adi -> satir sayisi + satir checksum toplami).
  Varolmayan/bos DB'de HATA VERMEZ: 0 tablo manifest'i yazar.
- verify_no_data_loss(original_db, target_db): tablo bazli satir sayisi
  karsilastirmasi; kayip varsa DataLossError + rapor (hangi tablo, kac
  satir eksik).
- safe_migrate(runner, db_path, backup_dir): yedek al -> migration uygula
  -> kayip kontrolu -> kayip varsa otomatik geri al (rollback + yedekten
  restore).

Dis bagimlilik yoktur (stdlib: sqlite3, os, json, hashlib, shutil,
datetime). Saat enjekte edilebilir (clock parametresi).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from .migrator import MigrationRunner


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class DataLossError(Exception):
    """Kayip tespit edildi; .report niteligi tablo bazli eksik sayilari icerir."""

    def __init__(self, message: str, report: Optional[Dict[str, object]] = None):
        super().__init__(message)
        self.report = report or {}


# ---------------------------------------------------------------------- #
# Yardimcilar
# ---------------------------------------------------------------------- #
def _list_tables(conn: sqlite3.Connection) -> List[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def _row_checksum(row) -> str:
    """Tek satirin deterministik SHA-256 ozeti."""
    return hashlib.sha256(repr(tuple(row)).encode("utf-8")).hexdigest()


def _table_checksum(conn: sqlite3.Connection, table: str) -> str:
    """Tablodaki tum satir checksum'larinin toplam (zincir) ozeti.

    Satirlar rowid sirasina gore okunur; ayni icerik her zaman ayni
    toplam checksum'i uretir (deterministik).
    """
    total = hashlib.sha256()
    for row in conn.execute('SELECT * FROM "%s" ORDER BY rowid' % table):
        total.update(_row_checksum(row).encode("ascii"))
    return total.hexdigest()


def _table_row_counts(db_path: str) -> Dict[str, int]:
    if not os.path.isfile(db_path):
        return {}
    conn = sqlite3.connect(db_path)
    try:
        counts: Dict[str, int] = {}
        for table in _list_tables(conn):
            counts[table] = conn.execute(
                'SELECT COUNT(*) FROM "%s"' % table
            ).fetchone()[0]
        return counts
    finally:
        conn.close()


def _stamp(now_iso: str) -> str:
    """ISO-8601 damgasini dosya adina uygun hale getirir."""
    return now_iso.replace("-", "").replace(":", "")


def _unique_path(backup_dir: str, base: str, ext: str) -> str:
    candidate = os.path.join(backup_dir, "%s%s" % (base, ext))
    i = 1
    while os.path.exists(candidate):
        candidate = os.path.join(backup_dir, "%s_%d%s" % (base, i, ext))
        i += 1
    return candidate


def _build_manifest(db_path: str) -> Dict[str, object]:
    """DB'deki tablolar icin satir sayisi + checksum manifest'i."""
    tables: Dict[str, Dict[str, object]] = {}
    if os.path.isfile(db_path):
        conn = sqlite3.connect(db_path)
        try:
            for table in _list_tables(conn):
                count = conn.execute(
                    'SELECT COUNT(*) FROM "%s"' % table
                ).fetchone()[0]
                tables[table] = {
                    "row_count": count,
                    "checksum": _table_checksum(conn, table),
                }
        finally:
            conn.close()
    return tables


# ---------------------------------------------------------------------- #
# Genel API
# ---------------------------------------------------------------------- #
def backup_db(
    db_path: str,
    backup_dir: str,
    clock: Optional[Callable[[], str]] = None,
) -> Dict[str, object]:
    """DB'nin timestamp'li kopyasini + manifest JSON'u backup_dir'e yazar.

    Varolmayan veya bos (tablosuz) DB icin hata VERMEZ: manifest 0 tablo
    ile yazilir, backup_path None olur. Donus: {"backup_path",
    "manifest_path", "manifest"}.
    """
    db_path = str(db_path)
    backup_dir = str(backup_dir)
    os.makedirs(backup_dir, exist_ok=True)
    now = (clock or _utcnow)()
    stamp = _stamp(now)

    manifest: Dict[str, object] = {
        "created_at": now,
        "source_db": db_path,
        "backup_file": None,
        "db_existed": os.path.isfile(db_path),
        "tables": _build_manifest(db_path),
    }

    backup_path = None
    if os.path.isfile(db_path):
        backup_path = _unique_path(backup_dir, "backup_%s" % stamp, ".db")
        shutil.copy2(db_path, backup_path)
        manifest["backup_file"] = os.path.basename(backup_path)

    manifest_path = _unique_path(backup_dir, "backup_%s" % stamp, ".manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=True, indent=2, sort_keys=True)

    return {
        "backup_path": backup_path,
        "manifest_path": manifest_path,
        "manifest": manifest,
    }


def verify_no_data_loss(original_db: str, target_db: str) -> Dict[str, object]:
    """original_db -> target_db arasinda satir kaybi olup olmadigini kontrol eder.

    Kayip varsa DataLossError firlatilir; rapor (exception.report ve donus
    degeri) hangi tabloda kac satirin eksik oldugunu icerir. Varolmayan
    original DB 0 tablo sayilir (bos DB senaryosunda hata yok).
    """
    original_counts = _table_row_counts(str(original_db))
    target_counts = _table_row_counts(str(target_db))

    missing: Dict[str, int] = {}
    for table, orig_count in original_counts.items():
        target_count = target_counts.get(table, 0)
        if target_count < orig_count:
            missing[table] = orig_count - target_count

    report: Dict[str, object] = {
        "original": str(original_db),
        "target": str(target_db),
        "checked_tables": sorted(original_counts.keys()),
        "missing": missing,
        "ok": not missing,
    }
    if missing:
        details = ", ".join(
            "%s tablosunda %d satir eksik" % (t, n)
            for t, n in sorted(missing.items())
        )
        raise DataLossError("veri kaybi tespit edildi: %s" % details, report)
    return report


def safe_migrate(
    runner: MigrationRunner,
    db_path: str,
    backup_dir: str,
    clock: Optional[Callable[[], str]] = None,
) -> Dict[str, object]:
    """Migration oncesi zorunlu akis: yedek -> uygula -> kayip kontrolu.

    Kayip tespit edilirse otomatik geri alinir: once yeni uygulanan
    migration'lar rollback edilir, sonra yedekten restore yapilir ve
    DataLossError yeniden firlatilir. Bos/varolmayan DB'de yedek 0 tablo
    manifest'i ile alinir, migration normal sekilde uygulanir.
    """
    db_path = str(db_path)
    backup = backup_db(db_path, backup_dir, clock=clock)
    before = set(runner.applied_versions())

    applied = runner.apply_all()

    backup_path = backup["backup_path"]
    if backup_path is not None:
        try:
            verify_no_data_loss(str(backup_path), db_path)
        except DataLossError:
            newly = [
                v for v in runner.applied_versions() if v not in before
            ]
            # Once migration rollback dene (best effort)...
            if newly:
                try:
                    runner.rollback(steps=len(newly))
                except Exception:
                    pass
            # ...sonra yedekten restore (yetkili geri alma).
            shutil.copy2(str(backup_path), db_path)
            raise

    return {
        "db_path": db_path,
        "backup": backup,
        "applied": applied,
        "verified": backup_path is not None,
    }
