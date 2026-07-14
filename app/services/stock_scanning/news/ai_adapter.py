"""BLOK 12 - Istege bagli AI eslestirme adaptoru (ai_adapter.py).

AiMatcherAdapter kurallari (SPEC bolum 9):
- SADECE belirsiz eslestirmeler icin cagrilir (skor araligi config:
  vars. 55-79).
- ai_client None -> AI kapali: belirsizler needs_review'da kalir, tarama
  DEVAM EDER.
- ai_client hata firlatirsa -> AI_SERVICE_ERROR logla, tarama DURMAZ,
  aday needs_review'da kalir.
- ai_client yaniti schema dogrulamasindan gecer; gecersiz yanit yok sayilir
  (AI_INVALID_RESPONSE).
- AI skoru ASLA tek basina teyit olamaz (is_confirmed yine kural
  motorundan gelir; bu kilit matcher.py tarafinda uygulanir).

ai_client duck-typed: `match_news(news, candidate)` metodu ya da
cagrilabilir (callable) nesne. Beklenen yanit semasi:
{"stock_id": str|None, "score": int(0-100), "reason": str(ops.)}.

Deterministik; gercek ag YOK (ai_client her zaman mock/enjekte).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from app.services.stock_scanning.news.models import MatchResult, NewsRecord

AI_SERVICE_ERROR = "AI_SERVICE_ERROR"
AI_INVALID_RESPONSE = "AI_INVALID_RESPONSE"

logger = logging.getLogger(__name__)


@dataclass
class AiConfig:
    """AI devreye girme araligi (belirsiz eslesme bandi)."""

    min_score: int = 55
    max_score: int = 79


class AiMatcherAdapter:
    """Belirsiz eslesmeler icin opsiyonel AI danisma adaptoru."""

    def __init__(self, ai_client=None, config: Optional[AiConfig] = None):
        self.ai_client = ai_client
        self.config = config or AiConfig()
        self.errors: list = []
        self.call_count = 0

    @property
    def enabled(self) -> bool:
        """AI acik mi? (ai_client enjekte edildiyse)."""
        return self.ai_client is not None

    def in_range(self, score: int) -> bool:
        """Skor belirsiz aralikta mi?"""
        return self.config.min_score <= score <= self.config.max_score

    def assess(self, news: NewsRecord, candidate: MatchResult) -> Optional[dict]:
        """AI'dan aday degerlendirmesi ister.

        - AI kapali -> None (tarama devam eder).
        - Hata -> AI_SERVICE_ERROR logla, None don (tarama DURMAZ).
        - Gecersiz yanit -> AI_INVALID_RESPONSE logla, None don.
        - Gecerli yanit -> {"stock_id": ..., "score": ..., "reason": ...}.
        """
        if self.ai_client is None:
            return None
        self.call_count += 1
        try:
            if hasattr(self.ai_client, "match_news"):
                raw = self.ai_client.match_news(news, candidate)
            elif callable(self.ai_client):
                raw = self.ai_client(news, candidate)
            else:
                self._record_error(
                    f"{AI_INVALID_RESPONSE}: ai_client cagrilabilir degil"
                )
                return None
        except Exception as exc:  # noqa: BLE001 - AI hatasi taramayi durdurmaz
            self._record_error(f"{AI_SERVICE_ERROR}: {type(exc).__name__}: {exc}")
            return None
        validated = self._validate(raw)
        if validated is None:
            self._record_error(f"{AI_INVALID_RESPONSE}: {raw!r}")
            return None
        return validated

    def _validate(self, raw) -> Optional[dict]:
        """Yanit schema dogrulamasi: stock_id (str|None) + score (int 0-100)."""
        if not isinstance(raw, dict):
            return None
        stock_id = raw.get("stock_id")
        score = raw.get("score")
        if stock_id is not None and not isinstance(stock_id, str):
            return None
        if isinstance(score, bool) or not isinstance(score, int):
            return None
        if not (0 <= score <= 100):
            return None
        reason = raw.get("reason")
        if reason is not None and not isinstance(reason, str):
            return None
        return {"stock_id": stock_id, "score": score, "reason": reason}

    def _record_error(self, message: str) -> None:
        """Hatayi loglar ve hata listesine ekler (tarama akisi bozulmaz)."""
        self.errors.append(message)
        logger.warning(message)
