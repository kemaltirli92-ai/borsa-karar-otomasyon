"""BLOK 11 - KAP Bildirim Toplama: TAM 100 pytest testi.

Kategoriler (toplam = 100, SPEC BLOK 11 bolum 9):
1. Merkezi akis toplama (16): 6 adim zinciri, kesimden sonrasi, detay
   tek-cekim onbellegi.
2. Tekrarlanan bildirim (12): ayni notification_id ikinci kez eklenmez.
3. Revizyon (14): eski uzerine yazilmaz, SUPERSEDED+REVISED zinciri,
   previous_notification_id.
4. Iptal (10): CANCELLED kaydi, hedef korunur.
5. Yanlis sirket eslesmesi (14): belirsiz eslesme yapilmaz, evren disi
   reddedilir, pending kuyrugu.
6. KAP kesintisi (12): PARTIAL/FAILED, fiyat taramasi durmaz (exception
   sizmaz), kap_health DOWN.
7. Ek dosya (10): meta kaydi, dosya indirilmez, coklu ek.
8. Profil haftalik kontrol + favori hazirlik kilidi + kapsam kilidi (12).

Hicbir test ag erisimi yapmaz: tum kaynaklar mock fetcher ile enjekte
edilir. Saat enjekte edilir (deterministik). stdlib only.
"""
from __future__ import annotations

import dataclasses
import os
import sqlite3
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services.stock_scanning.kap_collection import (
    CANCELLATION_RECORDED,
    CRITICAL_BODY_MISSING,
    DETAIL_MISSING,
    DUPLICATE,
    DUPLICATE_SKIPPED,
    FAVORI_READY_BLOCKED,
    FEED_UNAVAILABLE,
    INSERTED,
    KAP_PARTIAL_BLOCK,
    MATCH_AMBIGUOUS,
    MATCHED,
    OUT_OF_UNIVERSE,
    PROFILES_CHECKED,
    PROFILES_SKIPPED_FRESH,
    REVISION_CHAIN,
    REVISION_CHAINED,
    STEP1_FEED_FETCHED,
    STEP2_MATCHED,
    STEP3_DETAIL_FETCHED,
    STEP4_ATTACHMENTS,
    STEP5_REVISION,
    STEP6_STORED,
    SYMBOL_VERIFICATION_PENDING,
    UNMATCHED,
    AttachmentMeta,
    FavoriteReadiness,
    KapCollectionResult,
    KapCollector,
    KapFeed,
    KapFeedUnavailableError,
    KapHealth,
    KapMatcher,
    KapNotification,
    KapRunStatus,
    KapStorage,
    ProfileChecker,
    RevisionStatus,
)
from app.services.stock_scanning.symbol_identity import SymbolIdentityService

# ---------------------------------------------------------------------- #
# Sabitler / saatler
# ---------------------------------------------------------------------- #
FIXED_DT = datetime(2024, 6, 30, 8, 0, 0)
ISO_NOW = "2024-06-30T08:00:00Z"
CUTOFF = "2024-06-29T08:00:00Z"

STOCK_ID = "STK-000001"
SYMBOL = "THYAO"


def iso_clock():
    """Deterministik ISO saat (str)."""
    return ISO_NOW


def dt_clock():
    """Deterministik datetime saat."""
    return FIXED_DT


# ---------------------------------------------------------------------- #
# Mock'lar / yardimcilar
# ---------------------------------------------------------------------- #
class MockKapFetcher:
    """Enjekte edilen sahte merkezi KAP kaynagi (gercek ag YOK).

    Sozlesme: fetch_feed(cutoff) -> list[dict];
    fetch_notification(nid) -> dict | None.
    """

    def __init__(self, feed_items=None, details=None, feed_exc=None, detail_exc=None):
        self.feed_items = list(feed_items or [])
        self.details = dict(details or {})
        self.feed_exc = feed_exc
        self.detail_exc = detail_exc
        self.feed_calls = []
        self.detail_calls = []

    def fetch_feed(self, cutoff_iso):
        self.feed_calls.append(cutoff_iso)
        if self.feed_exc is not None:
            raise self.feed_exc
        return [dict(i) for i in self.feed_items]

    def fetch_notification(self, notification_id):
        self.detail_calls.append(notification_id)
        if self.detail_exc is not None:
            raise self.detail_exc
        detail = self.details.get(notification_id)
        return dict(detail) if detail is not None else None


class MockIdentityService:
    """BLOK 6 resolve taklidi: mapping + belirsiz sorgular + pending kuyrugu."""

    def __init__(self, mapping=None, ambiguous=()):
        self.mapping = dict(mapping or {})
        self.ambiguous = set(ambiguous)
        self.pending = []
        self.resolve_calls = []
        self.last_resolve_ambiguous = False

    def resolve(self, query, platform=None):
        self.resolve_calls.append((query, platform))
        if query in self.ambiguous:
            self.last_resolve_ambiguous = True
            self.mark_pending(None, "AMBIGUOUS", query=query)
            return None
        self.last_resolve_ambiguous = False
        sid = self.mapping.get(query)
        if sid is None:
            return None
        return SimpleNamespace(
            stock_id=sid, matched_by="symbol", matched_symbol=query
        )

    def mark_pending(self, stock_id, reason, query=None):
        self.pending.append(
            {"stock_id": stock_id, "reason": reason, "query": query}
        )

    def get_pending_queue(self, include_resolved=False):
        return list(self.pending)


class MockProfileFetcher:
    """Haftalik profil kontrol fetcher'i (gercek ag YOK)."""

    def __init__(self, exc=None):
        self.calls = []
        self.exc = exc

    def fetch_profile(self, stock_id):
        self.calls.append(stock_id)
        if self.exc is not None:
            raise self.exc
        return {"stock_id": stock_id, "profile": "ok"}


def make_item(nid, symbol=SYMBOL, ntype="ODA", published="2024-06-30T07:00:00Z",
              **extra):
    """Merkezi akis bildirim kaydi (dict)."""
    item = {
        "notification_id": nid,
        "symbol": symbol,
        "title": f"Bildirim {nid}",
        "notification_type": ntype,
        "subtype": "GENEL",
        "published_at": published,
        "source_timestamp": published,
        "summary_raw": f"Ozet {nid}",
        "official_url": f"https://kap.example.tr/{nid}",
    }
    item.update(extra)
    return item


def make_detail(body="Tam metin govdesi", **extra):
    """Bildirim detay kaydi (dict)."""
    detail = {"body": body, "source_timestamp": "2024-06-30T07:01:00Z"}
    detail.update(extra)
    return detail


def build_stack(feed_items=None, details=None, mapping=None, universe=None,
                ambiguous=(), fetcher_exc=None, profile_checker=None):
    """Tipik toplama zinciri (feed+matcher+storage+collector)."""
    mapping = dict(mapping or {SYMBOL: STOCK_ID})
    if universe is None:
        universe = list(mapping.values())
    fetcher = MockKapFetcher(feed_items, details, feed_exc=fetcher_exc)
    feed = KapFeed(fetcher, clock=iso_clock)
    identity = MockIdentityService(mapping, ambiguous)
    matcher = KapMatcher(identity, lambda: list(universe))
    storage = KapStorage(clock=iso_clock)
    collector = KapCollector(
        feed, matcher, storage,
        profile_checker=profile_checker, clock=iso_clock,
    )
    return SimpleNamespace(
        fetcher=fetcher, feed=feed, identity=identity, matcher=matcher,
        storage=storage, collector=collector,
    )


def make_notification(nid, stock_id=STOCK_ID, ntype="ODA", body="metin",
                      revision=RevisionStatus.ORIGINAL, previous=None, **extra):
    """KapNotification uretir (dogrudan storage testleri icin)."""
    kwargs = dict(
        notification_id=nid,
        stock_id=stock_id,
        symbol=SYMBOL,
        title=f"Bildirim {nid}",
        notification_type=ntype,
        subtype="GENEL",
        published_at="2024-06-30T07:00:00Z",
        source_timestamp="2024-06-30T07:00:00Z",
        body=body,
        summary_raw=f"Ozet {nid}",
        amount=None,
        currency="TRY",
        official_url=f"https://kap.example.tr/{nid}",
        attachment_urls=[],
        revision_status=revision,
        previous_notification_id=previous,
        collected_at=ISO_NOW,
    )
    kwargs.update(extra)
    return KapNotification(**kwargs)


# ====================================================================== #
# Kategori 1 - Merkezi akis toplama (16)
# ====================================================================== #
class TestMerkeziAkis:
    def test_fetch_since_returns_only_after_cutoff(self):
        items = [
            make_item("OLD", published="2024-06-28T10:00:00Z"),
            make_item("NEW", published="2024-06-30T07:00:00Z"),
        ]
        feed = KapFeed(MockKapFetcher(items), clock=iso_clock)
        result = feed.fetch_since(CUTOFF)
        assert [i["notification_id"] for i in result] == ["NEW"]

    def test_fetch_since_passes_cutoff_to_fetcher(self):
        fetcher = MockKapFetcher([make_item("N-1")])
        feed = KapFeed(fetcher, clock=iso_clock)
        feed.fetch_since(CUTOFF)
        assert fetcher.feed_calls == [CUTOFF]

    def test_single_central_feed_call_for_many_items(self):
        items = [make_item(f"N-{i}") for i in range(5)]
        stack = build_stack(items, {i["notification_id"]: make_detail() for i in items})
        stack.collector.collect(CUTOFF)
        # 5 bildirim icin merkezi akis TEK KEZ acildi (profil/link tek tek acilmadi)
        assert stack.fetcher.feed_calls == [CUTOFF]

    def test_collect_counts_fetched_matched_stored(self):
        items = [
            make_item("N-1"),
            make_item("N-2"),
            make_item("N-3", symbol="UNKNOWN"),
        ]
        details = {"N-1": make_detail(), "N-2": make_detail()}
        stack = build_stack(items, details)
        result = stack.collector.collect(CUTOFF)
        assert result.fetched_count == 3
        assert result.matched_count == 2
        assert result.stored_count == 2
        assert result.status == KapRunStatus.COMPLETED

    def test_kap_notification_has_exactly_17_fields(self):
        names = [f.name for f in dataclasses.fields(KapNotification)]
        assert names == [
            "notification_id", "stock_id", "symbol", "title",
            "notification_type", "subtype", "published_at", "source_timestamp",
            "body", "summary_raw", "amount", "currency", "official_url",
            "attachment_urls", "revision_status", "previous_notification_id",
            "collected_at",
        ]

    def test_stored_notification_fields_populated(self):
        item = make_item("N-1", ntype="FR", title="Finansal Rapor")
        stack = build_stack([item], {"N-1": make_detail("Rapor metni")})
        stack.collector.collect(CUTOFF)
        stored = stack.storage.get("N-1")
        assert stored is not None
        assert stored.stock_id == STOCK_ID
        assert stored.symbol == SYMBOL
        assert stored.title == "Finansal Rapor"
        assert stored.notification_type == "FR"
        assert stored.published_at == "2024-06-30T07:00:00Z"
        assert stored.body == "Rapor metni"
        assert stored.official_url == "https://kap.example.tr/N-1"
        assert stored.collected_at == ISO_NOW

    def test_detail_fetched_once_for_duplicate_ids_in_run(self):
        items = [make_item("N-1"), make_item("N-1")]  # ayni id iki kez geldi
        stack = build_stack(items, {"N-1": make_detail()})
        result = stack.collector.collect(CUTOFF)
        # calisma-ici onbellek: detay TEK KEZ cekildi
        assert stack.fetcher.detail_calls.count("N-1") == 1
        assert result.stored_count == 1
        assert result.skipped_duplicates == 1
        assert stack.storage.count() == 1

    def test_fetch_detail_caches_none_result(self):
        fetcher = MockKapFetcher([], details={})
        feed = KapFeed(fetcher, clock=iso_clock)
        assert feed.fetch_detail("N-9") is None
        assert feed.fetch_detail("N-9") is None
        assert fetcher.detail_calls.count("N-9") == 1

    def test_fetcher_none_raises_unavailable(self):
        feed = KapFeed(None, clock=iso_clock)
        with pytest.raises(KapFeedUnavailableError):
            feed.fetch_since(CUTOFF)

    def test_fetcher_exception_wrapped_as_unavailable(self):
        fetcher = MockKapFetcher(feed_exc=TimeoutError("kap yanit vermedi"))
        feed = KapFeed(fetcher, clock=iso_clock)
        with pytest.raises(KapFeedUnavailableError):
            feed.fetch_since(CUTOFF)

    def test_six_step_event_order(self):
        item = make_item("N-1")
        stack = build_stack([item], {"N-1": make_detail()})
        stack.collector.collect(CUTOFF)
        codes = [e["event"] for e in stack.collector.events]
        order = [
            STEP1_FEED_FETCHED, STEP2_MATCHED, STEP3_DETAIL_FETCHED,
            STEP4_ATTACHMENTS, STEP5_REVISION, STEP6_STORED,
        ]
        positions = [codes.index(c) for c in order]
        assert positions == sorted(positions)

    def test_summary_and_source_timestamp_carried(self):
        item = make_item("N-1", summary_raw="Ham ozet metin")
        detail = make_detail(source_timestamp="2024-06-30T07:05:00Z")
        stack = build_stack([item], {"N-1": detail})
        stack.collector.collect(CUTOFF)
        stored = stack.storage.get("N-1")
        assert stored.summary_raw == "Ham ozet metin"
        assert stored.source_timestamp == "2024-06-30T07:05:00Z"

    def test_amount_currency_carried_from_detail(self):
        item = make_item("N-1")
        detail = make_detail(amount=1234567.5, currency="TRY")
        stack = build_stack([item], {"N-1": detail})
        stack.collector.collect(CUTOFF)
        stored = stack.storage.get("N-1")
        assert stored.amount == pytest.approx(1234567.5)
        assert isinstance(stored.amount, float)
        assert stored.currency == "TRY"

    def test_empty_feed_completes_with_zero_counts(self):
        stack = build_stack([], {})
        result = stack.collector.collect(CUTOFF)
        assert result.status == KapRunStatus.COMPLETED
        assert result.fetched_count == 0
        assert result.stored_count == 0
        assert result.kap_health == KapHealth.OK

    def test_no_profile_or_per_stock_fetch_in_feed(self):
        items = [make_item(f"N-{i}") for i in range(3)]
        stack = build_stack(items, {i["notification_id"]: make_detail() for i in items})
        stack.collector.collect(CUTOFF)
        # fetcher'da profil cagrisi kanali yok; detay cagrilari sadece bildirim id'leri
        assert not hasattr(stack.fetcher, "profile_calls")
        assert set(stack.fetcher.detail_calls) == {"N-0", "N-1", "N-2"}
        assert len(stack.fetcher.feed_calls) == 1

    def test_result_has_spec_fields(self):
        names = [f.name for f in dataclasses.fields(KapCollectionResult)]
        assert set(names) == {
            "run_id", "status", "fetched_count", "matched_count",
            "stored_count", "skipped_duplicates", "revisions",
            "cancellations", "errors", "kap_health",
        }
        stack = build_stack([], {})
        result = stack.collector.collect(CUTOFF)
        assert result.run_id.startswith("KAPRUN-")
        assert isinstance(result.errors, list)


# ====================================================================== #
# Kategori 2 - Tekrarlanan bildirim (12)
# ====================================================================== #
class TestTekrarlananBildirim:
    def test_insert_duplicate_returns_duplicate(self):
        storage = KapStorage(clock=iso_clock)
        first = storage.insert(make_notification("N-1"))
        second = storage.insert(make_notification("N-1"))
        assert first.status == INSERTED
        assert second.status == DUPLICATE

    def test_second_collect_skips_duplicate(self):
        item = make_item("N-1")
        stack = build_stack([item], {"N-1": make_detail()})
        first = stack.collector.collect(CUTOFF)
        second = stack.collector.collect(CUTOFF)
        assert first.stored_count == 1
        assert second.stored_count == 0
        assert second.skipped_duplicates == 1

    def test_storage_count_ignores_duplicates(self):
        storage = KapStorage(clock=iso_clock)
        storage.insert(make_notification("N-1"))
        storage.insert(make_notification("N-1"))
        storage.insert(make_notification("N-1"))
        assert storage.count() == 1

    def test_duplicate_does_not_overwrite_body(self):
        storage = KapStorage(clock=iso_clock)
        storage.insert(make_notification("N-1", body="orijinal metin"))
        storage.insert(make_notification("N-1", body="degistirilmis metin"))
        assert storage.get("N-1").body == "orijinal metin"

    def test_duplicate_with_different_content_skipped(self):
        storage = KapStorage(clock=iso_clock)
        storage.insert(make_notification("N-1", title="Ilk baslik"))
        result = storage.insert(make_notification("N-1", title="Yeni baslik"))
        assert result.status == DUPLICATE
        assert storage.get("N-1").title == "Ilk baslik"

    def test_get_returns_first_version_after_duplicate(self):
        storage = KapStorage(clock=iso_clock)
        storage.insert(make_notification("N-1", summary_raw="ilk ozet"))
        storage.insert(make_notification("N-1", summary_raw="ikinci ozet"))
        assert storage.get("N-1").summary_raw == "ilk ozet"

    def test_sqlite_duplicate_via_unique_key(self):
        conn = sqlite3.connect(":memory:")
        storage = KapStorage(conn=conn, clock=iso_clock)
        assert storage.insert(make_notification("N-1")).status == INSERTED
        assert storage.insert(make_notification("N-1")).status == DUPLICATE
        assert storage.count() == 1

    def test_two_distinct_ids_both_stored(self):
        storage = KapStorage(clock=iso_clock)
        storage.insert(make_notification("N-1"))
        storage.insert(make_notification("N-2"))
        assert storage.count() == 2

    def test_skipped_duplicates_per_run(self):
        items = [make_item("N-1"), make_item("N-2")]
        details = {"N-1": make_detail(), "N-2": make_detail()}
        stack = build_stack(items, details)
        stack.collector.collect(CUTOFF)
        second = stack.collector.collect(CUTOFF)
        assert second.skipped_duplicates == 2
        assert second.stored_count == 0

    def test_duplicate_creates_no_revision_chain(self):
        storage = KapStorage(clock=iso_clock)
        storage.insert(make_notification("N-1"))
        storage.insert(make_notification("N-1"))
        history = storage.get_history("N-1")
        assert len(history) == 1

    def test_revision_of_existing_is_not_duplicate(self):
        storage = KapStorage(clock=iso_clock)
        storage.insert(make_notification("N-1"))
        result = storage.insert(
            make_notification(
                "N-2", revision=RevisionStatus.REVISED, previous="N-1"
            )
        )
        assert result.status == REVISION_CHAIN
        assert storage.count() == 2

    def test_duplicate_event_logged(self):
        item = make_item("N-1")
        stack = build_stack([item], {"N-1": make_detail()})
        stack.collector.collect(CUTOFF)
        stack.collector.collect(CUTOFF)
        events = stack.collector.events_by_code(DUPLICATE_SKIPPED)
        assert len(events) == 1
        assert events[0]["notification_id"] == "N-1"


# ====================================================================== #
# Kategori 3 - Revizyon (14)
# ====================================================================== #
class TestRevizyon:
    def test_revision_marks_old_superseded(self):
        storage = KapStorage(clock=iso_clock)
        storage.insert(make_notification("N-1"))
        storage.insert(
            make_notification("N-2", revision=RevisionStatus.REVISED, previous="N-1")
        )
        storage.mark_superseded("N-1", "N-2")
        assert storage.get("N-1").revision_status == RevisionStatus.SUPERSEDED

    def test_old_record_not_overwritten(self):
        storage = KapStorage(clock=iso_clock)
        storage.insert(make_notification("N-1", body="orijinal govde"))
        storage.mark_superseded("N-1", "N-2")
        storage.insert(
            make_notification(
                "N-2", body="revize govde",
                revision=RevisionStatus.REVISED, previous="N-1",
            )
        )
        # eski kayit korunur: govde degismez, sadece durum isaretlenir
        old = storage.get("N-1")
        assert old.body == "orijinal govde"
        assert old.revision_status == RevisionStatus.SUPERSEDED

    def test_new_record_revised_with_previous_id(self):
        storage = KapStorage(clock=iso_clock)
        storage.insert(make_notification("N-1"))
        storage.insert(
            make_notification("N-2", revision=RevisionStatus.REVISED, previous="N-1")
        )
        new = storage.get("N-2")
        assert new.revision_status == RevisionStatus.REVISED
        assert new.previous_notification_id == "N-1"

    def test_insert_revision_returns_revision_chain(self):
        storage = KapStorage(clock=iso_clock)
        storage.insert(make_notification("N-1"))
        result = storage.insert(
            make_notification("N-2", revision=RevisionStatus.REVISED, previous="N-1")
        )
        assert result.status == REVISION_CHAIN
        assert result.previous_notification_id == "N-1"

    def test_history_order_old_to_new(self):
        storage = KapStorage(clock=iso_clock)
        storage.insert(make_notification("N-1"))
        storage.insert(
            make_notification("N-2", revision=RevisionStatus.REVISED, previous="N-1")
        )
        storage.mark_superseded("N-1", "N-2")
        history = storage.get_history("N-2")
        assert [n.notification_id for n in history] == ["N-1", "N-2"]

    def test_mark_superseded_sets_superseded_by(self):
        storage = KapStorage(clock=iso_clock)
        storage.insert(make_notification("N-1"))
        assert storage.mark_superseded("N-1", "N-2") is True
        assert storage.get_record("N-1").superseded_by == "N-2"

    def test_revisions_counter(self):
        items = [
            make_item("N-1"),
            make_item("N-2", revises="N-1", published="2024-06-30T07:10:00Z"),
        ]
        details = {"N-1": make_detail(), "N-2": make_detail("duzeltilmis")}
        stack = build_stack(items, details)
        result = stack.collector.collect(CUTOFF)
        assert result.revisions == 1
        assert result.cancellations == 0

    def test_three_version_chain(self):
        storage = KapStorage(clock=iso_clock)
        storage.insert(make_notification("N-1"))
        storage.insert(
            make_notification("N-2", revision=RevisionStatus.REVISED, previous="N-1")
        )
        storage.mark_superseded("N-1", "N-2")
        storage.insert(
            make_notification("N-3", revision=RevisionStatus.REVISED, previous="N-2")
        )
        storage.mark_superseded("N-2", "N-3")
        history = storage.get_history("N-3")
        assert [n.notification_id for n in history] == ["N-1", "N-2", "N-3"]
        assert storage.get("N-1").revision_status == RevisionStatus.SUPERSEDED
        assert storage.get("N-2").revision_status == RevisionStatus.SUPERSEDED
        assert storage.get("N-3").revision_status == RevisionStatus.REVISED

    def test_version_no_increments(self):
        storage = KapStorage(clock=iso_clock)
        first = storage.insert(make_notification("N-1"))
        second = storage.insert(
            make_notification("N-2", revision=RevisionStatus.REVISED, previous="N-1")
        )
        assert first.version_no == 1
        assert second.version_no == 2
        assert storage.get_record("N-2").version_no == 2

    def test_revision_and_original_in_same_run(self):
        items = [
            make_item("N-1"),
            make_item("N-2", revises="N-1", published="2024-06-30T07:10:00Z"),
        ]
        details = {"N-1": make_detail(), "N-2": make_detail("revize")}
        stack = build_stack(items, details)
        result = stack.collector.collect(CUTOFF)
        assert result.stored_count == 2
        assert stack.storage.get("N-1").revision_status == RevisionStatus.SUPERSEDED
        assert stack.storage.get("N-2").revision_status == RevisionStatus.REVISED
        assert [n.notification_id for n in stack.storage.get_history("N-2")] == [
            "N-1", "N-2",
        ]

    def test_revision_without_existing_original_stored(self):
        storage = KapStorage(clock=iso_clock)
        # eski kayit hic gelmemis: zincir yine de yazilir, hata olmaz
        result = storage.insert(
            make_notification("N-9", revision=RevisionStatus.REVISED, previous="N-X")
        )
        assert result.status == REVISION_CHAIN
        assert storage.mark_superseded("N-X", "N-9") is False
        assert storage.get("N-9").previous_notification_id == "N-X"

    def test_get_by_stock_contains_both_versions(self):
        storage = KapStorage(clock=iso_clock)
        storage.insert(make_notification("N-1"))
        storage.insert(
            make_notification("N-2", revision=RevisionStatus.REVISED, previous="N-1")
        )
        storage.mark_superseded("N-1", "N-2")
        rows = storage.get_by_stock(STOCK_ID)
        assert [n.notification_id for n in rows] == ["N-1", "N-2"]

    def test_old_id_still_retrievable(self):
        storage = KapStorage(clock=iso_clock)
        storage.insert(make_notification("N-1"))
        storage.mark_superseded("N-1", "N-2")
        assert storage.get("N-1") is not None

    def test_revision_chained_event_logged(self):
        items = [
            make_item("N-1"),
            make_item("N-2", revises="N-1", published="2024-06-30T07:10:00Z"),
        ]
        details = {"N-1": make_detail(), "N-2": make_detail()}
        stack = build_stack(items, details)
        stack.collector.collect(CUTOFF)
        events = stack.collector.events_by_code(REVISION_CHAINED)
        assert len(events) == 1
        assert events[0]["notification_id"] == "N-2"
        assert events[0]["previous"] == "N-1"


# ====================================================================== #
# Kategori 4 - Iptal (10)
# ====================================================================== #
class TestIptal:
    def test_cancelled_record_created(self):
        items = [
            make_item("N-1"),
            make_item("N-3", cancels="N-1", published="2024-06-30T07:20:00Z"),
        ]
        details = {"N-1": make_detail(), "N-3": make_detail("Iptal bildirimi")}
        stack = build_stack(items, details)
        stack.collector.collect(CUTOFF)
        cancel = stack.storage.get("N-3")
        assert cancel is not None
        assert cancel.revision_status == RevisionStatus.CANCELLED

    def test_cancel_previous_id_points_target(self):
        storage = KapStorage(clock=iso_clock)
        storage.insert(make_notification("N-1"))
        storage.insert(
            make_notification("N-3", revision=RevisionStatus.CANCELLED, previous="N-1")
        )
        assert storage.get("N-3").previous_notification_id == "N-1"

    def test_target_record_preserved(self):
        items = [
            make_item("N-1"),
            make_item("N-3", cancels="N-1", published="2024-06-30T07:20:00Z"),
        ]
        details = {"N-1": make_detail("hedef metin"), "N-3": make_detail("iptal")}
        stack = build_stack(items, details)
        stack.collector.collect(CUTOFF)
        target = stack.storage.get("N-1")
        # hedef kayit silinmez / degistirilmez
        assert target is not None
        assert target.body == "hedef metin"
        assert target.revision_status == RevisionStatus.ORIGINAL

    def test_cancellations_counter(self):
        items = [
            make_item("N-1"),
            make_item("N-3", cancels="N-1", published="2024-06-30T07:20:00Z"),
        ]
        details = {"N-1": make_detail(), "N-3": make_detail()}
        stack = build_stack(items, details)
        result = stack.collector.collect(CUTOFF)
        assert result.cancellations == 1
        assert result.revisions == 0

    def test_cancel_insert_returns_revision_chain(self):
        storage = KapStorage(clock=iso_clock)
        storage.insert(make_notification("N-1"))
        result = storage.insert(
            make_notification("N-3", revision=RevisionStatus.CANCELLED, previous="N-1")
        )
        assert result.status == REVISION_CHAIN

    def test_history_contains_target_and_cancel(self):
        storage = KapStorage(clock=iso_clock)
        storage.insert(make_notification("N-1"))
        storage.insert(
            make_notification("N-3", revision=RevisionStatus.CANCELLED, previous="N-1")
        )
        history = storage.get_history("N-3")
        ids = [n.notification_id for n in history]
        assert "N-1" in ids and "N-3" in ids
        assert ids[0] == "N-1"

    def test_cancel_does_not_supersede_target(self):
        storage = KapStorage(clock=iso_clock)
        storage.insert(make_notification("N-1"))
        storage.insert(
            make_notification("N-3", revision=RevisionStatus.CANCELLED, previous="N-1")
        )
        assert storage.get("N-1").revision_status == RevisionStatus.ORIGINAL
        assert storage.get_record("N-1").superseded_by is None

    def test_cancel_counted_as_stored(self):
        items = [
            make_item("N-1"),
            make_item("N-3", cancels="N-1", published="2024-06-30T07:20:00Z"),
        ]
        details = {"N-1": make_detail(), "N-3": make_detail()}
        stack = build_stack(items, details)
        result = stack.collector.collect(CUTOFF)
        assert result.stored_count == 2

    def test_cancel_of_unknown_target_stored(self):
        storage = KapStorage(clock=iso_clock)
        result = storage.insert(
            make_notification("N-3", revision=RevisionStatus.CANCELLED, previous="N-X")
        )
        assert result.status == REVISION_CHAIN
        assert storage.get("N-3") is not None

    def test_cancellation_event_logged(self):
        items = [
            make_item("N-1"),
            make_item("N-3", cancels="N-1", published="2024-06-30T07:20:00Z"),
        ]
        details = {"N-1": make_detail(), "N-3": make_detail()}
        stack = build_stack(items, details)
        stack.collector.collect(CUTOFF)
        events = stack.collector.events_by_code(CANCELLATION_RECORDED)
        assert len(events) == 1
        assert events[0]["notification_id"] == "N-3"
        assert events[0]["target"] == "N-1"


# ====================================================================== #
# Kategori 5 - Yanlis sirket eslesmesi (14)
# ====================================================================== #
class TestYanlisEslesme:
    def test_out_of_universe_not_stored(self):
        items = [make_item("N-1", symbol="DIS")]
        stack = build_stack(items, {"N-1": make_detail()},
                            mapping={"DIS": "STK-999999"}, universe=[STOCK_ID])
        result = stack.collector.collect(CUTOFF)
        assert result.matched_count == 0
        assert result.stored_count == 0
        assert stack.storage.count() == 0

    def test_out_of_universe_counter(self):
        matcher = KapMatcher(
            MockIdentityService({"DIS": "STK-999999"}), lambda: [STOCK_ID]
        )
        outcome = matcher.match(make_item("N-1", symbol="DIS"))
        assert outcome.status == OUT_OF_UNIVERSE
        assert matcher.out_of_universe_count == 1

    def test_ambiguous_real_blok6_pending_queue(self):
        service = SymbolIdentityService(clock=dt_clock)
        # Ayni isim + farkli ISIN: iki aday -> resolve None + pending kuyrugu
        sid1 = service.register_stock("Belirsiz Holding", isin="ISIN-1")
        sid2 = service.register_stock("Belirsiz Holding", isin="ISIN-2")
        matcher = KapMatcher(service, lambda: [sid1, sid2])
        outcome = matcher.match(
            {"notification_id": "N-1", "symbol": None,
             "company_name": "Belirsiz Holding"}
        )
        assert outcome.status == MATCH_AMBIGUOUS
        pending = service.get_pending_queue()
        assert len(pending) == 2
        assert {p.stock_id for p in pending} == {sid1, sid2}

    def test_matcher_pending_items_symbol_verification_pending(self):
        matcher = KapMatcher(
            MockIdentityService({}, ambiguous=["AMB"]), lambda: [STOCK_ID]
        )
        outcome = matcher.match(make_item("N-1", symbol="AMB"))
        assert outcome.status == MATCH_AMBIGUOUS
        assert outcome.code == SYMBOL_VERIFICATION_PENDING
        assert matcher.pending_items == [
            {
                "notification_id": "N-1",
                "query": "AMB",
                "reason": SYMBOL_VERIFICATION_PENDING,
            }
        ]

    def test_ambiguous_not_stored_not_bound(self):
        items = [make_item("N-1", symbol="AMB")]
        stack = build_stack(items, {"N-1": make_detail()}, ambiguous=["AMB"])
        result = stack.collector.collect(CUTOFF)
        assert result.matched_count == 0
        assert result.stored_count == 0
        assert stack.storage.count() == 0

    def test_unmatched_counter(self):
        matcher = KapMatcher(MockIdentityService({}), lambda: [STOCK_ID])
        matcher.match(make_item("N-1", symbol="YOK"))
        matcher.match(make_item("N-2", symbol="YOK2"))
        assert matcher.unmatched_count == 2

    def test_unmatched_silently_not_bound(self):
        items = [make_item("N-1", symbol="YOK")]
        stack = build_stack(items, {"N-1": make_detail()})
        result = stack.collector.collect(CUTOFF)
        assert stack.matcher.counters[UNMATCHED] == 1
        assert result.stored_count == 0
        # sessizce hicbir hisseye baglanmaz
        assert stack.storage.get_by_stock(STOCK_ID) == []

    def test_company_name_match_real_blok6(self):
        service = SymbolIdentityService(clock=dt_clock)
        sid = service.register_stock("Acme Enerji")
        service.add_symbol(sid, "kap", "ACME")
        matcher = KapMatcher(service, lambda: [sid])
        outcome = matcher.match(
            {"notification_id": "N-1", "symbol": "ACME", "company_name": "Acme Enerji"}
        )
        assert outcome.status == MATCHED
        assert outcome.stock_id == sid

    def test_matched_count_excludes_non_matches(self):
        items = [
            make_item("N-1"),                          # eslesir
            make_item("N-2", symbol="YOK"),            # unmatched
            make_item("N-3", symbol="DIS"),            # evren disi
            make_item("N-4", symbol="AMB"),            # belirsiz
        ]
        stack = build_stack(
            items,
            {"N-1": make_detail()},
            mapping={SYMBOL: STOCK_ID, "DIS": "STK-999999"},
            universe=[STOCK_ID],
            ambiguous=["AMB"],
        )
        result = stack.collector.collect(CUTOFF)
        assert result.matched_count == 1
        assert result.stored_count == 1

    def test_matcher_uses_injected_resolve_with_kap_platform(self):
        identity = MockIdentityService({SYMBOL: STOCK_ID})
        matcher = KapMatcher(identity, lambda: [STOCK_ID])
        matcher.match(make_item("N-1"))
        assert identity.resolve_calls == [(SYMBOL, "kap")]

    def test_ambiguous_does_not_attach_to_similar_stock(self):
        # "THYAO" mevcut; belirsiz "THY" gelirse THYAO'ya BAGLANMAZ
        items = [make_item("N-1", symbol="THY")]
        stack = build_stack(
            items, {"N-1": make_detail()},
            mapping={SYMBOL: STOCK_ID}, ambiguous=["THY"],
        )
        stack.collector.collect(CUTOFF)
        assert stack.storage.get_by_stock(STOCK_ID) == []

    def test_empty_universe_marks_all_out_of_universe(self):
        matcher = KapMatcher(
            MockIdentityService({SYMBOL: STOCK_ID}), lambda: []
        )
        outcome = matcher.match(make_item("N-1"))
        assert outcome.status == OUT_OF_UNIVERSE

    def test_outcome_recorded_per_item(self):
        matcher = KapMatcher(
            MockIdentityService({SYMBOL: STOCK_ID}), lambda: [STOCK_ID]
        )
        matcher.match(make_item("N-1"))
        matcher.match(make_item("N-2", symbol="YOK"))
        assert [o.status for o in matcher.outcomes] == [MATCHED, UNMATCHED]
        assert matcher.outcomes[0].notification_id == "N-1"
        assert matcher.outcomes[1].notification_id == "N-2"

    def test_resolved_stock_id_bound_into_notification(self):
        item = make_item("N-1")
        stack = build_stack([item], {"N-1": make_detail()})
        stack.collector.collect(CUTOFF)
        stored = stack.storage.get("N-1")
        assert stored.stock_id == STOCK_ID
        assert stack.storage.get_by_stock(STOCK_ID)[0].notification_id == "N-1"


# ====================================================================== #
# Kategori 6 - KAP kesintisi (12)
# ====================================================================== #
class FlakyMatcher:
    """Belirli bildirimde hata firlatip digerlerini geciren matcher sarmalayici."""

    def __init__(self, inner, fail_on):
        self.inner = inner
        self.fail_on = fail_on
        self.counters = inner.counters

    def match(self, item):
        if item.get("notification_id") == self.fail_on:
            raise RuntimeError("beklenmeyen islem hatasi")
        return self.inner.match(item)

    def _universe_ids(self):
        return self.inner._universe_ids()


class TestKapKesintisi:
    def test_feed_outage_returns_failed_no_exception(self):
        fetcher = MockKapFetcher(feed_exc=ConnectionError("kap kapali"))
        feed = KapFeed(fetcher, clock=iso_clock)
        matcher = KapMatcher(MockIdentityService({SYMBOL: STOCK_ID}), lambda: [STOCK_ID])
        storage = KapStorage(clock=iso_clock)
        collector = KapCollector(feed, matcher, storage, clock=iso_clock)
        # exception FIRLATILMAZ; sonuc nesnesi doner
        result = collector.collect(CUTOFF)
        assert result.status == KapRunStatus.FAILED

    def test_outage_kap_health_down(self):
        stack = build_stack(fetcher_exc=TimeoutError("zaman asimi"))
        result = stack.collector.collect(CUTOFF)
        assert result.kap_health == KapHealth.DOWN

    def test_outage_errors_contain_feed_unavailable(self):
        stack = build_stack(fetcher_exc=ConnectionError("kopuk"))
        result = stack.collector.collect(CUTOFF)
        assert any(FEED_UNAVAILABLE in e for e in result.errors)

    def test_outage_does_not_stop_following_work(self):
        stack = build_stack(fetcher_exc=ConnectionError("kapali"))
        first = stack.collector.collect(CUTOFF)
        assert first.status == KapRunStatus.FAILED
        # KAP kesintisi baska isleri durdurmaz: sonraki calisma normal doner
        stack.fetcher.feed_exc = None
        stack.fetcher.feed_items = [make_item("N-1")]
        stack.fetcher.details = {"N-1": make_detail()}
        second = stack.collector.collect(CUTOFF)
        assert second.status == KapRunStatus.COMPLETED
        assert second.stored_count == 1

    def test_detail_outage_mid_run_partial(self):
        items = [make_item("N-1"), make_item("N-2")]
        fetcher = MockKapFetcher(items, detail_exc=ConnectionError("detay yok"))
        feed = KapFeed(fetcher, clock=iso_clock)
        matcher = KapMatcher(MockIdentityService({SYMBOL: STOCK_ID}), lambda: [STOCK_ID])
        storage = KapStorage(clock=iso_clock)
        collector = KapCollector(feed, matcher, storage, clock=iso_clock)
        result = collector.collect(CUTOFF)
        assert result.status == KapRunStatus.PARTIAL
        assert result.kap_health == KapHealth.DOWN

    def test_partial_run_recorded_in_storage(self):
        items = [make_item("N-1")]
        fetcher = MockKapFetcher(items, detail_exc=ConnectionError("detay yok"))
        feed = KapFeed(fetcher, clock=iso_clock)
        matcher = KapMatcher(MockIdentityService({SYMBOL: STOCK_ID}), lambda: [STOCK_ID])
        storage = KapStorage(clock=iso_clock)
        collector = KapCollector(feed, matcher, storage, clock=iso_clock)
        collector.collect(CUTOFF)
        assert storage.last_run_status() == KapRunStatus.PARTIAL.value

    def test_fetcher_none_feed_failed(self):
        feed = KapFeed(None, clock=iso_clock)
        matcher = KapMatcher(MockIdentityService({SYMBOL: STOCK_ID}), lambda: [STOCK_ID])
        storage = KapStorage(clock=iso_clock)
        collector = KapCollector(feed, matcher, storage, clock=iso_clock)
        result = collector.collect(CUTOFF)
        assert result.status == KapRunStatus.FAILED
        assert any(FEED_UNAVAILABLE in e for e in result.errors)

    def test_outage_result_zero_counts_with_run_id(self):
        stack = build_stack(fetcher_exc=ConnectionError("kapali"))
        result = stack.collector.collect(CUTOFF)
        assert result.fetched_count == 0
        assert result.stored_count == 0
        assert result.run_id.startswith("KAPRUN-")

    def test_feed_unavailable_event_logged(self):
        stack = build_stack(fetcher_exc=ConnectionError("kapali"))
        stack.collector.collect(CUTOFF)
        events = stack.collector.events_by_code(FEED_UNAVAILABLE)
        assert len(events) == 1
        assert events[0]["step"] == 1

    def test_recovery_after_outage(self):
        stack = build_stack(fetcher_exc=ConnectionError("kapali"))
        failed = stack.collector.collect(CUTOFF)
        assert failed.kap_health == KapHealth.DOWN
        stack.fetcher.feed_exc = None
        stack.fetcher.feed_items = [make_item("N-1")]
        stack.fetcher.details = {"N-1": make_detail()}
        recovered = stack.collector.collect(CUTOFF)
        assert recovered.status == KapRunStatus.COMPLETED
        assert recovered.kap_health == KapHealth.OK

    def test_detail_outage_stores_body_none_with_detail_missing(self):
        items = [make_item("N-1", ntype="FR"), make_item("N-2")]
        fetcher = MockKapFetcher(items, detail_exc=ConnectionError("detay yok"))
        feed = KapFeed(fetcher, clock=iso_clock)
        matcher = KapMatcher(MockIdentityService({SYMBOL: STOCK_ID}), lambda: [STOCK_ID])
        storage = KapStorage(clock=iso_clock)
        collector = KapCollector(feed, matcher, storage, clock=iso_clock)
        result = collector.collect(CUTOFF)
        # bildirimler yine de kaydedilir, body=None + DETAIL_MISSING
        assert result.stored_count == 2
        assert storage.get("N-1").body is None
        events = collector.events_by_code(DETAIL_MISSING)
        assert {e["notification_id"] for e in events} == {"N-1", "N-2"}
        critical = [e for e in events if e["notification_id"] == "N-1"]
        assert critical[0]["critical"] is True

    def test_single_item_error_partial_others_stored(self):
        items = [make_item("N-1"), make_item("N-2")]
        details = {"N-1": make_detail(), "N-2": make_detail()}
        stack = build_stack(items, details)
        flaky = FlakyMatcher(stack.matcher, fail_on="N-2")
        collector = KapCollector(
            stack.feed, flaky, stack.storage, clock=iso_clock
        )
        result = collector.collect(CUTOFF)
        assert result.status == KapRunStatus.PARTIAL
        assert result.kap_health == KapHealth.DEGRADED
        assert result.stored_count == 1
        assert stack.storage.get("N-1") is not None
        assert any("ITEM_PROCESSING_ERROR" in e for e in result.errors)


# ====================================================================== #
# Kategori 7 - Ek dosya (10)
# ====================================================================== #
class TestEkDosya:
    def test_attachment_meta_recorded(self):
        detail = make_detail(attachments=[
            {"url": "https://kap.example.tr/ek/a.pdf", "file_name": "a.pdf",
             "file_type": "pdf", "size_bytes": 2048},
        ])
        stack = build_stack([make_item("N-1")], {"N-1": detail})
        stack.collector.collect(CUTOFF)
        record = stack.storage.get_record("N-1")
        assert len(record.attachments) == 1
        meta = record.attachments[0]
        assert isinstance(meta, AttachmentMeta)
        assert meta.url == "https://kap.example.tr/ek/a.pdf"
        assert meta.file_name == "a.pdf"
        assert meta.file_type == "pdf"
        assert meta.size_bytes == 2048

    def test_attachment_never_downloaded_flags(self):
        detail = make_detail(attachments=[{"url": "https://kap.example.tr/ek/a.pdf"}])
        stack = build_stack([make_item("N-1")], {"N-1": detail})
        stack.collector.collect(CUTOFF)
        meta = stack.storage.get_record("N-1").attachments[0]
        # dosya INDIRILMEZ: sadece meta
        assert meta.fetched is False
        assert meta.fetched_at is None

    def test_multiple_attachments(self):
        detail = make_detail(attachments=[
            {"url": "https://kap.example.tr/ek/a.pdf", "file_name": "a.pdf"},
            {"url": "https://kap.example.tr/ek/b.xlsx", "file_name": "b.xlsx"},
            {"url": "https://kap.example.tr/ek/c.jpg", "file_name": "c.jpg"},
        ])
        stack = build_stack([make_item("N-1")], {"N-1": detail})
        stack.collector.collect(CUTOFF)
        record = stack.storage.get_record("N-1")
        assert len(record.attachments) == 3
        assert {a.file_name for a in record.attachments} == {"a.pdf", "b.xlsx", "c.jpg"}

    def test_notification_attachment_urls(self):
        detail = make_detail(attachments=[
            {"url": "https://kap.example.tr/ek/a.pdf"},
            {"url": "https://kap.example.tr/ek/b.pdf"},
        ])
        stack = build_stack([make_item("N-1")], {"N-1": detail})
        stack.collector.collect(CUTOFF)
        stored = stack.storage.get("N-1")
        assert stored.attachment_urls == [
            "https://kap.example.tr/ek/a.pdf",
            "https://kap.example.tr/ek/b.pdf",
        ]

    def test_no_attachments_empty(self):
        stack = build_stack([make_item("N-1")], {"N-1": make_detail()})
        stack.collector.collect(CUTOFF)
        record = stack.storage.get_record("N-1")
        assert record.attachments == []
        assert stack.storage.get("N-1").attachment_urls == []

    def test_item_level_attachment_urls_passthrough(self):
        item = make_item("N-1", attachment_urls=["https://kap.example.tr/ek/x.pdf"])
        stack = build_stack([item], {"N-1": make_detail()})
        stack.collector.collect(CUTOFF)
        assert stack.storage.get("N-1").attachment_urls == ["https://kap.example.tr/ek/x.pdf"]

    def test_attachment_missing_size_allowed(self):
        detail = make_detail(attachments=[{"url": "https://kap.example.tr/ek/a.pdf"}])
        stack = build_stack([make_item("N-1")], {"N-1": detail})
        stack.collector.collect(CUTOFF)
        meta = stack.storage.get_record("N-1").attachments[0]
        assert meta.size_bytes is None
        assert meta.file_type is None

    def test_no_download_calls_on_fetcher(self):
        detail = make_detail(attachments=[
            {"url": "https://kap.example.tr/ek/a.pdf"},
            {"url": "https://kap.example.tr/ek/b.pdf"},
        ])
        stack = build_stack([make_item("N-1")], {"N-1": detail})
        stack.collector.collect(CUTOFF)
        # ek URL'leri icin ayrica cekim yapilmadi
        assert stack.fetcher.detail_calls == ["N-1"]
        assert stack.fetcher.feed_calls == [CUTOFF]

    def test_step4_event_count(self):
        detail = make_detail(attachments=[
            {"url": "https://kap.example.tr/ek/a.pdf"},
            {"url": "https://kap.example.tr/ek/b.pdf"},
        ])
        stack = build_stack([make_item("N-1")], {"N-1": detail})
        stack.collector.collect(CUTOFF)
        events = stack.collector.events_by_code(STEP4_ATTACHMENTS)
        assert len(events) == 1
        assert events[0]["count"] == 2

    def test_attachments_survive_sqlite_roundtrip(self):
        conn = sqlite3.connect(":memory:")
        storage = KapStorage(conn=conn, clock=iso_clock)
        storage.insert(
            make_notification("N-1"),
            [AttachmentMeta(url="https://kap.example.tr/ek/a.pdf",
                            file_name="a.pdf", file_type="pdf", size_bytes=99)],
        )
        record = storage.get_record("N-1")
        assert len(record.attachments) == 1
        meta = record.attachments[0]
        assert (meta.url, meta.file_name, meta.file_type, meta.size_bytes) == (
            "https://kap.example.tr/ek/a.pdf", "a.pdf", "pdf", 99,
        )
        assert meta.fetched is False


# ====================================================================== #
# Kategori 8 - Profil haftalik + favori hazirlik kilidi + kapsam kilidi (12)
# ====================================================================== #
class TestProfilFavoriVeKilit:
    def test_profile_fresh_skip(self):
        fetcher = MockProfileFetcher()
        checker = ProfileChecker(fetcher, clock=dt_clock)
        checker.mark_checked("S1", FIXED_DT - timedelta(days=2))
        summary = checker.check(["S1"])
        assert summary["skipped_fresh"] == ["S1"]
        assert summary["checked"] == []
        assert fetcher.calls == []
        assert checker.events[-1]["event"] == PROFILES_SKIPPED_FRESH

    def test_profile_stale_checked(self):
        fetcher = MockProfileFetcher()
        checker = ProfileChecker(fetcher, clock=dt_clock)
        checker.mark_checked("S1", FIXED_DT - timedelta(days=8))
        summary = checker.check(["S1"])
        assert summary["checked"] == ["S1"]
        assert fetcher.calls == ["S1"]
        assert checker.events[-1]["event"] == PROFILES_CHECKED

    def test_profile_exactly_7_days_checked(self):
        fetcher = MockProfileFetcher()
        checker = ProfileChecker(fetcher, clock=dt_clock)
        checker.mark_checked("S1", FIXED_DT - timedelta(days=7))
        # 7 gunluk pencere dolmus: taze DEGIL -> cekilir
        summary = checker.check(["S1"])
        assert summary["checked"] == ["S1"]

    def test_profile_check_summary(self):
        fetcher = MockProfileFetcher()
        checker = ProfileChecker(fetcher, clock=dt_clock)
        checker.mark_checked("S1", FIXED_DT - timedelta(days=1))
        summary = checker.check(["S1", "S2"])
        assert summary == {
            "checked": ["S2"],
            "skipped_fresh": ["S1"],
            "skipped_no_fetcher": [],
            "failed": [],
        }

    def test_readiness_ready_when_critical_body_present(self):
        storage = KapStorage(clock=iso_clock)
        storage.insert(make_notification("N-1", ntype="FR", body="rapor metni"))
        verdict = FavoriteReadiness(storage).is_ready_for_favorite(STOCK_ID)
        assert verdict.ready is True
        assert verdict.blocking == []

    def test_readiness_blocked_when_critical_body_missing(self):
        storage = KapStorage(clock=iso_clock)
        storage.insert(make_notification("N-1", ntype="FR", body=None))
        verdict = FavoriteReadiness(storage).is_ready_for_favorite(STOCK_ID)
        assert verdict.ready is False
        assert CRITICAL_BODY_MISSING in verdict.blocking
        assert FAVORI_READY_BLOCKED in verdict.blocking

    def test_readiness_non_critical_body_missing_ok(self):
        storage = KapStorage(clock=iso_clock)
        storage.insert(make_notification("N-1", ntype="DG", body=None))
        verdict = FavoriteReadiness(storage).is_ready_for_favorite(STOCK_ID)
        assert verdict.ready is True

    def test_partial_run_with_critical_blocks(self):
        storage = KapStorage(clock=iso_clock)
        storage.insert(make_notification("N-1", ntype="ODA", body="metin"))
        storage.record_run(KapRunStatus.PARTIAL)
        verdict = FavoriteReadiness(storage).is_ready_for_favorite(STOCK_ID)
        assert verdict.ready is False
        assert KAP_PARTIAL_BLOCK in verdict.blocking

    def test_completed_run_no_partial_block(self):
        storage = KapStorage(clock=iso_clock)
        storage.insert(make_notification("N-1", ntype="ODA", body="metin"))
        storage.record_run(KapRunStatus.COMPLETED)
        verdict = FavoriteReadiness(storage).is_ready_for_favorite(STOCK_ID)
        assert verdict.ready is True
        assert KAP_PARTIAL_BLOCK not in verdict.blocking

    def test_superseded_old_body_missing_does_not_block(self):
        storage = KapStorage(clock=iso_clock)
        storage.insert(make_notification("N-1", ntype="FR", body=None))
        storage.mark_superseded("N-1", "N-2")
        storage.insert(
            make_notification("N-2", ntype="FR", body="revize tam metin",
                              revision=RevisionStatus.REVISED, previous="N-1")
        )
        verdict = FavoriteReadiness(storage).is_ready_for_favorite(STOCK_ID)
        assert verdict.ready is True

    def test_no_score_sentiment_fields_on_models(self):
        forbidden = ("sentiment", "score", "puan")
        for model in (KapNotification, KapCollectionResult, AttachmentMeta):
            for f in dataclasses.fields(model):
                low = f.name.lower()
                assert not any(bad in low for bad in forbidden), (
                    f"{model.__name__}.{f.name} kapsam kilidini ihlal ediyor"
                )
        for enum in (RevisionStatus, KapRunStatus, KapHealth):
            for member in enum:
                low = member.name.lower()
                assert not any(bad in low for bad in forbidden)

    def test_no_scoring_identifiers_in_package(self):
        forbidden = ("sentiment", "score", "puan")
        pkg_dir = os.path.join(
            os.path.dirname(__file__), os.pardir, os.pardir,
            "app", "services", "stock_scanning", "kap_collection",
        )
        scanned = 0
        for name in os.listdir(pkg_dir):
            if not name.endswith(".py"):
                continue
            scanned += 1
            with open(os.path.join(pkg_dir, name), "r", encoding="utf-8") as fh:
                src = fh.read().lower()
            for bad in forbidden:
                assert bad not in src, f"{name} icinde yasakli ifade: {bad}"
        assert scanned == 7  # paketin tum modulleri tarandi (__init__ dahil)
        # readiness sadece hazirlik bildirir; secim yapan metot yok
        assert hasattr(FavoriteReadiness, "is_ready_for_favorite")
        assert not any(
            any(bad in attr.lower() for bad in forbidden + ("select", "rank"))
            for attr in dir(FavoriteReadiness)
        )
        assert not any(
            any(bad in attr.lower() for bad in forbidden)
            for attr in dir(KapCollector)
        )
