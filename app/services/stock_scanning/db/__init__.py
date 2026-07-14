"""BLOK 7 - Veri Tabani ve Migration modulu (db paketi).

Bilesenler:
- migrator.MigrationRunner: surumlu migration (apply_all/apply_next/
  rollback/status), tek transaction, SHA-256 checksum, idempotent.
- backup.backup_db / verify_no_data_loss / safe_migrate: yedek + kayip
  kontrolu + migration oncesi zorunlu akis.
- repo.StockScanRepo: insert_price (layer parametreli), promote_to_clean,
  promote_to_validated (atlama yasak, raw silinmez).

Dis bagimlilik yoktur (stdlib sqlite3 + os + json + hashlib + shutil +
datetime). Dosya/identifier ASCII; docstring'ler Turkce.
"""
from .backup import DataLossError, backup_db, safe_migrate, verify_no_data_loss
from .migrator import (
    MIGRATIONS_DIR,
    ChecksumMismatchError,
    MigrationError,
    MigrationRunner,
    MissingDownMigrationError,
)
from .repo import PromotionError, RepoError, StockScanRepo

__all__ = [
    "MIGRATIONS_DIR",
    "MigrationRunner",
    "MigrationError",
    "ChecksumMismatchError",
    "MissingDownMigrationError",
    "backup_db",
    "verify_no_data_loss",
    "safe_migrate",
    "DataLossError",
    "StockScanRepo",
    "RepoError",
    "PromotionError",
]
