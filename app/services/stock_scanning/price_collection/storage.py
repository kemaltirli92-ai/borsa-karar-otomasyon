"""BLOK 8 - Fiyat depolama (storage.py).

BLOK 7 semasindaki stock_prices_daily tablosuna raw katmaninda yazar;
sema DEGISTIRILMEZ (SPEC bolum 9). Benzersizlik anahtari
(stock_id, trade_date, source, data_version): cakismada kopya YAZILMAZ
(INSERT OR IGNORE), atlanan satir sayisi dondurulur.

- PriceStorage(conn, repo=None, clock=None)
  * conn verilirse SQLite stock_prices_daily tablosu kullanilir.
  * conn=None ise bellek ici depolama (test icin).
  * conn=None ve repo verilirse BLOK 7 StockScanRepo.connect() ile baglanti
    acilir (repo uyumluluk yolu).
- Yazilan her bar data_layer="raw" baslar (BLOK 7 katmanlariyla uyumlu).
- Guncellenen barlar SILINMEZ: yeni data_version ile yeni satir eklenir;
  okuma yontemleri her (trade_date, source) icin en son surumu dondurur.

Dis bagimlilik yoktur (stdlib: sqlite3, dataclasses, datetime, typing).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from .sources import DEFAULT_CURRENCY, PriceBar

PRICES_TABLE = "stock_prices_daily"


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class WriteResult:
    """write_bars sonucu: yazilan ve (kopya nedeniyle) atlanan satir sayisi."""

    written: int = 0
    skipped: int = 0


class PriceStorage:
    """stock_prices_daily icin kopya engelli depolama (DB veya bellek ici)."""

    def __init__(
        self,
        conn: Optional[sqlite3.Connection] = None,
        repo=None,
        clock: Optional[Callable[[], str]] = None,
    ):
        if conn is None and repo is not None:
            conn = repo.connect()
        self.conn = conn
        self.repo = repo
        self._clock = clock or _utcnow
        # Bellek ici mod: (stock_id, trade_date, source, data_version) -> kayit
        self._mem: Dict[Tuple[str, str, str, str], dict] = {}
        self._seq = 0  # ekleme sirasi sayaci (DB'deki id'ye karsilik)
        if self.conn is not None:
            self.conn.row_factory = sqlite3.Row

    @property
    def is_memory(self) -> bool:
        return self.conn is None

    # ------------------------------------------------------------------ #
    # Yazim
    # ------------------------------------------------------------------ #
    def write_bars(
        self,
        stock_id: str,
        bars: List[PriceBar],
        data_layer: str = "raw",
        data_version: str = "1",
    ) -> WriteResult:
        """Bar listesini yazar; unique cakismada kopya YAZILMAZ.

        Donus: WriteResult(written, skipped) — skipped, benzersizlik
        anahtari (stock_id+trade_date+source+data_version) zaten var olan
        satir sayisidir.
        """
        result = WriteResult()
        for bar in bars:
            if self._insert_one(stock_id, bar, str(data_version), data_layer):
                result.written += 1
            else:
                result.skipped += 1
        if self.conn is not None:
            self.conn.commit()
        return result

    def update_bar(
        self,
        stock_id: str,
        trade_date: str,
        source: str,
        new_bar: PriceBar,
        new_version: str,
    ) -> bool:
        """Son-10-gun recheck icin surum artirimli guncelleme.

        Eski satir SILINMEZ; (stock_id, trade_date, source, new_version)
        anahtariyla yeni satir eklenir. Anahtar zaten varsa yazilmaz.
        Donus: yazildiysa True, atlandiysa False.
        """
        inserted = self._insert_one(stock_id, new_bar, str(new_version), "raw")
        if inserted and self.conn is not None:
            self.conn.commit()
        return inserted

    def _insert_one(
        self, stock_id: str, bar: PriceBar, data_version: str, data_layer: str
    ) -> bool:
        if self.conn is not None:
            cur = self.conn.execute(
                """
                INSERT OR IGNORE INTO stock_prices_daily
                    (stock_id, trade_date, source, data_version,
                     open, high, low, close, volume, data_layer)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stock_id,
                    bar.trade_date,
                    bar.source,
                    data_version,
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    int(bar.volume),
                    data_layer,
                ),
            )
            return cur.rowcount == 1
        key = (stock_id, bar.trade_date, bar.source, data_version)
        if key in self._mem:
            return False
        self._seq += 1
        self._mem[key] = {
            "seq": self._seq,
            "stock_id": stock_id,
            "trade_date": bar.trade_date,
            "source": bar.source,
            "data_version": data_version,
            "data_layer": data_layer,
            "bar": bar,
        }
        return True

    # ------------------------------------------------------------------ #
    # Okuma
    # ------------------------------------------------------------------ #
    def get_last_trade_date(self, stock_id: str) -> Optional[str]:
        """DB/bellek icindeki en yeni trade_date; kayit yoksa None."""
        if self.conn is not None:
            row = self.conn.execute(
                "SELECT MAX(trade_date) AS last_date FROM stock_prices_daily "
                "WHERE stock_id = ?",
                (stock_id,),
            ).fetchone()
            return row["last_date"] if row and row["last_date"] is not None else None
        dates = [
            rec["trade_date"]
            for rec in self._mem.values()
            if rec["stock_id"] == stock_id
        ]
        return max(dates) if dates else None

    def latest_version(
        self, stock_id: str, trade_date: str, source: str
    ) -> Optional[str]:
        """(stock_id, trade_date, source) icin en son data_version; yoksa None."""
        trade_date = str(trade_date)
        if self.conn is not None:
            row = self.conn.execute(
                "SELECT data_version FROM stock_prices_daily "
                "WHERE stock_id = ? AND trade_date = ? AND source = ? "
                "ORDER BY id DESC LIMIT 1",
                (stock_id, trade_date, source),
            ).fetchone()
            return row["data_version"] if row else None
        candidates = [
            rec
            for rec in self._mem.values()
            if rec["stock_id"] == stock_id
            and rec["trade_date"] == trade_date
            and rec["source"] == source
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda r: r["seq"])["data_version"]

    def get_bar(
        self, stock_id: str, trade_date: str, source: Optional[str] = None
    ) -> Optional[PriceBar]:
        """Belirli bir gunun en son surumlu bar'i; yoksa None."""
        trade_date = str(trade_date)
        if self.conn is not None:
            if source is None:
                row = self.conn.execute(
                    "SELECT * FROM stock_prices_daily "
                    "WHERE stock_id = ? AND trade_date = ? "
                    "ORDER BY id DESC LIMIT 1",
                    (stock_id, trade_date),
                ).fetchone()
            else:
                row = self.conn.execute(
                    "SELECT * FROM stock_prices_daily "
                    "WHERE stock_id = ? AND trade_date = ? AND source = ? "
                    "ORDER BY id DESC LIMIT 1",
                    (stock_id, trade_date, source),
                ).fetchone()
            return self._row_to_bar(row) if row else None
        candidates = [
            rec
            for rec in self._mem.values()
            if rec["stock_id"] == stock_id
            and rec["trade_date"] == trade_date
            and (source is None or rec["source"] == source)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda r: r["seq"])["bar"]

    def get_bars(self, stock_id: str, days: Optional[int] = None) -> List[PriceBar]:
        """Her (trade_date, source) icin EN SON surum, tarih sirali (artan).

        days verilirse en yeni `days` kayit dondurulur.
        """
        if self.conn is not None:
            rows = self.conn.execute(
                """
                SELECT p.* FROM stock_prices_daily p
                INNER JOIN (
                    SELECT trade_date, source, MAX(id) AS max_id
                    FROM stock_prices_daily
                    WHERE stock_id = ?
                    GROUP BY trade_date, source
                ) m ON p.id = m.max_id
                ORDER BY p.trade_date ASC, p.source ASC
                """,
                (stock_id,),
            ).fetchall()
            bars = [self._row_to_bar(r) for r in rows]
        else:
            latest: Dict[Tuple[str, str], dict] = {}
            for rec in self._mem.values():
                if rec["stock_id"] != stock_id:
                    continue
                key = (rec["trade_date"], rec["source"])
                if key not in latest or rec["seq"] > latest[key]["seq"]:
                    latest[key] = rec
            bars = [rec["bar"] for rec in latest.values()]
            bars.sort(key=lambda b: (b.trade_date, b.source))
        if days is not None:
            bars = bars[-int(days):]
        return bars

    def count_bars(self, stock_id: str) -> int:
        """Toplam satir sayisi (tum surumler dahil)."""
        if self.conn is not None:
            row = self.conn.execute(
                "SELECT COUNT(*) AS n FROM stock_prices_daily WHERE stock_id = ?",
                (stock_id,),
            ).fetchone()
            return int(row["n"]) if row else 0
        return sum(1 for rec in self._mem.values() if rec["stock_id"] == stock_id)

    # ------------------------------------------------------------------ #
    # Yardimci
    # ------------------------------------------------------------------ #
    @staticmethod
    def _row_to_bar(row: sqlite3.Row) -> PriceBar:
        """DB satirini PriceBar'a cevirir (tabloda currency/adjusted_close yok)."""
        return PriceBar(
            stock_id=row["stock_id"],
            trade_date=row["trade_date"],
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=int(row["volume"]),
            adjusted_close=None,
            currency=DEFAULT_CURRENCY,
            source=row["source"],
        )
