"""BLOK 7 - Ince repository katmani (repo.py).

Yardimcilar:
- insert_price(...): stock_prices_daily'ye layer parametreli kayit ekler.
- promote_to_clean(record_ids): raw -> clean yukseltmesi.
- promote_to_validated(record_ids): clean -> validated yukseltmesi.

Kurallar:
- Her gecis data_layer_promotions tablosuna kayit duser (checksum'larla).
- Atlama yasaktir: validated sadece clean'den yukseltilir; raw -> validated
  ve clean/validated -> clean denemeleri PromotionError firlatir.
- Raw kayit uzerine yazilamaz: yukseltme disinda raw icerigini degistiren
  bir yol yoktur; temizleme/yukseltme kaydi SILMEZ, ayni satirin
  data_layer etiketi ilerletilir (veri korunur).
- Coklu id'li cagirimlar atomiktir: biri basarisiz olursa hepsi geri alinir.

Dis bagimlilik yoktur (stdlib: sqlite3, json, hashlib, datetime).
Saat enjekte edilebilir (clock parametresi).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Callable, List, Optional, Sequence

PROMOTIONS_TABLE = "data_layer_promotions"
PRICES_TABLE = "stock_prices_daily"


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _checksum_row(row: sqlite3.Row) -> str:
    """Satir iceriginin deterministik SHA-256 ozeti."""
    payload = json.dumps(
        dict(row), sort_keys=True, ensure_ascii=True, default=str
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class RepoError(Exception):
    """Repository katmani hatalarinin taban sinifi."""


class PromotionError(RepoError):
    """Katman yukseltme kurali ihlali (atlama, yok kayit vb.)."""


class StockScanRepo:
    """stock_prices_daily + data_layer_promotions icin ince repo."""

    VALID_LAYERS = ("raw", "clean", "validated")

    def __init__(
        self,
        db_path: str,
        clock: Optional[Callable[[], str]] = None,
    ):
        self.db_path = str(db_path)
        self._clock = clock or _utcnow

    def connect(self) -> sqlite3.Connection:
        """Yeni baglanti acar; PRAGMA foreign_keys=ON zorunlu."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------ #
    # Insert
    # ------------------------------------------------------------------ #
    def insert_price(
        self,
        stock_id: str,
        trade_date: str,
        source: str,
        data_version: str,
        layer: str = "raw",
        open=None,
        high=None,
        low=None,
        close=None,
        volume=None,
    ) -> int:
        """stock_prices_daily'ye fiyat kaydi ekler; yeni satir id'sini doner.

        layer parametresi 'raw' | 'clean' | 'validated' olmalidir.
        Benzersizlik kisiti (stock_id, trade_date, source, data_version)
        ihlalinde sqlite3.IntegrityError firlatilir.
        """
        if layer not in self.VALID_LAYERS:
            raise RepoError("gecersiz data_layer: %r" % (layer,))
        conn = self.connect()
        try:
            cur = conn.execute(
                """
                INSERT INTO stock_prices_daily
                    (stock_id, trade_date, source, data_version,
                     open, high, low, close, volume, data_layer)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stock_id, trade_date, source, data_version,
                    open, high, low, close, volume, layer,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------ #
    # Katman yukseltme
    # ------------------------------------------------------------------ #
    def _promote(
        self,
        record_ids: Sequence[int],
        from_layer: str,
        to_layer: str,
        promoted_by: Optional[str],
    ) -> List[int]:
        """Ortak yukseltme dongusu (atomik). Donus: promotion id'leri."""
        ids = [int(rid) for rid in record_ids]
        if not ids:
            return []
        conn = self.connect()
        try:
            conn.execute("BEGIN")
            promotion_ids: List[int] = []
            for rid in ids:
                row = conn.execute(
                    'SELECT * FROM "%s" WHERE id = ?' % PRICES_TABLE, (rid,)
                ).fetchone()
                if row is None:
                    raise PromotionError(
                        "kayit bulunamadi: %s id=%d" % (PRICES_TABLE, rid)
                    )
                current = row["data_layer"]
                if current != from_layer:
                    raise PromotionError(
                        "atlama yasak: id=%d katmani '%s', '%s' bekleniyordu"
                        % (rid, current, from_layer)
                    )
                checksum_before = _checksum_row(row)
                # Kayit SILINMEZ: ayni satirin data_layer etiketi ilerletilir.
                conn.execute(
                    'UPDATE "%s" SET data_layer = ? WHERE id = ?' % PRICES_TABLE,
                    (to_layer, rid),
                )
                row_after = conn.execute(
                    'SELECT * FROM "%s" WHERE id = ?' % PRICES_TABLE, (rid,)
                ).fetchone()
                checksum_after = _checksum_row(row_after)
                cur = conn.execute(
                    """
                    INSERT INTO data_layer_promotions
                        (table_name, record_id, from_layer, to_layer,
                         promoted_at, promoted_by, checksum_before, checksum_after)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        PRICES_TABLE, rid, from_layer, to_layer,
                        self._clock(), promoted_by,
                        checksum_before, checksum_after,
                    ),
                )
                promotion_ids.append(int(cur.lastrowid))
            conn.commit()
            return promotion_ids
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def promote_to_clean(
        self,
        record_ids: Sequence[int],
        promoted_by: Optional[str] = None,
    ) -> List[int]:
        """raw -> clean yukseltmesi. Sadece 'raw' katmanindaki kayitlar
        yukseltilebilir; clean/validated kayitlarda PromotionError."""
        return self._promote(record_ids, "raw", "clean", promoted_by)

    def promote_to_validated(
        self,
        record_ids: Sequence[int],
        promoted_by: Optional[str] = None,
    ) -> List[int]:
        """clean -> validated yukseltmesi. Atlama yasak: raw kayittan
        dogrudan validated'a gecilemez (PromotionError)."""
        return self._promote(record_ids, "clean", "validated", promoted_by)
