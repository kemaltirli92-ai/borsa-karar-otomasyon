"""BLOK 12 - Haber toplama zinciri (collector.py).

NewsCollector zinciri (SPEC bolum 10):
etiketle -> her haber icin match -> dedupe -> canonical'lara eslesme aktar.

PUAN KILIDI: Bu modul ton/onem/etki puani HESAPLAMAZ; bu amacla alan veya
fonksiyon TANIMLAMAZ (sentiment/score/impact adinda alan bulunamaz).
Eslestirme guven skoru yalnizca SPEC bolum 3'teki MatchResult.match_score
alaninda tasir.

Deterministik: saat enjekte edilebilir (collected_at damgasi icin);
gercek ag YOK.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional

from app.services.stock_scanning.news.dedupe import DedupeEngine
from app.services.stock_scanning.news.matcher import NewsMatcher
from app.services.stock_scanning.news.models import (
    DedupeResult,
    MatchResult,
    NewsRecord,
)
from app.services.stock_scanning.news.tagger import ContentTagger, TagResult

REASON_LOW_CONFIDENCE = "LOW_CONFIDENCE"
REASON_AMBIGUOUS = "AMBIGUOUS"


@dataclass
class ReviewQueueItem:
    """Inceleme kuyrugu kaydi: dusuk guvenli / belirsiz eslesme adayi."""

    news_id: str
    stock_id: Optional[str]
    match_score: int
    reason: str


@dataclass
class NewsProcessResult:
    """NewsCollector.process() ciktisi (SPEC bolum 10).

    Zincir ciktilari: etiketlenmis kayitlar, eslesmeler, duplikasyon
    gruplari, inceleme kuyrugu. Ek olarak kanonik haberler, kanoniklere
    aktarilmis eslesmeler ve bagimsiz dogrulama kredileri tasir.

    PUAN KILIDI: ton/onem/etki puanina iliskin alan YOKTUR.
    """

    records_tagged: List[NewsRecord] = field(default_factory=list)
    matches: Dict[str, List[MatchResult]] = field(default_factory=dict)
    dedupe_groups: List[DedupeResult] = field(default_factory=list)
    review_queue: List[ReviewQueueItem] = field(default_factory=list)
    canonical_news: List[NewsRecord] = field(default_factory=list)
    canonical_matches: Dict[str, List[MatchResult]] = field(default_factory=dict)
    confirmation_credits: Dict[str, bool] = field(default_factory=dict)
    tag_results: Dict[str, TagResult] = field(default_factory=dict)


class NewsCollector:
    """Haber kayitlarini isleyen ana zincir."""

    def __init__(
        self,
        matcher: NewsMatcher,
        dedupe_engine: DedupeEngine,
        tagger: ContentTagger,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self.matcher = matcher
        self.dedupe_engine = dedupe_engine
        self.tagger = tagger
        self._clock: Callable[[], datetime] = clock or datetime.now

    def process(self, records: List[NewsRecord]) -> NewsProcessResult:
        """Zincir: etiketle -> eslestir -> duplike et -> canonical'a aktar."""
        tagged: List[NewsRecord] = []
        tag_results: Dict[str, TagResult] = {}
        matches: Dict[str, List[MatchResult]] = {}

        # 1) Etiketleme (+ collected_at damgasi; saat enjekte)
        for rec in records:
            if rec.collected_at is None:
                rec.collected_at = self._clock()
            tag_result = self.tagger.tag(rec)
            rec.content_type = tag_result.content_type
            tag_results[rec.news_id] = tag_result
            tagged.append(rec)

        # 2) Eslestirme (etiketli icerik de eslestirmeye GIRER)
        for rec in tagged:
            matches[rec.news_id] = self.matcher.match(rec)

        # 3) Duplikasyon (olay+tarih kaniti: eslesmeler match_map ile iletilir)
        canonical_news, dedupe_groups = self.dedupe_engine.dedupe(
            tagged, match_map=matches
        )

        # 4) Kanoniklere eslesme aktarimi + inceleme kuyrugu
        canonical_matches = self._merge_canonical_matches(
            tagged, matches, dedupe_groups, canonical_news
        )
        review_queue = self._build_review_queue(matches)

        return NewsProcessResult(
            records_tagged=tagged,
            matches=matches,
            dedupe_groups=dedupe_groups,
            review_queue=review_queue,
            canonical_news=canonical_news,
            canonical_matches=canonical_matches,
            confirmation_credits=dict(self.dedupe_engine.confirmation_credits),
            tag_results=tag_results,
        )

    # -- yardimcilar ---------------------------------------------------------
    @staticmethod
    def _build_review_queue(
        matches: Dict[str, List[MatchResult]]
    ) -> List[ReviewQueueItem]:
        """needs_review adaylarini inceleme kuyruguna cevirir.

        Ayni en yuksek skorlu birden cok hisse -> AMBIGUOUS; aksi halde
        LOW_CONFIDENCE.
        """
        queue: List[ReviewQueueItem] = []
        for news_id in sorted(matches.keys()):
            results = matches[news_id]
            pending = [r for r in results if r.needs_review]
            if not pending:
                continue
            max_score = max(r.match_score for r in results)
            top_stocks = {r.stock_id for r in results if r.match_score == max_score}
            reason = REASON_AMBIGUOUS if len(top_stocks) > 1 else REASON_LOW_CONFIDENCE
            for r in pending:
                queue.append(
                    ReviewQueueItem(
                        news_id=news_id,
                        stock_id=r.stock_id,
                        match_score=r.match_score,
                        reason=reason,
                    )
                )
        return queue

    @staticmethod
    def _merge_canonical_matches(
        tagged: List[NewsRecord],
        matches: Dict[str, List[MatchResult]],
        dedupe_groups: List[DedupeResult],
        canonical_news: List[NewsRecord],
    ) -> Dict[str, List[MatchResult]]:
        """Kopya haberlerin eslesmelerini kanonik habere aktarir.

        Kanonik haber, grubundaki tum uyelerin eslesmelerini birlestirir;
        hisse basina en yuksek skorlu sonuc korunur.
        """
        group_members: Dict[str, List[str]] = {}
        for group in dedupe_groups:
            group_members[group.canonical_news_id] = [
                group.canonical_news_id,
                *group.duplicates,
            ]
        for rec in canonical_news:
            group_members.setdefault(rec.news_id, [rec.news_id])

        merged: Dict[str, List[MatchResult]] = {}
        for canonical_id, member_ids in group_members.items():
            best_by_stock: Dict[str, MatchResult] = {}
            for nid in member_ids:
                for result in matches.get(nid, []):
                    if result.stock_id is None:
                        continue
                    current = best_by_stock.get(result.stock_id)
                    if current is None or (
                        result.match_score,
                        result.is_confirmed,
                    ) > (
                        current.match_score,
                        current.is_confirmed,
                    ):
                        best_by_stock[result.stock_id] = result
            merged[canonical_id] = sorted(
                best_by_stock.values(), key=lambda r: (-r.match_score, r.stock_id or "")
            )
        return merged
