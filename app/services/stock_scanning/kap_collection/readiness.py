"""BLOK 11 - Favori hazirlik kilidi (readiness.py).

FavoriteReadiness(storage, critical_types=None):
- Kritik tipler varsayilan: {"FR", "ODA", "MSL"} (finansal rapor, ozel
  durum, maddi olay).
- Son kesimden beri kritik bildirim var VE body is None (tam metin
  alinamamis) -> ready=False (CRITICAL_BODY_MISSING / FAVORI_READY_BLOCKED).
- KAP son calisma PARTIAL/FAILED iken kritik bildirim var -> ready=False
  (KAP_PARTIAL_BLOCK).
- Aksi halde ready=True.

Bu modul favori SECIMI yapmaz; sadece hazirlik durumunu bildirir.
SUPERSEDED/CANCELLED kayitlar govde kontrolunde aktif sayilmaz (yerini
yeni surum almistir / iptal bildirimi metni zorunlu degildir).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .models import KapRunStatus, RevisionStatus

# Engelleme kodlari
CRITICAL_BODY_MISSING = "CRITICAL_BODY_MISSING"
FAVORI_READY_BLOCKED = "FAVORI_READY_BLOCKED"
KAP_PARTIAL_BLOCK = "KAP_PARTIAL_BLOCK"

DEFAULT_CRITICAL_TYPES = frozenset({"FR", "ODA", "MSL"})

# Govde kontrolunde aktif sayilan revizyon durumlari
_ACTIVE_STATUSES = frozenset({RevisionStatus.ORIGINAL, RevisionStatus.REVISED})


@dataclass
class ReadinessVerdict:
    """is_ready_for_favorite sonucu."""

    ready: bool
    blocking: List[str] = field(default_factory=list)


class FavoriteReadiness:
    """Hisse icin favori surecine hazirlik durumunu raporlar."""

    def __init__(self, storage, critical_types: Optional[set] = None):
        self.storage = storage
        self.critical_types = (
            frozenset(critical_types) if critical_types else DEFAULT_CRITICAL_TYPES
        )

    def is_ready_for_favorite(self, stock_id: str) -> ReadinessVerdict:
        """Kritik bildirim tam metni / son calisma sagligi kontrolu."""
        blocking: List[str] = []
        notifications = self.storage.get_by_stock(stock_id)
        critical = [
            n for n in notifications if n.notification_type in self.critical_types
        ]
        active_critical = [
            n for n in critical if n.revision_status in _ACTIVE_STATUSES
        ]

        # Kritik bildirim tam metni alinamadiysa hazir degil
        if any(n.body is None for n in active_critical):
            blocking.append(CRITICAL_BODY_MISSING)
            blocking.append(FAVORI_READY_BLOCKED)

        # Son calisma PARTIAL/FAILED iken kritik bildirim varsa hazir degil
        last_status = None
        getter = getattr(self.storage, "last_run_status", None)
        if callable(getter):
            last_status = getter()
        if last_status in (KapRunStatus.PARTIAL.value, KapRunStatus.FAILED.value):
            if critical:
                blocking.append(KAP_PARTIAL_BLOCK)

        return ReadinessVerdict(ready=not blocking, blocking=blocking)
