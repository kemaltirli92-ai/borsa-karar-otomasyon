"""BLOK 12 - Haber duplikasyon motoru (dedupe.py).

DedupeEngine kurallari (SPEC bolum 7):
- Ayni original_url -> DUPLICATE_SAME_URL (skor 100).
- Baslik benzerligi >= title_threshold (vars. 85) + metin benzerligi >=
  body_threshold (vars. 80) -> DUPLICATE_TEXT.
- Yayin zamani yakinligi (vars. 30 dk) + yuksek baslik benzerligi ->
  DUPLICATE_EVENT_TIME.
- Ayni olay: olay anahtar kumesi + ayni hisse + zaman penceresi ->
  DUPLICATE_SAME_EVENT (eslesme kaniti match_map ile enjekte edilir).
- AJANS KOPYASI: kaynak ajans (AA, DHA, IHA, Reuters...) ise ve baska bir
  site ayni/yakin metni yayinladiysa -> AGENCY_COPY; kopyalayan site
  canonical SAYILMAZ ve BAGIMSIZ DOGRULAMA sayilmaz
  (confirmation_credit=False).
- Canonical secimi: ajans > en erken published_at > en uzun body.
- AUTO_PRICE_TABLE icerikler dedupe ve dogrulama kredisine katilmaz.

deterministik; ag erisimi YOK.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional, Sequence, Tuple

from app.services.stock_scanning.news.fuzzy import (
    normalize,
    significant_tokens,
    token_set_ratio,
)
from app.services.stock_scanning.news.models import (
    ContentType,
    DedupeResult,
    MatchResult,
    NewsRecord,
)

DUPLICATE_SAME_URL = "DUPLICATE_SAME_URL"
DUPLICATE_TEXT = "DUPLICATE_TEXT"
DUPLICATE_EVENT_TIME = "DUPLICATE_EVENT_TIME"
DUPLICATE_SAME_EVENT = "DUPLICATE_SAME_EVENT"
AGENCY_COPY = "AGENCY_COPY"

_DEFAULT_AGENCIES = (
    "anadolu ajansi",
    "aa",
    "dha",
    "demiroren haber ajansi",
    "iha",
    "ihlas haber ajansi",
    "reuters",
    "bloomberg ht",
    "afp",
    "dow jones",
)


@dataclass
class DedupeConfig:
    """Duplikasyon esikleri (ayarlanabilir)."""

    title_threshold: int = 85
    body_threshold: int = 80
    event_time_window_minutes: int = 30
    same_event_window_minutes: int = 360
    same_event_min_keywords: int = 2
    agency_sources: tuple = _DEFAULT_AGENCIES


class _UnionFind:
    """Deterministik birlesme-kume (union-find) yapisi."""

    def __init__(self, items: Sequence[int]):
        self.parent = {i: i for i in items}

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


class DedupeEngine:
    """Haber kopyalarini tek kanonik habere indirger."""

    def __init__(self, config: Optional[DedupeConfig] = None):
        self.config = config or DedupeConfig()
        self.confirmation_credits: Dict[str, bool] = {}

    # -- kaynak tespiti ------------------------------------------------------
    def is_agency(self, source_name: Optional[str]) -> bool:
        """Kaynak haber ajansi mi? (AA, DHA, IHA, Reuters...)."""
        norm = normalize(source_name)
        if not norm:
            return False
        tokens = set(norm.split())
        for agency in self.config.agency_sources:
            a_norm = normalize(agency)
            if not a_norm:
                continue
            if a_norm in norm or set(a_norm.split()) <= tokens:
                return True
        return False

    # -- ana API -------------------------------------------------------------
    def dedupe(
        self,
        records: List[NewsRecord],
        match_map: Optional[Dict[str, List[MatchResult]]] = None,
    ) -> Tuple[List[NewsRecord], List[DedupeResult]]:
        """Kayitlari kanonik listeye ve duplikasyon gruplarina ayirir.

        - AUTO_PRICE_TABLE kayitlari dedupe'a ve dogrulama kredisine
          katilmaz; oldugu gibi kanonik listeye gecer.
        - Donus: (canonical_list, [DedupeResult]) — kanonikler yayin zamani
          ve kimlige gore sirali (deterministik).
        - confirmation_credits: her haber icin bagimsiz dogrulama kredisi
          (AGENCY_COPY kopyalari False).
        """
        self.confirmation_credits = {}
        eligible: List[NewsRecord] = []
        excluded: List[NewsRecord] = []
        for rec in records:
            if rec.content_type == ContentType.AUTO_PRICE_TABLE:
                excluded.append(rec)
            else:
                eligible.append(rec)

        n = len(eligible)
        uf = _UnionFind(range(n))
        pair_reasons: Dict[Tuple[int, int], List[str]] = {}
        for i in range(n):
            for j in range(i + 1, n):
                reasons = self._pair_reasons(eligible[i], eligible[j], match_map)
                if reasons:
                    pair_reasons[(i, j)] = reasons
                    uf.union(i, j)

        groups: Dict[int, List[int]] = {}
        for i in range(n):
            groups.setdefault(uf.find(i), []).append(i)

        canonical_records: List[NewsRecord] = []
        results: List[DedupeResult] = []
        for members in sorted(groups.values(), key=lambda m: m[0]):
            canonical_idx = self._choose_canonical([eligible[i] for i in members])
            canonical = canonical_idx
            member_ids = [eligible[i].news_id for i in members]
            reason_union: List[str] = []
            for (i, j), reasons in sorted(pair_reasons.items()):
                if i in members and j in members:
                    for r in reasons:
                        if r not in reason_union:
                            reason_union.append(r)
            dup_ids = [nid for nid in member_ids if nid != canonical.news_id]
            self._assign_credits(canonical, dup_ids, eligible, members, reason_union)
            if dup_ids:
                results.append(
                    DedupeResult(
                        canonical_news_id=canonical.news_id,
                        duplicates=dup_ids,
                        reason_codes=reason_union,
                    )
                )
            canonical_records.append(canonical)

        canonical_records.extend(excluded)  # oto fiyat tablosu: dedupe disi
        canonical_records.sort(key=self._canonical_sort_key)
        return canonical_records, results

    # -- kanonik secimi ------------------------------------------------------
    @staticmethod
    def _to_dt(value) -> Optional[datetime]:
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime(value.year, value.month, value.day)
        if isinstance(value, str) and value.strip():
            try:
                return datetime.fromisoformat(value.strip())
            except ValueError:
                return None
        return None

    def _canonical_sort_key(self, rec: NewsRecord):
        dt = self._to_dt(rec.published_at) or datetime.max
        return (dt, rec.news_id)

    def _choose_canonical(self, group: List[NewsRecord]) -> NewsRecord:
        """Canonical: ajans > en erken published_at > en uzun body."""

        def key(rec: NewsRecord):
            agency_rank = 0 if self.is_agency(rec.source_name) else 1
            dt = self._to_dt(rec.published_at) or datetime.max
            body_len = len(rec.body or "")
            return (agency_rank, dt, -body_len, rec.news_id)

        return min(group, key=key)

    def _assign_credits(
        self,
        canonical: NewsRecord,
        dup_ids: List[str],
        eligible: List[NewsRecord],
        members: List[int],
        reason_union: List[str],
    ) -> None:
        """Bagimsiz dogrulama kredisi atar.

        AGENCY_COPY grubunda ajans disi kopyalar bagimsiz dogrulama
        SAYILMAZ (confirmation_credit=False).
        """
        by_id = {eligible[i].news_id: eligible[i] for i in members}
        self.confirmation_credits[canonical.news_id] = True
        agency_copy = AGENCY_COPY in reason_union and self.is_agency(canonical.source_name)
        for nid in dup_ids:
            rec = by_id[nid]
            if agency_copy and not self.is_agency(rec.source_name):
                self.confirmation_credits[nid] = False
            else:
                self.confirmation_credits[nid] = True

    # -- cift nedenleri ------------------------------------------------------
    def _minutes_between(self, a: NewsRecord, b: NewsRecord) -> Optional[float]:
        da = self._to_dt(a.published_at)
        db = self._to_dt(b.published_at)
        if da is None or db is None:
            return None
        return abs((da - db).total_seconds()) / 60.0

    def _confirmed_stocks(
        self, news_id: str, match_map: Optional[Dict[str, List[MatchResult]]]
    ) -> set:
        if not match_map:
            return set()
        return {
            r.stock_id
            for r in match_map.get(news_id, [])
            if r.is_confirmed and r.stock_id
        }

    def _same_event(
        self,
        a: NewsRecord,
        b: NewsRecord,
        match_map: Optional[Dict[str, List[MatchResult]]],
        minutes: Optional[float],
    ) -> bool:
        """Ayni olay: olay anahtarlari + ayni hisse + zaman penceresi."""
        if minutes is None or minutes > self.config.same_event_window_minutes:
            return False
        keys_a = set(significant_tokens(a.title))
        keys_b = set(significant_tokens(b.title))
        if len(keys_a & keys_b) < self.config.same_event_min_keywords:
            return False
        stocks_a = self._confirmed_stocks(a.news_id, match_map)
        stocks_b = self._confirmed_stocks(b.news_id, match_map)
        return bool(stocks_a and stocks_b and stocks_a & stocks_b)

    def _pair_reasons(
        self,
        a: NewsRecord,
        b: NewsRecord,
        match_map: Optional[Dict[str, List[MatchResult]]],
    ) -> List[str]:
        """Iki kayit arasindaki duplikasyon nedenleri."""
        reasons: List[str] = []
        if a.original_url and a.original_url == b.original_url:
            reasons.append(DUPLICATE_SAME_URL)

        title_sim = token_set_ratio(a.title, b.title)
        body_sim = token_set_ratio(a.body, b.body)
        minutes = self._minutes_between(a, b)

        if (
            title_sim >= self.config.title_threshold
            and body_sim >= self.config.body_threshold
        ):
            reasons.append(DUPLICATE_TEXT)

        if (
            minutes is not None
            and minutes <= self.config.event_time_window_minutes
            and title_sim >= self.config.title_threshold
        ):
            reasons.append(DUPLICATE_EVENT_TIME)

        if self._same_event(a, b, match_map, minutes):
            reasons.append(DUPLICATE_SAME_EVENT)

        agency_a = self.is_agency(a.source_name)
        agency_b = self.is_agency(b.source_name)
        if reasons and agency_a != agency_b:
            reasons.append(AGENCY_COPY)
        return reasons
