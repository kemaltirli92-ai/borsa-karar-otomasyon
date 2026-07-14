"""BLOK 13 - Kurumsal veri paketi aktarimi (feed.py).

CorporateFeed(action_registry, restriction_registry, suspension_policy):
- build_packet(stock_id, validated_ids=None) -> FeedPacket
  * actions_raw: ham kayitlar (tum status; eski surumler ve iptal
    kayitlari dahil).
  * actions_validated: dogrulanmis kayitlar — status EFFECTIVE/COMPLETED
    olanlar + validated_ids ile isaretlenenler (data_version veya
    (action_type, effective_date) cifti ile).
  * restrictions_active + restrictions_history: anlik aktif tedbirler ve
    arsiv dahil tum gecmis.
  * scoring_ready + suspension_flag: SuspensionPolicy.scan_status'tan.
- Paket DEGISMEZ: frozen FeedPacket; tum listeler derin kopya + tuple.
  Uretimden sonra registry degisse bile paket sessizce degismez
  (eski rapor verisi korunur ilkesi).
- packet_version her uretimde artar (feed basina monoton sayac).

Deterministik; gercek ag YOK.
"""
from __future__ import annotations

import copy
from typing import Iterable, Optional, Tuple

from app.services.stock_scanning.corporate_actions.models import (
    ActionStatus,
    ActionType,
    CorporateActionRecord,
    FeedPacket,
)
from app.services.stock_scanning.corporate_actions.registry import (
    CorporateActionRegistry,
)
from app.services.stock_scanning.corporate_actions.restrictions import (
    RestrictionRegistry,
)
from app.services.stock_scanning.corporate_actions.suspension import (
    SuspensionPolicy,
)

VALIDATED_STATUSES = {ActionStatus.EFFECTIVE, ActionStatus.COMPLETED}


class CorporateFeed:
    """Sonraki modullere ham/dogrulanmis kurumsal veri paketi uretir."""

    def __init__(
        self,
        action_registry: CorporateActionRegistry,
        restriction_registry: RestrictionRegistry,
        suspension_policy: SuspensionPolicy,
    ):
        self.action_registry = action_registry
        self.restriction_registry = restriction_registry
        self.suspension_policy = suspension_policy
        self._packet_counter = 0

    @staticmethod
    def _is_marked(record: CorporateActionRecord, validated_ids: set) -> bool:
        """validated_ids: data_version metinleri veya
        (action_type, effective_date) ciftleri icerir."""
        if record.data_version in validated_ids:
            return True
        return (record.action_type, record.effective_date) in validated_ids

    def build_packet(
        self, stock_id: str, validated_ids: Optional[Iterable] = None
    ) -> FeedPacket:
        """Hisse icin DEGISMEZ kurumsal veri paketi uretir."""
        marks = set(validated_ids or [])

        all_records = self.action_registry.get_all_records(stock_id)
        actions_raw = tuple(copy.deepcopy(r) for r in all_records)
        actions_validated = tuple(
            copy.deepcopy(r)
            for r in all_records
            if r.status in VALIDATED_STATUSES or self._is_marked(r, marks)
        )

        restrictions_active = tuple(
            copy.deepcopy(r)
            for r in self.restriction_registry.active_restrictions(stock_id)
        )
        restrictions_history = tuple(
            copy.deepcopy(r)
            for r in self.restriction_registry.restriction_history(stock_id)
        )

        scan = self.suspension_policy.scan_status(stock_id)

        self._packet_counter += 1
        return FeedPacket(
            stock_id=stock_id,
            actions_raw=actions_raw,
            actions_validated=actions_validated,
            restrictions_active=restrictions_active,
            restrictions_history=restrictions_history,
            scoring_ready=scan.scoring_ready,
            suspension_flag=bool(scan.active_halts),
            packet_version=self._packet_counter,
        )
