"""BLOK 11 - KAP Bildirim Toplama modulu (kap_collection paketi).

Bilesenler:
- models.KapNotification (TAM 17 alan) / RevisionStatus / AttachmentMeta /
  KapRunStatus / KapHealth / KapCollectionResult: standart KAP kaydi ve
  calisma sonucu.
- feed.KapFeed / KapFeedUnavailableError / ProfileChecker: merkezi akis
  (fetcher enjekte, gercek ag YOK), calisma-ici tek detay cekimi, profil
  haftalik (7 gun) penceresi (PROFILES_SKIPPED_FRESH).
- matcher.KapMatcher / MatchOutcome: BLOK 6 resolve enjekte; evren disi
  OUT_OF_UNIVERSE, belirsiz MATCH_AMBIGUOUS + SYMBOL_VERIFICATION_PENDING,
  eslesmeyen UNMATCHED (yanlis hisseye baglanti YOK).
- collector.KapCollector: 6 adimli zincir, dedupe, revizyon/iptal zinciri,
  KAP kesintisinde PARTIAL/FAILED + kap_health=DOWN (exception sizmaz).
- storage.KapStorage / StoredResult / StoredRecord: notification_id unique,
  surum zinciri (previous_notification_id, superseded_by), bellek ici veya
  SQLite kap_notifications tablosu.
- readiness.FavoriteReadiness / ReadinessVerdict: kritik bildirim tam
  metni yoksa FAVORI HAZIR DEGIL kilidi.

KAPSAM KILIDI: bu pakette bildirim etki/yon alani ve hesabi YOKTUR.
Dis bagimlilik yoktur (stdlib). ASCII identifier, Turkce docstring,
deterministik (saat enjekte).
"""
from .collector import (
    CANCELLATION_RECORDED,
    CRITICAL_TYPES,
    DETAIL_MISSING,
    DUPLICATE_SKIPPED,
    FEED_UNAVAILABLE,
    ITEM_PROCESSING_ERROR,
    REVISION_CHAINED,
    STEP1_FEED_FETCHED,
    STEP2_MATCHED,
    STEP3_DETAIL_FETCHED,
    STEP4_ATTACHMENTS,
    STEP5_REVISION,
    STEP6_STORED,
    KapCollector,
)
from .feed import (
    PROFILES_CHECKED,
    PROFILES_CHECK_FAILED,
    PROFILES_SKIPPED_FRESH,
    PROFILES_SKIPPED_NO_FETCHER,
    WEEKLY_WINDOW_DAYS,
    KapFeed,
    KapFeedUnavailableError,
    ProfileChecker,
)
from .matcher import (
    KAP_PLATFORM,
    MATCH_AMBIGUOUS,
    MATCHED,
    OUT_OF_UNIVERSE,
    SYMBOL_VERIFICATION_PENDING,
    UNMATCHED,
    KapMatcher,
    MatchOutcome,
)
from .models import (
    AttachmentMeta,
    KapCollectionResult,
    KapHealth,
    KapNotification,
    KapRunStatus,
    RevisionStatus,
)
from .readiness import (
    CRITICAL_BODY_MISSING,
    DEFAULT_CRITICAL_TYPES,
    FAVORI_READY_BLOCKED,
    KAP_PARTIAL_BLOCK,
    FavoriteReadiness,
    ReadinessVerdict,
)
from .storage import (
    DUPLICATE,
    INSERTED,
    KAP_TABLE,
    REVISION_CHAIN,
    KapStorage,
    StoredRecord,
    StoredResult,
)

__all__ = [
    # models
    "KapNotification",
    "RevisionStatus",
    "AttachmentMeta",
    "KapRunStatus",
    "KapHealth",
    "KapCollectionResult",
    # feed
    "KapFeed",
    "KapFeedUnavailableError",
    "ProfileChecker",
    "WEEKLY_WINDOW_DAYS",
    "PROFILES_CHECKED",
    "PROFILES_SKIPPED_FRESH",
    "PROFILES_SKIPPED_NO_FETCHER",
    "PROFILES_CHECK_FAILED",
    # matcher
    "KapMatcher",
    "MatchOutcome",
    "MATCHED",
    "OUT_OF_UNIVERSE",
    "MATCH_AMBIGUOUS",
    "UNMATCHED",
    "SYMBOL_VERIFICATION_PENDING",
    "KAP_PLATFORM",
    # collector
    "KapCollector",
    "CRITICAL_TYPES",
    "DETAIL_MISSING",
    "DUPLICATE_SKIPPED",
    "REVISION_CHAINED",
    "CANCELLATION_RECORDED",
    "FEED_UNAVAILABLE",
    "ITEM_PROCESSING_ERROR",
    "STEP1_FEED_FETCHED",
    "STEP2_MATCHED",
    "STEP3_DETAIL_FETCHED",
    "STEP4_ATTACHMENTS",
    "STEP5_REVISION",
    "STEP6_STORED",
    # storage
    "KapStorage",
    "StoredResult",
    "StoredRecord",
    "KAP_TABLE",
    "INSERTED",
    "DUPLICATE",
    "REVISION_CHAIN",
    # readiness
    "FavoriteReadiness",
    "ReadinessVerdict",
    "CRITICAL_BODY_MISSING",
    "FAVORI_READY_BLOCKED",
    "KAP_PARTIAL_BLOCK",
    "DEFAULT_CRITICAL_TYPES",
]
