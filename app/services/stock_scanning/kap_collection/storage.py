"""BLOK 11 - KAP bildirim depolama (storage.py).

KapStorage(conn=None, clock=None):
- conn=None -> bellek ici depolama (test/hizli kullanim).
- conn verilirse SQLite kap_notifications tablosu kullanilir (BLOK 7
  migrator ile olusturulmus DB'ye EK tablo; mevcut semaya DOKUNULMAZ —
  tablo yoksa CREATE TABLE IF NOT EXISTS ile olusturulur).

Kurallar:
- notification_id UNIQUE: ayni no ikinci kez YAZILMAZ (duplicate).
- Revizyonda eski kaydin UZERINE YAZILMAZ: eski SUPERSEDED + superseded_by,
  yeni kayit REVISED + previous_notification_id; version_no artar.
- Iptalde CANCELLED kaydi olusur, hedef kayit KORUNUR.
- get_history(notification_id): surum zincirini (eski->yeni) dondurur.

KAPSAM KILIDI: tablo ve kayitlarda etki/yon alani YOKTUR.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional

from .models import AttachmentMeta, KapNotification, RevisionStatus

KAP_TABLE = "kap_notifications"

# insert() durum kodlari
INSERTED = "inserted"
DUPLICATE = "duplicate"
REVISION_CHAIN = "revision_chain"

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {KAP_TABLE} (
    notification_id TEXT PRIMARY KEY,
    stock_id TEXT,
    symbol TEXT,
    title TEXT,
    notification_type TEXT,
    subtype TEXT,
    published_at TEXT,
    source_timestamp TEXT,
    body TEXT,
    summary_raw TEXT,
    amount REAL,
    currency TEXT,
    official_url TEXT,
    attachment_urls TEXT,
    attachments_meta TEXT,
    revision_status TEXT,
    previous_notification_id TEXT,
    collected_at TEXT,
    version_no INTEGER NOT NULL DEFAULT 1,
    superseded_by TEXT
)
"""


def _utcnow_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class StoredResult:
    """insert() sonucu: inserted | duplicate | revision_chain."""

    status: str
    notification_id: str
    previous_notification_id: Optional[str] = None
    version_no: int = 1


@dataclass
class StoredRecord:
    """Depodaki tam kayit (bildirim + surum meta + ek meta)."""

    notification: KapNotification
    version_no: int = 1
    superseded_by: Optional[str] = None
    attachments: List[AttachmentMeta] = field(default_factory=list)


class KapStorage:
    """KAP bildirim deposu (bellek ici veya SQLite)."""

    def __init__(
        self,
        conn: Optional[sqlite3.Connection] = None,
        clock: Optional[Callable[[], str]] = None,
    ):
        self.conn = conn
        self._clock: Callable[[], str] = clock or _utcnow_iso
        # Bellek ici kayitlar: notification_id -> StoredRecord
        self._mem: Dict[str, StoredRecord] = {}
        # Son calisma durumu (readiness icin; her iki modda bellekte)
        self._last_run_status: Optional[str] = None
        if self.conn is not None:
            self.conn.row_factory = sqlite3.Row
            self.conn.execute(_SCHEMA)
            self.conn.commit()

    @property
    def is_memory(self) -> bool:
        return self.conn is None

    # ------------------------------------------------------------------ #
    # Yazim
    # ------------------------------------------------------------------ #
    def insert(
        self,
        notification: KapNotification,
        attachments: Optional[List[AttachmentMeta]] = None,
    ) -> StoredResult:
        """Bildirimi yazar. Ayni notification_id -> duplicate (yazilmaz).

        previous_notification_id tasiysa kayit surum zincirinin parcasidir
        (revision_chain).
        """
        nid = notification.notification_id
        prev = notification.previous_notification_id
        if self._exists(nid):
            return StoredResult(
                status=DUPLICATE, notification_id=nid, previous_notification_id=prev
            )
        version_no = 1
        if prev:
            old = self.get_record(prev)
            if old is not None:
                version_no = old.version_no + 1
        status = REVISION_CHAIN if prev else INSERTED
        record = StoredRecord(
            notification=self._copy(notification),
            version_no=version_no,
            superseded_by=None,
            attachments=list(attachments or []),
        )
        self._put(record)
        return StoredResult(
            status=status,
            notification_id=nid,
            previous_notification_id=prev,
            version_no=version_no,
        )

    def mark_superseded(self, old_id: str, new_id: str) -> bool:
        """Eski kaydi SUPERSEDED isaretler ve yenisine baglar. Yoksa False.

        Eski kayit UZERINE YAZILMAZ — sadece durum/zincir alanlari guncellenir.
        """
        if self.conn is not None:
            row = self.conn.execute(
                f"SELECT notification_id FROM {KAP_TABLE} WHERE notification_id = ?",
                (old_id,),
            ).fetchone()
            if row is None:
                return False
            self.conn.execute(
                f"UPDATE {KAP_TABLE} SET revision_status = ?, superseded_by = ? "
                f"WHERE notification_id = ?",
                (RevisionStatus.SUPERSEDED.value, new_id, old_id),
            )
            self.conn.commit()
            return True
        rec = self._mem.get(old_id)
        if rec is None:
            return False
        rec.notification.revision_status = RevisionStatus.SUPERSEDED
        rec.superseded_by = new_id
        return True

    # ------------------------------------------------------------------ #
    # Okuma
    # ------------------------------------------------------------------ #
    def get(self, notification_id: str) -> Optional[KapNotification]:
        rec = self.get_record(notification_id)
        return rec.notification if rec else None

    def get_record(self, notification_id: str) -> Optional[StoredRecord]:
        if self.conn is not None:
            row = self.conn.execute(
                f"SELECT * FROM {KAP_TABLE} WHERE notification_id = ?",
                (notification_id,),
            ).fetchone()
            return self._row_to_record(row) if row else None
        return self._mem.get(notification_id)

    def _all_records(self) -> List[StoredRecord]:
        """Tum kayitlar (published_at, notification_id sirali)."""
        if self.conn is not None:
            rows = self.conn.execute(
                f"SELECT * FROM {KAP_TABLE} "
                f"ORDER BY published_at ASC, notification_id ASC"
            ).fetchall()
            return [self._row_to_record(r) for r in rows]
        records = list(self._mem.values())
        records.sort(
            key=lambda r: (r.notification.published_at, r.notification.notification_id)
        )
        return records

    def get_history(self, notification_id: str) -> List[KapNotification]:
        """Surum zinciri (en eski -> en yeni). Kayit yoksa bos liste.

        Once previous_notification_id halkalariyla koke inilir, sonra
        superseded_by halkalariyla ileri yurunur. Zincire previous ile
        baglanan ama superseded_by ile baglanmayan kayitlar (or. CANCELLED
        iptal kayitlari) zincirin sonuna eklenir — hedef kayit korunur.
        """
        if self.get_record(notification_id) is None:
            return []
        # Koke in
        root_id = notification_id
        seen = {root_id}
        while True:
            rec = self.get_record(root_id)
            prev = rec.notification.previous_notification_id if rec else None
            if not prev or prev in seen or self.get_record(prev) is None:
                break
            root_id = prev
            seen.add(root_id)
        # Kokten ileri yuru
        chain: List[KapNotification] = []
        current = root_id
        seen2 = set()
        while current and current not in seen2:
            seen2.add(current)
            rec = self.get_record(current)
            if rec is None:
                break
            chain.append(rec.notification)
            current = rec.superseded_by
        # Zincire previous ile bagli diger kayitlar (iptal kayitlari)
        chain_ids = {n.notification_id for n in chain}
        for rec in self._all_records():
            nid = rec.notification.notification_id
            if nid in chain_ids:
                continue
            if rec.notification.previous_notification_id in chain_ids:
                chain.append(rec.notification)
                chain_ids.add(nid)
        return chain

    def get_by_stock(
        self, stock_id: str, since: Optional[str] = None
    ) -> List[KapNotification]:
        """Hisseye bagli tum bildirimler (published_at, notification_id sirali).

        since verilirse published_at >= since olanlar dondurulur.
        """
        if self.conn is not None:
            rows = self.conn.execute(
                f"SELECT * FROM {KAP_TABLE} WHERE stock_id = ? "
                f"ORDER BY published_at ASC, notification_id ASC",
                (stock_id,),
            ).fetchall()
            items = [self._row_to_record(r).notification for r in rows]
        else:
            items = [
                rec.notification
                for rec in self._mem.values()
                if rec.notification.stock_id == stock_id
            ]
            items.sort(key=lambda n: (n.published_at, n.notification_id))
        if since is not None:
            items = [n for n in items if n.published_at >= since]
        return items

    def count(self) -> int:
        if self.conn is not None:
            row = self.conn.execute(
                f"SELECT COUNT(*) AS n FROM {KAP_TABLE}"
            ).fetchone()
            return int(row["n"]) if row else 0
        return len(self._mem)

    # ------------------------------------------------------------------ #
    # Calisma durumu (readiness icin)
    # ------------------------------------------------------------------ #
    def record_run(self, status) -> None:
        """Son toplama calismasinin durumunu kaydeder (PARTIAL/FAILED izi)."""
        self._last_run_status = getattr(status, "value", status)

    def last_run_status(self) -> Optional[str]:
        return self._last_run_status

    # ------------------------------------------------------------------ #
    # Ic yardimcilar
    # ------------------------------------------------------------------ #
    def _exists(self, notification_id: str) -> bool:
        if self.conn is not None:
            row = self.conn.execute(
                f"SELECT 1 AS x FROM {KAP_TABLE} WHERE notification_id = ?",
                (notification_id,),
            ).fetchone()
            return row is not None
        return notification_id in self._mem

    @staticmethod
    def _copy(notification: KapNotification) -> KapNotification:
        """Depoya yazilan kopya (cagiranin nesnesi izole kalir)."""
        return KapNotification(
            notification_id=notification.notification_id,
            stock_id=notification.stock_id,
            symbol=notification.symbol,
            title=notification.title,
            notification_type=notification.notification_type,
            subtype=notification.subtype,
            published_at=notification.published_at,
            source_timestamp=notification.source_timestamp,
            body=notification.body,
            summary_raw=notification.summary_raw,
            amount=notification.amount,
            currency=notification.currency,
            official_url=notification.official_url,
            attachment_urls=list(notification.attachment_urls or []),
            revision_status=notification.revision_status,
            previous_notification_id=notification.previous_notification_id,
            collected_at=notification.collected_at,
        )

    def _put(self, record: StoredRecord) -> None:
        n = record.notification
        if self.conn is not None:
            self.conn.execute(
                f"""
                INSERT INTO {KAP_TABLE}
                    (notification_id, stock_id, symbol, title, notification_type,
                     subtype, published_at, source_timestamp, body, summary_raw,
                     amount, currency, official_url, attachment_urls,
                     attachments_meta, revision_status, previous_notification_id,
                     collected_at, version_no, superseded_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    n.notification_id,
                    n.stock_id,
                    n.symbol,
                    n.title,
                    n.notification_type,
                    n.subtype,
                    n.published_at,
                    n.source_timestamp,
                    n.body,
                    n.summary_raw,
                    n.amount,
                    n.currency,
                    n.official_url,
                    json.dumps(list(n.attachment_urls or []), ensure_ascii=False),
                    json.dumps(
                        [
                            {
                                "url": a.url,
                                "file_name": a.file_name,
                                "file_type": a.file_type,
                                "size_bytes": a.size_bytes,
                                "fetched": a.fetched,
                                "fetched_at": a.fetched_at,
                            }
                            for a in record.attachments
                        ],
                        ensure_ascii=False,
                    ),
                    getattr(n.revision_status, "value", n.revision_status),
                    n.previous_notification_id,
                    n.collected_at,
                    record.version_no,
                    record.superseded_by,
                ),
            )
            self.conn.commit()
            return
        self._mem[n.notification_id] = record

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> StoredRecord:
        attachments = [
            AttachmentMeta(
                url=a.get("url"),
                file_name=a.get("file_name"),
                file_type=a.get("file_type"),
                size_bytes=a.get("size_bytes"),
                fetched=bool(a.get("fetched")),
                fetched_at=a.get("fetched_at"),
            )
            for a in json.loads(row["attachments_meta"] or "[]")
        ]
        notification = KapNotification(
            notification_id=row["notification_id"],
            stock_id=row["stock_id"],
            symbol=row["symbol"],
            title=row["title"] or "",
            notification_type=row["notification_type"] or "",
            subtype=row["subtype"],
            published_at=row["published_at"] or "",
            source_timestamp=row["source_timestamp"],
            body=row["body"],
            summary_raw=row["summary_raw"],
            amount=row["amount"],
            currency=row["currency"],
            official_url=row["official_url"],
            attachment_urls=json.loads(row["attachment_urls"] or "[]"),
            revision_status=RevisionStatus(row["revision_status"]),
            previous_notification_id=row["previous_notification_id"],
            collected_at=row["collected_at"] or "",
        )
        return StoredRecord(
            notification=notification,
            version_no=int(row["version_no"]),
            superseded_by=row["superseded_by"],
            attachments=attachments,
        )
