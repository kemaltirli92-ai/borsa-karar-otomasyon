"""BLOK 7 - Surumlu migration sistemi (MigrationRunner).

- migrations/ klasorundeki dosyalar NNNN_ad.sql (up) ve NNNN_ad.down.sql
  (down) formatindadir. Up dosyasi var ama down dosyasi yoksa kesin hata
  (MissingDownMigrationError) - kesif asamasinda yakalanir.
- schema_migrations tablosu: version (PRIMARY KEY), name, checksum
  (SHA-256, up dosyasinin icerigi), applied_at (ISO-8601 UTC).
- Her migration TEK transaction icinde uygulanir; hata olursa ROLLBACK
  yapilir, yarim kayit kalmaz.
- Ayni migration ikinci kez uygulanmaz (idempotent: pending listesinden
  cikarilmis olur).
- Uygulanmis bir migration dosyasinin checksum'i sonradan degistiyse
  status() bunu raporlar; apply_* ve rollback bu durumda
  ChecksumMismatchError ile islemi reddeder (disaridan mudahale tespiti).

Dis bagimlilik yoktur (stdlib: sqlite3, os, re, json degil, hashlib,
datetime). Saat enjekte edilebilir (clock parametresi) - deterministik
testler icin.
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

# Paket ici varsayilan migration klasoru
MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")

# 0001_initial.sql -> ("0001", "initial"); 0001_initial.down.sql ayri desen
_UP_RE = re.compile(r"^(\d{4})_([A-Za-z0-9_]+)\.sql$")
_DOWN_RE = re.compile(r"^(\d{4})_([A-Za-z0-9_]+)\.down\.sql$")


def _utcnow() -> str:
    """Varsayilan saat: ISO-8601 UTC (saniye cozunurluk)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class MigrationError(Exception):
    """Migration uygulama/kesif/geri-alma hatalarinin taban sinifi."""


class ChecksumMismatchError(MigrationError):
    """Uygulanmis migration dosyasinin checksum'i degismis - islem reddedildi."""


class MissingDownMigrationError(MigrationError):
    """Up migration dosyasi var ama karsilik gelen .down.sql yok."""


class Migration:
    """Tek bir migration dosyasi cifti (up + down)."""

    def __init__(self, version: str, name: str, up_path: str, down_path: str):
        self.version = version
        self.name = name
        self.up_path = up_path
        self.down_path = down_path

    def up_sql(self) -> str:
        with open(self.up_path, "r", encoding="utf-8") as fh:
            return fh.read()

    def down_sql(self) -> str:
        with open(self.down_path, "r", encoding="utf-8") as fh:
            return fh.read()

    def checksum(self) -> str:
        """Up dosyasi iceriginin SHA-256 ozeti."""
        return _sha256_text(self.up_sql())

    @property
    def label(self) -> str:
        return "%s_%s" % (self.version, self.name)


class MigrationRunner:
    """SQLite veritabani icin surumlu migration yoneticisi."""

    def __init__(
        self,
        db_path: str,
        migrations_dir: Optional[str] = None,
        clock: Optional[Callable[[], str]] = None,
    ):
        self.db_path = str(db_path)
        self.migrations_dir = str(migrations_dir) if migrations_dir else MIGRATIONS_DIR
        self._clock = clock or _utcnow
        # Kesif hatasi (ornegin down dosyasi eksik) burada patlar.
        self._migrations: List[Migration] = self._discover()
        self._ensure_meta()

    # ------------------------------------------------------------------ #
    # Baglanti / meta tablo
    # ------------------------------------------------------------------ #
    def connect(self) -> sqlite3.Connection:
        """Yeni baglanti acar; PRAGMA foreign_keys=ON zorunlu."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_meta(self) -> None:
        conn = self.connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version    TEXT PRIMARY KEY,
                    name       TEXT NOT NULL,
                    checksum   TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------ #
    # Kesif
    # ------------------------------------------------------------------ #
    def _discover(self) -> List[Migration]:
        if not os.path.isdir(self.migrations_dir):
            raise MigrationError(
                "migration klasoru bulunamadi: %s" % self.migrations_dir
            )
        ups: Dict[str, Migration] = {}
        downs = set()
        for fname in sorted(os.listdir(self.migrations_dir)):
            m = _DOWN_RE.match(fname)
            if m:
                downs.add((m.group(1), m.group(2)))
                continue
            m = _UP_RE.match(fname)
            if not m:
                continue  # taninmayan dosya: yok say
            version, name = m.group(1), m.group(2)
            if version in ups:
                raise MigrationError(
                    "yinelenen migration surumu: %s" % version
                )
            ups[version] = Migration(
                version,
                name,
                os.path.join(self.migrations_dir, fname),
                os.path.join(self.migrations_dir, "%s_%s.down.sql" % (version, name)),
            )
        migrations = [ups[v] for v in sorted(ups)]
        for mig in migrations:
            if (mig.version, mig.name) not in downs:
                raise MissingDownMigrationError(
                    "%s icin %s_%s.down.sql dosyasi eksik"
                    % (os.path.basename(mig.up_path), mig.version, mig.name)
                )
            if not os.path.isfile(mig.down_path):
                raise MissingDownMigrationError(
                    "down migration dosyasi bulunamadi: %s" % mig.down_path
                )
        return migrations

    # ------------------------------------------------------------------ #
    # Durum sorgulari
    # ------------------------------------------------------------------ #
    def applied_versions(self) -> List[str]:
        conn = self.connect()
        try:
            rows = conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
            return [r[0] for r in rows]
        finally:
            conn.close()

    def _applied_checksums(self) -> Dict[str, str]:
        conn = self.connect()
        try:
            rows = conn.execute(
                "SELECT version, checksum FROM schema_migrations"
            ).fetchall()
            return {r[0]: r[1] for r in rows}
        finally:
            conn.close()

    def pending(self) -> List[Migration]:
        applied = set(self.applied_versions())
        return [m for m in self._migrations if m.version not in applied]

    def checksum_mismatches(self) -> List[str]:
        """Checksum'i degismis uygulanmis migration surumleri."""
        stored = self._applied_checksums()
        bad = []
        for mig in self._migrations:
            if mig.version in stored and stored[mig.version] != mig.checksum():
                bad.append(mig.version)
        return bad

    def status(self) -> Dict[str, object]:
        """Uygulanmis / bekleyen surumler + checksum uyusmazliklari."""
        applied = self.applied_versions()
        return {
            "db_path": self.db_path,
            "applied": applied,
            "pending": [m.version for m in self.pending()],
            "current": applied[-1] if applied else None,
            "checksum_mismatches": self.checksum_mismatches(),
        }

    def _validate_applied(self) -> None:
        bad = self.checksum_mismatches()
        if bad:
            raise ChecksumMismatchError(
                "uygulanmis migration checksum uyusmazligi: %s"
                % ", ".join(bad)
            )

    # ------------------------------------------------------------------ #
    # Uygulama
    # ------------------------------------------------------------------ #
    def _apply_one(self, mig: Migration) -> str:
        """Tek migration'u TEK transaction icinde uygular.

        Hata olursa transaction ROLLBACK edilir; schema_migrations'a
        kayit dusmez ve olusturulan nesneler geri alinir.
        """
        checksum = mig.checksum()
        applied_at = self._clock()
        # Icerikler regex ile dogrulanmis guvenli identifier'lar
        # (surum: 4 rakam, ad: [A-Za-z0-9_], checksum: hex, saat: ISO).
        meta_sql = (
            "INSERT INTO schema_migrations (version, name, checksum, applied_at) "
            "VALUES ('%s', '%s', '%s', '%s');"
            % (mig.version, mig.name, checksum, applied_at)
        )
        script = "BEGIN;\n" + mig.up_sql() + "\n" + meta_sql + "\nCOMMIT;"
        conn = self.connect()
        try:
            conn.executescript(script)
        except sqlite3.Error as exc:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise MigrationError(
                "%s uygulanamadi; transaction geri alindi: %s" % (mig.label, exc)
            ) from exc
        finally:
            conn.close()
        return mig.version

    def apply_next(self):
        """Bekleyen ilk migration'u uygular; yoksa None doner."""
        self._validate_applied()
        pend = self.pending()
        if not pend:
            return None
        return self._apply_one(pend[0])

    def apply_all(self) -> List[str]:
        """Tum bekleyen migration'lari sirayla uygular (idempotent)."""
        self._validate_applied()
        applied = []
        for mig in self.pending():
            applied.append(self._apply_one(mig))
        return applied

    # ------------------------------------------------------------------ #
    # Geri alma
    # ------------------------------------------------------------------ #
    def rollback(self, steps: int = 1) -> List[str]:
        """Son N migration'u .down.sql ile geri alir.

        - Geri alinacak surumlerden HERHANGI BIRININ dosya checksum'i
          kayitla uyusmuyorsa hicbir sey yapilmaz (ChecksumMismatchError).
        - Her adim TEK transaction icindedir.
        - Donus: geri alinan surumler (yeniden eskiye).
        """
        if steps <= 0:
            return []
        applied = self.applied_versions()
        if not applied:
            return []
        targets = list(reversed(applied))[:steps]
        mig_by_version = {m.version: m for m in self._migrations}
        stored = self._applied_checksums()

        # 1) Oncelikle butun hedeflerin checksum'ini dogrula.
        for version in targets:
            mig = mig_by_version.get(version)
            if mig is None:
                raise MigrationError(
                    "migration dosyasi bulunamadigi icin geri alinamaz: %s" % version
                )
            if stored.get(version) != mig.checksum():
                raise ChecksumMismatchError(
                    "checksum uyusmazligi nedeniyle geri alma reddedildi: %s"
                    % version
                )

        # 2) Adim adim geri al (her adim tek transaction).
        rolled = []
        for version in targets:
            mig = mig_by_version[version]
            meta_sql = (
                "DELETE FROM schema_migrations WHERE version = '%s';" % version
            )
            script = "BEGIN;\n" + mig.down_sql() + "\n" + meta_sql + "\nCOMMIT;"
            conn = self.connect()
            try:
                conn.executescript(script)
            except sqlite3.Error as exc:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise MigrationError(
                    "%s geri alinamadi; transaction geri alindi: %s"
                    % (mig.label, exc)
                ) from exc
            finally:
                conn.close()
            rolled.append(version)
        return rolled
