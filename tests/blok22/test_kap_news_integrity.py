"""BLOK 22 - test_kap_news_integrity: KAP + haber butunlugu kabul testleri (9 test).

Kapsam: KAP duplikasyon: ayni bildirim tek kayit (2); KAP revizyon:
revises zinciri SUPERSEDED/REVISED (2); haber yanlis eslesme: benzer
isim baska sirkete baglanmaz/queue (2); haber duplikasyon: ajans
kopyasi + ayni URL tek (3). GERCEK BLOK 11/12 modulleri kullanilir.
"""
from __future__ import annotations

from datetime import datetime

from app.services.stock_scanning.kap_collection import (
    DUPLICATE,
    KapCollector,
    KapFeed,
    KapMatcher,
    KapNotification,
    KapStorage,
    RevisionStatus,
)
from app.services.stock_scanning.news.aliases import AliasStore
from app.services.stock_scanning.news.dedupe import (
    AGENCY_COPY,
    DUPLICATE_SAME_URL,
    DedupeEngine,
)
from app.services.stock_scanning.news.matcher import NewsMatcher
from app.services.stock_scanning.news.models import NewsRecord
from app.services.stock_scanning.symbol_identity import SymbolIdentityService

ISO_NOW = "2025-06-03T08:00:00Z"
CUTOFF = "2025-06-02T08:00:00Z"


def _kap_storage():
    return KapStorage(clock=lambda: ISO_NOW)


def _notification(nid, previous=None, revision=RevisionStatus.ORIGINAL):
    return KapNotification(
        notification_id=nid,
        stock_id="STK-000001",
        symbol="X001",
        title=f"Bildirim {nid}",
        notification_type="ODA",
        subtype="GENEL",
        published_at="2025-06-03T07:00:00Z",
        source_timestamp="2025-06-03T07:00:00Z",
        body="bildirim metni",
        summary_raw=f"ozet {nid}",
        amount=None,
        currency="TRY",
        official_url=f"https://kap.example.tr/{nid}",
        attachment_urls=[],
        revision_status=revision,
        previous_notification_id=previous,
        collected_at=ISO_NOW,
    )


# 1) KAP duplikasyon: ayni bildirim tek kayit ------------------------------------
def test_kap_duplicate_notification_single_record():
    storage = _kap_storage()
    first = storage.insert(_notification("N-1"))
    second = storage.insert(_notification("N-1"))
    assert first.status != DUPLICATE
    assert second.status == DUPLICATE  # ikinci kez EKLENMEZ


def test_kap_duplicate_not_counted_twice():
    storage = _kap_storage()
    storage.insert(_notification("N-1"))
    storage.insert(_notification("N-1"))
    storage.insert(_notification("N-2"))
    assert storage.get_record("N-1") is not None
    # blok11 kalibi: kayit sayisi gercek public sayac API'si ile dogrulanir
    assert storage.count() == 2  # toplam kayit 2 (N-1, N-2)


# 2) KAP revizyon: revises zinciri SUPERSEDED/REVISED -----------------------------
class _MockKapFetcher:
    """Enjekte KAP kaynagi (gercek ag YOK): blok11 MockKapFetcher deseni.

    Sozlesme: fetch_feed(cutoff_iso) -> list[dict];
    fetch_notification(nid) -> dict | None.
    """

    def __init__(self, feed_items=None, details=None):
        self.feed_items = list(feed_items or [])
        self.details = dict(details or {})

    def fetch_feed(self, cutoff_iso):
        return [dict(i) for i in self.feed_items]

    def fetch_notification(self, notification_id):
        detail = self.details.get(notification_id)
        return dict(detail) if detail is not None else None


def _feed_item(nid, published="2025-06-03T07:00:00Z", **extra):
    """Merkezi akis bildirim kaydi (blok11 make_item deseni)."""
    item = {
        "notification_id": nid,
        "symbol": "X001",
        "title": f"Bildirim {nid}",
        "notification_type": "ODA",
        "subtype": "GENEL",
        "published_at": published,
        "source_timestamp": published,
        "summary_raw": f"ozet {nid}",
        "official_url": f"https://kap.example.tr/{nid}",
    }
    item.update(extra)
    return item


def _revision_collector(feed_items, details):
    """Gercek kimlik+matcher+storage zinciri; sahte yalniz fetcher.

    blok11 build_stack kalibi; revizyon zinciri collector akisiyla
    kurulur (revises alani -> mark_superseded otomatik).
    """
    identity = SymbolIdentityService(
        clock=lambda: datetime(2025, 6, 3, 8, 0, 0)
    )
    sid = identity.register_stock("Revizyon Sirketi")
    identity.add_symbol(sid, "kap", "X001")
    fetcher = _MockKapFetcher(feed_items, details)
    feed = KapFeed(fetcher, clock=lambda: ISO_NOW)
    matcher = KapMatcher(identity, lambda: [sid])
    storage = _kap_storage()
    collector = KapCollector(feed, matcher, storage, clock=lambda: ISO_NOW)
    return collector, storage


def test_kap_revision_supersedes_old_record():
    collector, storage = _revision_collector(
        feed_items=[
            _feed_item("N-1"),
            _feed_item("N-2", published="2025-06-03T07:10:00Z", revises="N-1"),
        ],
        details={
            "N-1": {"body": "orijinal metin",
                    "source_timestamp": "2025-06-03T07:01:00Z"},
            "N-2": {"body": "revize metin",
                    "source_timestamp": "2025-06-03T07:11:00Z"},
        },
    )
    collector.collect(CUTOFF)
    old = storage.get_record("N-1")
    # collector akisi eski kaydi SUPERSEDED isaretler + yenisine baglar
    assert old.notification.revision_status == RevisionStatus.SUPERSEDED
    assert old.superseded_by == "N-2"


def test_kap_revision_new_record_revised_and_chained():
    storage = _kap_storage()
    storage.insert(_notification("N-1"))
    storage.insert(_notification(
        "N-2", previous="N-1", revision=RevisionStatus.REVISED
    ))
    new = storage.get_record("N-2")
    assert new.notification.revision_status == RevisionStatus.REVISED
    assert new.notification.previous_notification_id == "N-1"
    # eski kayit KORUNUR (silinmez/uzerine yazilmaz)
    assert storage.get_record("N-1") is not None


# 3) haber yanlis eslesme: benzer isim baska sirkete baglanmaz --------------------
def _store():
    store = AliasStore()
    store.register(
        "STK-IS",
        code="ISCTR",
        full_name="Türkiye İş Bankası A.Ş.",
        short_name="İş Bankası",
    )
    store.register(
        "STK-ISY",
        code="ISMEN",
        full_name="İş Yatırım Menkul Değerler A.Ş.",
        short_name="İş Yatırım",
    )
    return store


def _news(nid, title, body="", url="", source="Site", published=None):
    return NewsRecord(
        news_id=nid,
        title=title,
        body=body,
        source_name=source,
        original_url=url,
        published_at=published or datetime(2025, 6, 3, 7, 0, 0),
    )


def test_news_similar_name_not_connected_to_wrong_stock():
    matcher = NewsMatcher(_store())
    res = matcher.match(
        _news("N-1", "İş Yatırım Menkul Değerler A.Ş. temettü açıkladı")
    )
    isbank = [r for r in res if r.stock_id == "STK-IS"]
    # "İş Yatırım" haberi İş Bankası'na KESIN baglanmaz
    assert all(not r.is_confirmed for r in isbank)
    correct = [r for r in res if r.stock_id == "STK-ISY"]
    assert correct and correct[0].is_confirmed is True


def test_news_ambiguous_alias_not_auto_confirmed():
    # "İş" tek basina iki sirkete de isaret edebilir -> otomatik teyit YOK
    matcher = NewsMatcher(_store())
    res = matcher.match(_news("N-2", "İş hisseleri bugün hareketli"))
    assert all(not r.is_confirmed for r in res)


# 4) haber duplikasyon: ajans kopyasi + ayni URL tek ------------------------------
def test_news_same_url_single_canonical():
    engine = DedupeEngine()
    a = _news("N-1", "Sirket bilancosunu açıkladı", url="https://x.tr/haber-1")
    b = _news("N-2", "Sirket bilancosunu açıkladı", url="https://x.tr/haber-1")
    canonical, groups = engine.dedupe([a, b])
    assert len(canonical) == 1  # ayni URL tek kayit
    assert groups and DUPLICATE_SAME_URL in groups[0].reason_codes


def test_news_agency_copy_not_canonical():
    engine = DedupeEngine()
    agency = _news(
        "N-AA", "Anadolu Ajansı: Sirket temettü kararını duyurdu",
        source="Anadolu Ajansı", url="https://aa.tr/1",
        published=datetime(2025, 6, 3, 6, 30, 0),
    )
    copy_site = _news(
        "N-SITE", "Anadolu Ajansı: Sirket temettü kararını duyurdu",
        source="HaberSitesi", url="https://site.tr/kopya",
        published=datetime(2025, 6, 3, 7, 0, 0),
    )
    canonical, groups = engine.dedupe([agency, copy_site])
    assert canonical[0].news_id == "N-AA"  # ajans canonical
    assert groups and AGENCY_COPY in groups[0].reason_codes


def test_news_dedupe_group_structure():
    engine = DedupeEngine()
    a = _news("N-1", "Sirket bilancosunu açıkladı", url="https://x.tr/h1")
    b = _news("N-2", "Sirket bilancosunu açıkladı", url="https://x.tr/h1")
    c = _news("N-3", "Baska bir haber tamamen farkli icerik", url="https://x.tr/h2")
    canonical, groups = engine.dedupe([a, b, c])
    canonical_ids = {r.news_id for r in canonical}
    assert "N-3" in canonical_ids  # bagimsiz haber canonical kalir
    assert len(groups) == 1
    assert groups[0].canonical_news_id in {"N-1", "N-2"}
    assert len(groups[0].duplicates) == 1
