"""BLOK 13 - Kurumsal Islemler ve Aktif Tedbirler paketi.

Moduller:
- models: ActionType (11), CorporateActionRecord (11 alan), ActionStatus (5),
  RestrictionType (7), TradingRestriction (7 alan), FeedPacket (frozen),
  ScanStatus.
- registry: CorporateActionRegistry (dedupe, surum zinciri action-vN,
  durum gecis kontrolu, iptal ayri kayit, gecmis koruma).
- restrictions: RestrictionRegistry (dedupe, otomatik is_active,
  REVIEW_REQUIRED, suresi biten tedbir arsivlenir).
- suspension: SuspensionPolicy (islem durdurmada hisse korunur,
  scoring_ready=False; halt bitince True).
- feed: CorporateFeed (ham/dogrulanmis paket, frozen, packet_version).
- collector: CorporateCollector (kaynak enjekte; kaynak yok/hata ->
  SOURCE_UNAVAILABLE, tarama durmaz, eksik hisseye bos paket;
  PUAN KILIDI: sentiment/score/impact YOK).

stdlib only; deterministik (saat enjekte); gercek ag YOK.
"""
from app.services.stock_scanning.corporate_actions.collector import (
    SOURCE_OK,
    SOURCE_UNAVAILABLE,
    CollectionReport,
    CorporateCollector,
)
from app.services.stock_scanning.corporate_actions.feed import (
    VALIDATED_STATUSES,
    CorporateFeed,
)
from app.services.stock_scanning.corporate_actions.models import (
    ActionStatus,
    ActionType,
    CorporateActionRecord,
    FeedPacket,
    RestrictionType,
    ScanStatus,
    TradingRestriction,
)
from app.services.stock_scanning.corporate_actions.registry import (
    OUTCOME_CANCELLED,
    OUTCOME_DUPLICATE,
    OUTCOME_REJECTED,
    OUTCOME_REVISION,
    OUTCOME_STATUS_UPDATED,
    OUTCOME_STORED,
    REASON_CANCEL_TARGET_NOT_FOUND,
    REASON_DUPLICATE_KEY,
    REASON_INVALID_TRANSITION,
    REASON_NOT_FOUND,
    SYMBOL_CHANGE_NOTE,
    VALID_TRANSITIONS,
    CorporateActionRegistry,
    RegistryResult,
)
from app.services.stock_scanning.corporate_actions.restrictions import (
    REVIEW_REQUIRED,
    RestrictionRegistry,
    RestrictionResult,
)
from app.services.stock_scanning.corporate_actions.suspension import (
    HALT_NOTE,
    RISK_NOTE_PREFIX,
    SuspensionPolicy,
)

__all__ = [
    "ActionStatus",
    "ActionType",
    "CollectionReport",
    "CorporateActionRecord",
    "CorporateActionRegistry",
    "CorporateCollector",
    "CorporateFeed",
    "FeedPacket",
    "HALT_NOTE",
    "OUTCOME_CANCELLED",
    "OUTCOME_DUPLICATE",
    "OUTCOME_REJECTED",
    "OUTCOME_REVISION",
    "OUTCOME_STATUS_UPDATED",
    "OUTCOME_STORED",
    "REASON_CANCEL_TARGET_NOT_FOUND",
    "REASON_DUPLICATE_KEY",
    "REASON_INVALID_TRANSITION",
    "REASON_NOT_FOUND",
    "REVIEW_REQUIRED",
    "RISK_NOTE_PREFIX",
    "RegistryResult",
    "RestrictionRegistry",
    "RestrictionResult",
    "RestrictionType",
    "SOURCE_OK",
    "SOURCE_UNAVAILABLE",
    "SYMBOL_CHANGE_NOTE",
    "ScanStatus",
    "SuspensionPolicy",
    "TradingRestriction",
    "VALIDATED_STATUSES",
    "VALID_TRANSITIONS",
]
