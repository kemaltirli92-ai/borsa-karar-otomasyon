"""BLOK 11 - KAP Bildirim Toplama: veri modelleri (models.py).

Standart KAP bildirim kaydi KapNotification TAM 17 alanlidir (SPEC bolum 3).
notification_id benzersizdir; revizyon eski kaydin UZERINE YAZILMAZ, yeni
surum REVISED + previous_notification_id ile zincirlenir; iptal CANCELLED
kaydi olarak ayrica tutulur.

KAPSAM KILIDI: Bu modulde bildirimin olumlu/olumsuz etkisine iliskin
hicbir alan veya hesaplama YOKTUR (alani tanimlanmamistir).

Dis bagimlilik yoktur (stdlib: dataclasses, enum, typing).
Dosya/identifier ASCII; docstring'ler Turkce.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class RevisionStatus(str, Enum):
    """Bildirim revizyon durumu.

    - ORIGINAL: ilk (orijinal) bildirim.
    - REVISED: duzeltilmis bildirim — eski kayit SUPERSEDED isaretlenir,
      yeni kayit REVISED + previous_notification_id tasir.
    - CANCELLED: iptal bildirimi — eski kayit silinmez/korunur, iptal
      kaydi ayrica tutulur ve hedef previous_notification_id ile isaretlenir.
    - SUPERSEDED: yerini yeni surume birakmis eski kayit (uzerine YAZILMAZ).
    """

    ORIGINAL = "ORIGINAL"
    REVISED = "REVISED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class KapRunStatus(str, Enum):
    """Toplama calismasi durumu (SPEC bolum 3)."""

    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class KapHealth(str, Enum):
    """KAP kaynagi saglik durumu."""

    OK = "OK"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"


@dataclass
class AttachmentMeta:
    """Ek dosya meta bilgisi.

    KURAL: ek dosya INDIRILMEZ; sadece meta bilgisi kaydedilir.
    fetched her zaman False baslar (indirme bu modulde yapilmaz).
    """

    url: str
    file_name: Optional[str] = None
    file_type: Optional[str] = None
    size_bytes: Optional[int] = None
    fetched: bool = False
    fetched_at: Optional[str] = None


@dataclass
class KapNotification:
    """Standart KAP bildirim kaydi — TAM 17 alan (SPEC bolum 3).

    1. notification_id (benzersiz) 2. stock_id 3. symbol 4. title
    5. notification_type (FR/ODA/MSL/DG ... serbest str) 6. subtype
    7. published_at 8. source_timestamp 9. body (tam metin; None olabilir)
    10. summary_raw 11. amount 12. currency 13. official_url
    14. attachment_urls 15. revision_status 16. previous_notification_id
    17. collected_at
    """

    notification_id: str
    stock_id: Optional[str] = None
    symbol: Optional[str] = None
    title: str = ""
    notification_type: str = "DG"
    subtype: Optional[str] = None
    published_at: str = ""
    source_timestamp: Optional[str] = None
    body: Optional[str] = None
    summary_raw: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    official_url: Optional[str] = None
    attachment_urls: List[str] = field(default_factory=list)
    revision_status: RevisionStatus = RevisionStatus.ORIGINAL
    previous_notification_id: Optional[str] = None
    collected_at: str = ""


@dataclass
class KapCollectionResult:
    """collect() sonucu (SPEC bolum 3).

    Hata durumunda exception DISARI FIRLATILMAZ; durum bu nesnede tasimlidir
    (KAP kesintisi fiyat taramasini durdurmaz).
    """

    run_id: str
    status: KapRunStatus
    fetched_count: int = 0
    matched_count: int = 0
    stored_count: int = 0
    skipped_duplicates: int = 0
    revisions: int = 0
    cancellations: int = 0
    errors: List[str] = field(default_factory=list)
    kap_health: KapHealth = KapHealth.OK
