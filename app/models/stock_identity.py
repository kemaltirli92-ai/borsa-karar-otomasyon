"""BLOK 6 - Sirket Kimligi ve Sembol Eslestirme: veri modelleri.

Dataclass tabanli, veritabani bagimsiz modeller. Repository deseni ile
kullanilir; ileride SQLAlchemy'ye tasinabilir.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional

# Desteklenen platformlar
VALID_PLATFORMS = ("bist", "yahoo", "google", "tradingview", "kap")


class KapLinkStatus(str, Enum):
    """KAP link dogrulama durumu."""

    KAP_LINK_VALID = "KAP_LINK_VALID"
    KAP_LINK_BROKEN = "KAP_LINK_BROKEN"
    KAP_LINK_UNCHECKED = "KAP_LINK_UNCHECKED"


class VerificationStatus(str, Enum):
    """Hisse dogrulama durumu."""

    VERIFIED = "VERIFIED"
    SYMBOL_VERIFICATION_PENDING = "SYMBOL_VERIFICATION_PENDING"
    REJECTED = "REJECTED"
    DUPLICATE_SYMBOL = "DUPLICATE_SYMBOL"


@dataclass
class StockIdentity:
    """Sistem genelinde tek merkezi kimlik.

    stock_id: "STK-000001" formatinda, benzersiz, counter tabanli (deterministik).
    merged_into: cift kayit birlestirildiginde hedef stock_id (None = birlesmemis).
    """

    stock_id: str
    company_name: str
    isin: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    status: VerificationStatus = VerificationStatus.VERIFIED
    merged_into: Optional[str] = None


@dataclass
class SymbolRecord:
    """Bir hissenin bir platformdaki sembol kaydi.

    valid_to None ise kayit aciktir (aktif). Gecerlilik araligi:
    valid_from <= d < valid_to (valid_to None ise sinirsiz).
    """

    stock_id: str
    platform: str
    symbol: str
    valid_from: date
    valid_to: Optional[date] = None
    is_active: bool = True


@dataclass
class KapLink:
    """KAP (Kamuyu Aydinlatma Platformu) link kaydi."""

    stock_id: str
    url: str
    status: KapLinkStatus = KapLinkStatus.KAP_LINK_UNCHECKED
    last_checked_at: Optional[datetime] = None
    fail_count: int = 0


@dataclass
class SymbolAuditEntry:
    """Sembol degisikliklerinin denetim (audit) kaydi."""

    audit_id: str
    stock_id: str
    action: str
    platform: str
    old_symbol: Optional[str]
    new_symbol: Optional[str]
    admin_user: str
    timestamp: datetime
    reason: Optional[str] = None


@dataclass
class VerificationQueueItem:
    """SYMBOL_VERIFICATION_PENDING kuyruk kaydi.

    stock_id None olabilir (hic kaydi olmayan sembol sorgulari icin);
    bu durumda query alani cozulemeyen sembolu tasir.
    """

    queue_id: str
    stock_id: Optional[str]
    reason: str
    created_at: datetime
    resolved: bool = False
    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    query: Optional[str] = None
    note: Optional[str] = None


@dataclass
class ResolveResult:
    """resolve() / resolve_old_code() sonucu.

    historical=True: eslesme kapali (gecmis) bir kayit ya da birlestirilmis
    bir hisse uzerinden yapildi.
    """

    stock_id: str
    matched_by: str  # "symbol" | "company_name" | "historical_symbol"
    platform: Optional[str] = None
    matched_symbol: Optional[str] = None
    historical: bool = False
