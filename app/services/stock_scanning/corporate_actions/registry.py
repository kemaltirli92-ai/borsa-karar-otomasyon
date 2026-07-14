"""BLOK 13 - Kurumsal islem kayit defteri (registry.py).

CorporateActionRegistry:
- register(record, kap_notice_no=None) -> RegistryResult
  * DEDUPE: ayni (stock_id, action_type, effective_date, kap_notice_no)
    ikinci kez EKLENMEZ (duplicate++).
  * SURUM ZINCIRI: ayni olay (stock_id, action_type, effective_date) icin
    duzeltilmis kayit (farkli kap_notice_no) -> eski kayit SUPERSEDED,
    yeni kayit yeni data_version ile (action-v1, action-v2, ...);
    eski surum SILINMEZ, get_history ile okunur.
  * CANCELLED: iptal AYRI kayit olarak tutulur; hedef kayit korunur
    (silinmez, status'u degismez).
- DURUM GECIS KONTROLU: ANNOUNCED -> EFFECTIVE -> COMPLETED; gecersiz
  gecisler reddedilir (or. COMPLETED -> ANNOUNCED yok).
- SYMBOL_CHANGE: BLOK 6 sembol gecmisiyle uyumlu not — eski kod silinmez
  ilkesine atif; baglanti (symbol_history) enjekte edilir, DEGISTIRILMEZ.
- get_actions(stock_id, status=None), get_history(stock_id, action_key).

Deterministik: clock enjekte edilebilir; gercek ag YOK.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

from app.services.stock_scanning.corporate_actions.models import (
    ActionStatus,
    ActionType,
    CorporateActionRecord,
)

# RegistryResult.outcome degerleri (SPEC bolum 4)
OUTCOME_STORED = "stored"
OUTCOME_DUPLICATE = "duplicate"
OUTCOME_REVISION = "revision_chain"
OUTCOME_CANCELLED = "cancelled_recorded"
OUTCOME_STATUS_UPDATED = "status_updated"
OUTCOME_REJECTED = "rejected"

# Red nedenleri
REASON_DUPLICATE_KEY = "DUPLICATE_KEY"
REASON_NOT_FOUND = "NOT_FOUND"
REASON_INVALID_TRANSITION = "INVALID_TRANSITION"
REASON_CANCEL_TARGET_NOT_FOUND = "CANCEL_TARGET_NOT_FOUND"

# SYMBOL_CHANGE baglanti notu (BLOK 6: eski kod silinmez ilkesi)
SYMBOL_CHANGE_NOTE = (
    "SYMBOL_CHANGE: eski kod silinmez; BLOK 6 sembol gecmisi korunur "
    "(baglanti enjekte, bu modul tarafindan degistirilmez)."
)

# Gecerli durum gecisleri (SPEC bolum 4)
VALID_TRANSITIONS = {
    ActionStatus.ANNOUNCED: {ActionStatus.EFFECTIVE, ActionStatus.CANCELLED},
    ActionStatus.EFFECTIVE: {ActionStatus.COMPLETED, ActionStatus.CANCELLED},
    ActionStatus.COMPLETED: set(),
    ActionStatus.CANCELLED: set(),
    ActionStatus.SUPERSEDED: set(),
}

# Olay anahtari: (stock_id, action_type, effective_date)
EventKey = Tuple[str, ActionType, str]


def _default_clock() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class RegistryResult:
    """register()/update_status() ciktisi.

    outcome: stored | duplicate | revision_chain | cancelled_recorded |
             status_updated | rejected
    record: ilgili kayit (yeni/guncel); duplicate/red durumunda None
    olabilir.
    reason: red/duplicate neden kodu.
    superseded_version: revizyonda SUPERSEDED yapilan eski data_version.
    data_version: sonuc kaydinin data_version degeri.
    """

    outcome: str
    record: Optional[CorporateActionRecord] = None
    reason: str = ""
    superseded_version: Optional[str] = None
    data_version: Optional[str] = None


class CorporateActionRegistry:
    """Kurumsal islem kayitlarinin merkezi, surumlu ve kopyasiz defteri."""

    def __init__(self, clock: Optional[Callable[[], str]] = None, symbol_history=None):
        self._clock: Callable[[], str] = clock or _default_clock
        # BLOK 6 sembol gecmisi baglantisi ENJEKTE edilir; bu modul
        # tarafindan asla degistirilmez (eski kod silinmez ilkesi).
        self.symbol_history = symbol_history
        self._events: Dict[EventKey, List[CorporateActionRecord]] = {}
        self._cancellations: Dict[EventKey, List[CorporateActionRecord]] = {}
        # (stock_id, action_type, effective_date, kap_notice_no) dedupe kumesi
        self._dedupe: set = set()
        # kap_notice_no baglami: (event key + data_version) -> kap_notice_no
        self._kap_context: Dict[Tuple[EventKey, str], Optional[str]] = {}
        # Ekleme sirasi: (stock_id, record, kind) kind in {"action","cancellation"}
        self._all: List[Tuple[str, CorporateActionRecord, str]] = []
        self.duplicate_count = 0
        self.symbol_notes: List[str] = []

    # ------------------------------------------------------------------ #
    # Kayit
    # ------------------------------------------------------------------ #
    def register(
        self,
        record: CorporateActionRecord,
        kap_notice_no: Optional[str] = None,
    ) -> RegistryResult:
        """Kurumsal islem kaydi ekler; dedupe/surum zinciri/iptal kurallari."""
        event_key: EventKey = (
            record.stock_id,
            record.action_type,
            record.effective_date,
        )
        dedupe_key = (*event_key, kap_notice_no)
        if dedupe_key in self._dedupe:
            self.duplicate_count += 1
            return RegistryResult(
                outcome=OUTCOME_DUPLICATE, reason=REASON_DUPLICATE_KEY
            )

        # Iptal kaydi AYRI tutulur; hedef korunur.
        if record.status == ActionStatus.CANCELLED:
            return self._record_cancellation(record, kap_notice_no, event_key, dedupe_key)

        if record.action_type == ActionType.SYMBOL_CHANGE:
            self.symbol_notes.append(SYMBOL_CHANGE_NOTE)

        chain = self._events.get(event_key)
        if chain is None:
            # Ilk kayit: action-v1
            record.data_version = "action-v1"
            self._events[event_key] = [record]
            self._dedupe.add(dedupe_key)
            self._kap_context[(event_key, record.data_version)] = kap_notice_no
            self._all.append((record.stock_id, record, "action"))
            return RegistryResult(
                outcome=OUTCOME_STORED,
                record=record,
                data_version=record.data_version,
            )

        # Ayni olay icin duzeltilmis kayit -> SURUM ZINCIRI
        latest = chain[-1]
        superseded_version = latest.data_version
        latest.status = ActionStatus.SUPERSEDED  # eski surum SILINMEZ
        new_version = f"action-v{len(chain) + 1}"
        record.data_version = new_version
        chain.append(record)
        self._dedupe.add(dedupe_key)
        self._kap_context[(event_key, record.data_version)] = kap_notice_no
        self._all.append((record.stock_id, record, "action"))
        return RegistryResult(
            outcome=OUTCOME_REVISION,
            record=record,
            superseded_version=superseded_version,
            data_version=new_version,
        )

    def _record_cancellation(
        self,
        record: CorporateActionRecord,
        kap_notice_no: Optional[str],
        event_key: EventKey,
        dedupe_key,
    ) -> RegistryResult:
        """Iptal kaydini hedeften AYRI saklar; hedef kayit korunur."""
        if event_key not in self._events:
            return RegistryResult(
                outcome=OUTCOME_REJECTED, reason=REASON_CANCEL_TARGET_NOT_FOUND
            )
        bucket = self._cancellations.setdefault(event_key, [])
        record.status = ActionStatus.CANCELLED
        record.data_version = f"cancel-v{len(bucket) + 1}"
        bucket.append(record)
        self._dedupe.add(dedupe_key)
        self._kap_context[(event_key, record.data_version)] = kap_notice_no
        self._all.append((record.stock_id, record, "cancellation"))
        return RegistryResult(
            outcome=OUTCOME_CANCELLED,
            record=record,
            data_version=record.data_version,
        )

    # ------------------------------------------------------------------ #
    # Durum gecisleri
    # ------------------------------------------------------------------ #
    def update_status(
        self,
        stock_id: str,
        action_type: ActionType,
        effective_date: str,
        new_status: ActionStatus,
        kap_notice_no: Optional[str] = None,
        source: Optional[str] = None,
        official_url: Optional[str] = None,
    ) -> RegistryResult:
        """Guncel (son) surumun durumunu gecis kurallariyla degistirir.

        new_status == CANCELLED ise hedef DEGISTIRILMEZ; iptal ayri kayit
        olarak tutulur (hedef korunur ilkesi).
        """
        event_key: EventKey = (stock_id, action_type, effective_date)
        chain = self._events.get(event_key)
        if not chain:
            return RegistryResult(outcome=OUTCOME_REJECTED, reason=REASON_NOT_FOUND)
        current = chain[-1]

        if new_status == ActionStatus.CANCELLED:
            dedupe_key = (*event_key, kap_notice_no)
            if dedupe_key in self._dedupe:
                self.duplicate_count += 1
                return RegistryResult(
                    outcome=OUTCOME_DUPLICATE, reason=REASON_DUPLICATE_KEY
                )
            cancel_record = CorporateActionRecord(
                stock_id=stock_id,
                action_type=action_type,
                announcement_date=current.announcement_date,
                effective_date=effective_date,
                ratio=current.ratio,
                amount=current.amount,
                currency=current.currency,
                source=source if source is not None else current.source,
                official_url=(
                    official_url if official_url is not None else current.official_url
                ),
                status=ActionStatus.CANCELLED,
            )
            return self._record_cancellation(
                cancel_record, kap_notice_no, event_key, dedupe_key
            )

        if new_status not in VALID_TRANSITIONS[current.status]:
            return RegistryResult(
                outcome=OUTCOME_REJECTED,
                record=current,
                reason=REASON_INVALID_TRANSITION,
                data_version=current.data_version,
            )
        current.status = new_status
        return RegistryResult(
            outcome=OUTCOME_STATUS_UPDATED,
            record=current,
            data_version=current.data_version,
        )

    # ------------------------------------------------------------------ #
    # Sorgular
    # ------------------------------------------------------------------ #
    def get_actions(
        self, stock_id: str, status: Optional[ActionStatus] = None
    ) -> List[CorporateActionRecord]:
        """Hisse kayitlari.

        status=None: her olayin GUNCEL surumu + iptal kayitlari (SUPERSEDED
        surumler gizlidir; get_history ile okunur).
        status verilirse: tum katmanlarda (eski surumler dahil) o status'lu
        kayitlar.
        """
        if status is not None:
            return [
                rec
                for sid, rec, _kind in self._all
                if sid == stock_id and rec.status == status
            ]
        latest_ids = {
            id(chain[-1])
            for key, chain in self._events.items()
            if chain and key[0] == stock_id
        }
        return [
            rec
            for sid, rec, kind in self._all
            if sid == stock_id and (kind == "cancellation" or id(rec) in latest_ids)
        ]

    def get_all_records(self, stock_id: str) -> List[CorporateActionRecord]:
        """Hisseye ait TUM kayitlar (tum surumler + iptal kayitlari).

        Ham veri (actions_raw) icin kullanilir; ekleme sirasi korunur.
        """
        return [rec for sid, rec, _kind in self._all if sid == stock_id]

    def get_history(
        self, stock_id: str, action_key: Tuple[ActionType, str]
    ) -> List[CorporateActionRecord]:
        """Olayin surum zinciri (eski surumler SILINMEZ, sirayla okunur).

        action_key: (action_type, effective_date).
        """
        event_key: EventKey = (stock_id, action_key[0], action_key[1])
        return list(self._events.get(event_key, []))

    def get_cancellations(
        self, stock_id: str, action_key: Tuple[ActionType, str]
    ) -> List[CorporateActionRecord]:
        """Olaya ait ayri tutulan iptal kayitlari."""
        event_key: EventKey = (stock_id, action_key[0], action_key[1])
        return list(self._cancellations.get(event_key, []))

    def kap_notice_no_of(
        self,
        stock_id: str,
        action_type: ActionType,
        effective_date: str,
        data_version: str,
    ) -> Optional[str]:
        """Kaydin registry baglamindaki kap_notice_no degeri (11 alan disi)."""
        event_key: EventKey = (stock_id, action_type, effective_date)
        return self._kap_context.get((event_key, data_version))
