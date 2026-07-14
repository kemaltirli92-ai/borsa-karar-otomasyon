"""BLOK 12 - Haber Toplama, Eslestirme ve Duplikasyon paketi.

Moduller:
- models: NewsRecord (10 alan), ContentType, MatchMethod, MatchResult,
  DedupeResult.
- aliases: AliasStore (BLOK 6 enjekte edilebilir; AMBIGUOUS_ALIAS).
- fuzzy: stdlib fuzzy motor (difflib tabanli; RapidFuzz KURULMAZ).
- matcher: NewsMatcher (tam token, guven skoru, teyit kurallari).
- tagger: ContentTagger (reklam/sponsorlu/forum/otomatik fiyat tablosu).
- dedupe: DedupeEngine (URL/metin/zaman/olay/ajans kopyasi).
- ai_adapter: AiMatcherAdapter (belirsiz eslesme; hata taramayi durdurmaz).
- collector: NewsCollector zinciri (PUAN KILIDI: ton/onem/etki YOK).

stdlib only; deterministik (saat enjekte); gercek ag YOK.
"""
from app.services.stock_scanning.news.ai_adapter import (
    AI_INVALID_RESPONSE,
    AI_SERVICE_ERROR,
    AiConfig,
    AiMatcherAdapter,
)
from app.services.stock_scanning.news.aliases import (
    AMBIGUOUS_ALIAS,
    AliasStore,
    StockAliasProfile,
)
from app.services.stock_scanning.news.collector import (
    REASON_AMBIGUOUS,
    REASON_LOW_CONFIDENCE,
    NewsCollector,
    NewsProcessResult,
    ReviewQueueItem,
)
from app.services.stock_scanning.news.dedupe import (
    AGENCY_COPY,
    DUPLICATE_EVENT_TIME,
    DUPLICATE_SAME_EVENT,
    DUPLICATE_SAME_URL,
    DUPLICATE_TEXT,
    DedupeConfig,
    DedupeEngine,
)
from app.services.stock_scanning.news.fuzzy import (
    best_match,
    normalize,
    partial_ratio,
    ratio,
    significant_tokens,
    tokenize,
    token_set_ratio,
)
from app.services.stock_scanning.news.matcher import (
    CONTEXT_WORDS,
    MatcherConfig,
    NewsMatcher,
)
from app.services.stock_scanning.news.models import (
    ContentType,
    DedupeResult,
    MatchMethod,
    MatchResult,
    NewsRecord,
)
from app.services.stock_scanning.news.tagger import (
    REASON_AD_KEYWORD,
    REASON_FORUM_SOURCE,
    REASON_FORUM_URL,
    REASON_PRICE_ROW_RATIO,
    REASON_PRICE_TITLE_TEMPLATE,
    REASON_SPONSORED_KEYWORD,
    ContentTagger,
    TaggerConfig,
    TagResult,
)

__all__ = [
    "AGENCY_COPY",
    "AI_INVALID_RESPONSE",
    "AI_SERVICE_ERROR",
    "AMBIGUOUS_ALIAS",
    "AiConfig",
    "AiMatcherAdapter",
    "AliasStore",
    "CONTEXT_WORDS",
    "ContentTagger",
    "ContentType",
    "DedupeConfig",
    "DedupeEngine",
    "DedupeResult",
    "DUPLICATE_EVENT_TIME",
    "DUPLICATE_SAME_EVENT",
    "DUPLICATE_SAME_URL",
    "DUPLICATE_TEXT",
    "MatcherConfig",
    "MatchMethod",
    "MatchResult",
    "NewsCollector",
    "NewsMatcher",
    "NewsProcessResult",
    "NewsRecord",
    "REASON_AD_KEYWORD",
    "REASON_AMBIGUOUS",
    "REASON_FORUM_SOURCE",
    "REASON_FORUM_URL",
    "REASON_LOW_CONFIDENCE",
    "REASON_PRICE_ROW_RATIO",
    "REASON_PRICE_TITLE_TEMPLATE",
    "REASON_SPONSORED_KEYWORD",
    "ReviewQueueItem",
    "StockAliasProfile",
    "TaggerConfig",
    "TagResult",
    "best_match",
    "normalize",
    "partial_ratio",
    "ratio",
    "significant_tokens",
    "token_set_ratio",
    "tokenize",
]
