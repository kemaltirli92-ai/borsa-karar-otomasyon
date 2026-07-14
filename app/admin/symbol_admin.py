"""BLOK 6 - Yonetici paneli: sembol duzenleme + audit log.

Tum yonetici islemleri audit log'a yazilir; admin_user bos olamaz.
"""
from __future__ import annotations

from typing import List, Optional

from app.models.stock_identity import SymbolAuditEntry, VerificationStatus
from app.services.stock_scanning.symbol_identity import SymbolIdentityService


class SymbolAdmin:
    """Yonetici paneli islemleri."""

    def __init__(self, service: SymbolIdentityService):
        self.service = service

    @staticmethod
    def _require_admin(admin_user) -> str:
        if not admin_user or not str(admin_user).strip():
            raise ValueError("admin_user bos olamaz")
        return str(admin_user).strip()

    def admin_update_symbol(
        self,
        admin_user: str,
        stock_id: str,
        platform: str,
        new_symbol: str,
        reason: Optional[str] = None,
    ) -> SymbolAuditEntry:
        """Validasyon + degisiklik + audit.

        Platformda aktif sembol varsa CHANGE_SYMBOL, yoksa ADD_SYMBOL
        olarak kaydedilir.
        """
        admin = self._require_admin(admin_user)
        self.service.get_stock(stock_id)
        platform_norm = str(platform).strip().lower()
        active = self.service.get_active_symbol(stock_id, platform_norm)
        if active is None:
            rec = self.service.add_symbol(stock_id, platform_norm, new_symbol)
            return self.service._write_audit(
                stock_id, "ADD_SYMBOL", platform_norm, None, rec.symbol, admin, reason
            )
        self.service.change_symbol(
            stock_id,
            platform_norm,
            new_symbol,
            effective_date=self.service.now().date(),
            admin_user=admin,
            reason=reason,
        )
        return self.service.get_audit_log(stock_id)[-1]

    def admin_merge_duplicate(
        self, admin_user: str, keep_id: str, drop_id: str
    ) -> List[SymbolAuditEntry]:
        """Cift kayit birlestirme (audit ile).

        drop_id'nin acik sembolleri kapanir (gecmis olarak korunur),
        drop kaydi DUPLICATE_SYMBOL olarak isaretlenir ve keep_id'ye
        yonlendirilir (merged_into). Eski kod sorgulari bundan sonra
        keep_id'ye cozumlenir (historical=True).
        """
        admin = self._require_admin(admin_user)
        if keep_id == drop_id:
            raise ValueError("keep_id ve drop_id farkli olmali")
        self.service.get_stock(keep_id)
        drop = self.service.get_stock(drop_id)
        if drop.merged_into is not None:
            raise ValueError(f"{drop_id} zaten birlestirilmis: {drop.merged_into}")

        today = self.service.now().date()
        for rec in self.service.get_symbol_history(drop_id):
            if rec.is_active:
                rec.is_active = False
                rec.valid_to = today

        drop.status = VerificationStatus.DUPLICATE_SYMBOL
        drop.merged_into = keep_id

        a1 = self.service._write_audit(
            drop_id, "MERGE_DUPLICATE", "", None, None, admin,
            reason=f"merged into {keep_id}",
        )
        a2 = self.service._write_audit(
            keep_id, "MERGE_DUPLICATE", "", None, None, admin,
            reason=f"absorbed {drop_id}",
        )
        return [a1, a2]

    def admin_resolve_pending(
        self,
        admin_user: str,
        queue_id: str,
        approve: bool,
        note: Optional[str] = None,
    ):
        """Bekleyen kayit onay/red.

        Onay: hisse durumu VERIFIED olur. Red: REJECTED olur.
        Her iki durumda da kuyruk kaydi cozulmus sayilir ve audit yazilir.
        """
        admin = self._require_admin(admin_user)
        item = self.service.get_queue_item(queue_id)
        if item.resolved:
            raise ValueError(f"Kuyruk kaydi zaten cozulmus: {queue_id}")
        item.resolved = True
        item.resolved_by = admin
        item.resolved_at = self.service.now()
        item.note = note
        if item.stock_id is not None:
            st = self.service.get_stock(item.stock_id)
            st.status = (
                VerificationStatus.VERIFIED if approve else VerificationStatus.REJECTED
            )
        return self.service._write_audit(
            item.stock_id or "",
            "RESOLVE_PENDING",
            "",
            None,
            None,
            admin,
            reason=f"approve={approve}; note={note}",
        )

    def get_audit_log(self, stock_id: Optional[str] = None) -> List[SymbolAuditEntry]:
        return self.service.get_audit_log(stock_id)
