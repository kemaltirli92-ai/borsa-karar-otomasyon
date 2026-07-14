"""BLOK 11 - KapCollector: 6 adimli KAP bildirim toplama zinciri (collector.py).

collect(cutoff_iso) adimlari (SPEC bolum 6):
  1) fetch_since(cutoff) — merkezi akis (TEK cagri; profil linkleri acilmaz)
  2) matcher ile aktif XK100 eslestirme
  3) eslesen bildirimin detayini ac (fetch_detail, calisma ici tek kez)
  4) ek dosya META bilgisini kaydet (AttachmentMeta; dosya INDIRILMEZ)
  5) revizyon/iptal kontrolu: REVISED/CANCELLED zinciri
  6) stock_id ile bagla + storage'a yaz

Kurallar:
- Dedupe: ayni notification_id ikinci kez EKLENMEZ (skipped_duplicates++).
- Revizyon: eski kaydin UZERINE YAZILMAZ — eski SUPERSEDED, yeni REVISED +
  previous_notification_id.
- Iptal: CANCELLED kaydi olusur, hedef kayit korunur.
- KAP KESINTISI: feed hatasi -> PARTIAL (hic veri yoksa FAILED),
  kap_health=DOWN; exception DISARI FIRLATILMAZ (fiyat taramasi durmaz).
- Detay cekilemeyen bildirim: body=None + DETAIL_MISSING isareti.
- KAPSAM KILIDI: bu modulde bildirim etki/yon HESAPLAMASI YOKTUR.

Deterministik: clock enjekte (ISO str). Gercek ag YOK.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable, List, Optional

from .feed import KapFeedUnavailableError
from .matcher import MATCHED
from .models import (
    AttachmentMeta,
    KapCollectionResult,
    KapHealth,
    KapNotification,
    KapRunStatus,
    RevisionStatus,
)
from .storage import DUPLICATE

# Olay kodlari
STEP1_FEED_FETCHED = "STEP1_FEED_FETCHED"
STEP2_MATCHED = "STEP2_MATCHED"
STEP3_DETAIL_FETCHED = "STEP3_DETAIL_FETCHED"
STEP4_ATTACHMENTS = "STEP4_ATTACHMENTS"
STEP5_REVISION = "STEP5_REVISION"
STEP6_STORED = "STEP6_STORED"

DETAIL_MISSING = "DETAIL_MISSING"
DUPLICATE_SKIPPED = "DUPLICATE_SKIPPED"
REVISION_CHAINED = "REVISION_CHAINED"
CANCELLATION_RECORDED = "CANCELLATION_RECORDED"
FEED_UNAVAILABLE = "FEED_UNAVAILABLE"
ITEM_PROCESSING_ERROR = "ITEM_PROCESSING_ERROR"

# Kritik bildirim tipleri (readiness ile ortak tanim)
CRITICAL_TYPES = frozenset({"FR", "ODA", "MSL"})


def _utcnow_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


class KapCollector:
    """Merkezi KAP akisindan XK100 bildirimlerini toplayan zincir."""

    def __init__(
        self,
        feed,
        matcher,
        storage,
        profile_checker=None,
        logger=None,
        clock: Optional[Callable[[], str]] = None,
    ):
        self.feed = feed
        self.matcher = matcher
        self.storage = storage
        self.profile_checker = profile_checker
        self._logger = logger
        self._clock: Callable[[], str] = clock or _utcnow_iso
        self.events: List[dict] = []
        self._run_counter = 0
        self.last_result: Optional[KapCollectionResult] = None

    # ------------------------------------------------------------------ #
    # Yardimcilar
    # ------------------------------------------------------------------ #
    def _now_iso(self) -> str:
        return str(self._clock())

    def _next_run_id(self) -> str:
        self._run_counter += 1
        stamp = "".join(ch for ch in self._now_iso() if ch.isalnum())
        return f"KAPRUN-{stamp}-{self._run_counter:04d}"

    def _log(self, code: str, **fields) -> None:
        event = {"event": code}
        event.update(fields)
        self.events.append(event)
        lg = self._logger
        if lg is None:
            return
        if callable(lg):
            lg(code, dict(fields))
        elif hasattr(lg, "info"):
            lg.info("%s | %s", code, fields)

    def events_by_code(self, code: str) -> List[dict]:
        return [e for e in self.events if e["event"] == code]

    # ------------------------------------------------------------------ #
    # Ana akis
    # ------------------------------------------------------------------ #
    def collect(self, cutoff_iso: str) -> KapCollectionResult:
        """6 adimli toplama. Hicbir durumda exception disari SIZMAZ."""
        run_id = self._next_run_id()
        errors: List[str] = []
        kap_health = KapHealth.OK
        outage = False

        # Calisma-ici detay onbellegini sifirla
        begin_run = getattr(self.feed, "begin_run", None)
        if callable(begin_run):
            begin_run()

        # Haftalik profil kontrolu (opsiyonel; toplamayi durdurmaz)
        if self.profile_checker is not None:
            try:
                self.profile_checker.check(self._universe_stock_ids())
            except Exception as exc:
                errors.append(f"PROFILE_CHECK_ERROR:{exc}")

        # ---- Adim 1: merkezi akis ------------------------------------
        try:
            items = self.feed.fetch_since(cutoff_iso)
        except KapFeedUnavailableError as exc:
            self._log(FEED_UNAVAILABLE, step=1, error=str(exc))
            errors.append(f"{FEED_UNAVAILABLE}:{exc}")
            result = KapCollectionResult(
                run_id=run_id,
                status=KapRunStatus.FAILED,
                errors=errors,
                kap_health=KapHealth.DOWN,
            )
            self._finish(result)
            return result
        except Exception as exc:  # beklenmeyen kaynak hatasi da sizmaz
            self._log(FEED_UNAVAILABLE, step=1, error=str(exc))
            errors.append(f"{FEED_UNAVAILABLE}:{exc}")
            result = KapCollectionResult(
                run_id=run_id,
                status=KapRunStatus.FAILED,
                errors=errors,
                kap_health=KapHealth.DOWN,
            )
            self._finish(result)
            return result

        self._log(STEP1_FEED_FETCHED, count=len(items))
        fetched_count = len(items)
        matched_count = 0
        stored_count = 0
        skipped_duplicates = 0
        revisions = 0
        cancellations = 0

        for item in items:
            nid = item.get("notification_id")
            try:
                # ---- Adim 2: eslestirme ------------------------------
                outcome = self.matcher.match(item)
                if outcome.status != MATCHED:
                    continue
                matched_count += 1
                self._log(
                    STEP2_MATCHED,
                    notification_id=nid,
                    stock_id=outcome.stock_id,
                )

                # ---- Adim 3: detay (calisma ici tek kez) --------------
                detail = None
                try:
                    detail = self.feed.fetch_detail(nid)
                except KapFeedUnavailableError as exc:
                    outage = True
                    kap_health = KapHealth.DOWN
                    errors.append(f"{FEED_UNAVAILABLE}:{nid}:{exc}")
                    self._log(FEED_UNAVAILABLE, step=3, notification_id=nid)
                except Exception as exc:
                    errors.append(f"{ITEM_PROCESSING_ERROR}:{nid}:{exc}")
                    self._log(
                        ITEM_PROCESSING_ERROR, step=3, notification_id=nid
                    )
                self._log(
                    STEP3_DETAIL_FETCHED,
                    notification_id=nid,
                    has_detail=detail is not None,
                )

                merged = self._merge(item, detail)

                # ---- Adim 4: ek dosya META (indirme YOK) --------------
                attachments = self._build_attachments(merged)
                self._log(
                    STEP4_ATTACHMENTS,
                    notification_id=nid,
                    count=len(attachments),
                )

                # ---- Adim 5: revizyon / iptal --------------------------
                notification = self._build_notification(merged, outcome, attachments)
                if notification.revision_status == RevisionStatus.REVISED:
                    prev = notification.previous_notification_id
                    if prev:
                        self.storage.mark_superseded(prev, nid)
                    revisions += 1
                    self._log(
                        REVISION_CHAINED, notification_id=nid, previous=prev
                    )
                elif notification.revision_status == RevisionStatus.CANCELLED:
                    cancellations += 1
                    self._log(
                        CANCELLATION_RECORDED,
                        notification_id=nid,
                        target=notification.previous_notification_id,
                    )
                self._log(
                    STEP5_REVISION,
                    notification_id=nid,
                    revision_status=notification.revision_status.value,
                )

                if notification.body is None:
                    self._log(
                        DETAIL_MISSING,
                        notification_id=nid,
                        critical=notification.notification_type in CRITICAL_TYPES,
                    )

                # ---- Adim 6: stock_id bagla + yaz -----------------------
                stored = self.storage.insert(notification, attachments)
                if stored.status == DUPLICATE:
                    skipped_duplicates += 1
                    self._log(DUPLICATE_SKIPPED, notification_id=nid)
                else:
                    stored_count += 1
                    self._log(
                        STEP6_STORED,
                        notification_id=nid,
                        status=stored.status,
                    )
            except Exception as exc:  # tek kayit hatasi zinciri durdurmaz
                errors.append(f"{ITEM_PROCESSING_ERROR}:{nid}:{exc}")
                self._log(ITEM_PROCESSING_ERROR, notification_id=nid, error=str(exc))

        # ---- Durum / saglik ozeti -------------------------------------
        if outage:
            status = KapRunStatus.PARTIAL if stored_count > 0 or matched_count > 0 else KapRunStatus.FAILED
            kap_health = KapHealth.DOWN
        elif errors:
            status = KapRunStatus.PARTIAL
            kap_health = KapHealth.DEGRADED
        else:
            status = KapRunStatus.COMPLETED
            kap_health = KapHealth.OK

        result = KapCollectionResult(
            run_id=run_id,
            status=status,
            fetched_count=fetched_count,
            matched_count=matched_count,
            stored_count=stored_count,
            skipped_duplicates=skipped_duplicates,
            revisions=revisions,
            cancellations=cancellations,
            errors=errors,
            kap_health=kap_health,
        )
        self._finish(result)
        return result

    def _finish(self, result: KapCollectionResult) -> None:
        """Sonucu kaydet: son calisma durumu readiness icin izlenir."""
        self.last_result = result
        record_run = getattr(self.storage, "record_run", None)
        if callable(record_run):
            record_run(result.status)

    def _universe_stock_ids(self) -> List[str]:
        """Profil haftalik kontrolu icin evren stock_id listesi."""
        getter = getattr(self.matcher, "_universe_ids", None)
        if callable(getter):
            try:
                return sorted(getter())
            except Exception:
                return []
        return []

    # ------------------------------------------------------------------ #
    # Kayit insasi
    # ------------------------------------------------------------------ #
    @staticmethod
    def _merge(item: dict, detail: Optional[dict]) -> dict:
        """Akis kaydi + detay birlesimi (detay anahtarlari onceliklidir)."""
        merged = dict(item)
        if detail:
            for key, value in detail.items():
                merged[key] = value
        return merged

    @staticmethod
    def _build_attachments(merged: dict) -> List[AttachmentMeta]:
        """Ek dosya META listesi. Dosya INDIRILMEZ: fetched=False."""
        raw = merged.get("attachments") or []
        metas: List[AttachmentMeta] = []
        for att in raw:
            if isinstance(att, str):
                metas.append(AttachmentMeta(url=att))
                continue
            metas.append(
                AttachmentMeta(
                    url=att.get("url", ""),
                    file_name=att.get("file_name"),
                    file_type=att.get("file_type"),
                    size_bytes=att.get("size_bytes"),
                    fetched=False,
                    fetched_at=None,
                )
            )
        return metas

    def _build_notification(
        self,
        merged: dict,
        outcome,
        attachments: List[AttachmentMeta],
    ) -> KapNotification:
        """KapNotification (17 alan) insasi; revizyon/iptal alanlari dahil."""
        revises = merged.get("revises")
        cancels = merged.get("cancels")
        if cancels:
            revision_status = RevisionStatus.CANCELLED
            previous = cancels
        elif revises:
            revision_status = RevisionStatus.REVISED
            previous = revises
        else:
            revision_status = RevisionStatus.ORIGINAL
            previous = merged.get("previous_notification_id")

        amount = merged.get("amount")
        if amount is not None:
            amount = float(amount)

        attachment_urls = list(merged.get("attachment_urls") or [])
        for meta in attachments:
            if meta.url and meta.url not in attachment_urls:
                attachment_urls.append(meta.url)

        return KapNotification(
            notification_id=str(merged.get("notification_id")),
            stock_id=outcome.stock_id,
            symbol=merged.get("symbol") or outcome.symbol,
            title=merged.get("title") or "",
            notification_type=merged.get("notification_type") or "DG",
            subtype=merged.get("subtype"),
            published_at=merged.get("published_at") or "",
            source_timestamp=merged.get("source_timestamp"),
            body=merged.get("body"),
            summary_raw=merged.get("summary_raw"),
            amount=amount,
            currency=merged.get("currency"),
            official_url=merged.get("official_url"),
            attachment_urls=attachment_urls,
            revision_status=revision_status,
            previous_notification_id=previous,
            collected_at=self._now_iso(),
        )
