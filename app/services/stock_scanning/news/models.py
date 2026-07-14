"""BLOK 12 - Haber Toplama, Eslestirme ve Duplikasyon: veri modelleri (models.py).

Standart haber kaydi NewsRecord TAM 10 alanlidir (SPEC bolum 3):
news_id, title, body, source_name, original_url, published_at, updated_at,
author, content_type, collected_at.

KAPSAM KILIDI: Bu modul haberin ton/onem/etki puanini HESAPLAMAZ ve bu
amaçla alan TANIMLAMAZ (o is Bolum 7'nindir). Eslestirme tarafinda yalnizca
SPEC bolum 3'te tanimli guven skoru (match_score) vardir.

Dis bagimlilik yoktur (stdlib: dataclasses, enum, datetime, typing).
Dosya/identifier ASCII; docstring'ler Turkce.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class ContentType(str, Enum):
    """Haber icerik tipi (etiketleme sonucu, SPEC bolum 3/8).

    - NEWS: standart haber (varsayilan).
    - ADVERTISEMENT: reklam / advertorial / tanitim yazisi.
    - SPONSORED: sponsorlu icerik / is birligi.
    - FORUM: forum / kullanici yorumu.
    - AUTO_PRICE_TABLE: otomatik fiyat/oran tablosu (dedupe ve dogrulama
      kredisine katilmaz).
    - UNKNOWN: henuz etiketlenmemis / siniflandirilamamis.
    """

    NEWS = "NEWS"
    ADVERTISEMENT = "ADVERTISEMENT"
    SPONSORED = "SPONSORED"
    FORUM = "FORUM"
    AUTO_PRICE_TABLE = "AUTO_PRICE_TABLE"
    UNKNOWN = "UNKNOWN"


class MatchMethod(str, Enum):
    """Eslestirme yontemi (SPEC bolum 3).

    OLD_NAME / OLD_CODE eslesmeleri dogal olarak "historical" etiketlidir
    (ayri alan gerekmez; yontem adi bunu tasir).
    """

    CODE = "CODE"
    FULL_NAME = "FULL_NAME"
    SHORT_NAME = "SHORT_NAME"
    OLD_NAME = "OLD_NAME"
    OLD_CODE = "OLD_CODE"
    BRAND = "BRAND"
    SUBSIDIARY = "SUBSIDIARY"
    AFFILIATE = "AFFILIATE"
    EXECUTIVE = "EXECUTIVE"
    EVENT_DATE = "EVENT_DATE"
    AI_ASSISTED = "AI_ASSISTED"
    NONE = "NONE"


@dataclass
class NewsRecord:
    """Standart haber kaydi — TAM 10 alan (SPEC bolum 3).

    1. news_id (benzersiz) 2. title 3. body 4. source_name
    5. original_url 6. published_at 7. updated_at (None olabilir)
    8. author (None olabilir) 9. content_type 10. collected_at
    """

    news_id: str
    title: str = ""
    body: str = ""
    source_name: str = ""
    original_url: str = ""
    published_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    author: Optional[str] = None
    content_type: ContentType = ContentType.UNKNOWN
    collected_at: Optional[datetime] = None


@dataclass
class MatchResult:
    """Tek bir hisse adayina iliskin eslestirme sonucu (SPEC bolum 3/6).

    - stock_id: aday hisse (None olabilir — eslesme yok).
    - match_score: 0-100 arasi guven skoru (int).
    - match_method: eslesmeyi saglayan varlik tipi.
    - matched_entity: eslesen varlik metni (orijinal, normalize edilmemis).
    - is_confirmed: True ise haber bu hisseye KESIN baglanir
      (kural motoru karari; AI tek basina teyit edemez).
    - needs_review: dusuk guven / belirsizlik durumunda inceleme isareti.
    """

    stock_id: Optional[str] = None
    match_score: int = 0
    match_method: MatchMethod = MatchMethod.NONE
    matched_entity: str = ""
    is_confirmed: bool = False
    needs_review: bool = False


@dataclass
class DedupeResult:
    """Bir duplikasyon grubunun ozeti (SPEC bolum 3/7).

    - canonical_news_id: grubun temsilci (kanonik) haberi.
    - duplicates: kanonik disindaki haber kimlikleri.
    - reason_codes: grubu olusturan neden kodlari
      (DUPLICATE_SAME_URL, DUPLICATE_TEXT, DUPLICATE_EVENT_TIME,
      DUPLICATE_SAME_EVENT, AGENCY_COPY).
    """

    canonical_news_id: str
    duplicates: List[str] = field(default_factory=list)
    reason_codes: List[str] = field(default_factory=list)
