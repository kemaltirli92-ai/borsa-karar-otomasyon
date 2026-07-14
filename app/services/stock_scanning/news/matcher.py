"""BLOK 12 - Haber-hisse eslestirme motoru (matcher.py).

NewsMatcher kurallari (SPEC bolum 6):

1. Kelime-ici eslesme YASAK: kod/unvan aramasi her zaman TAM TOKEN sinirlidir
   (fuzzy.tokenize ile; "IS" kodu "ISLEM" icinde yakalanamaz).
2. Kisa kodlar (<=2 harf) icin baglam sarti: metinde borsa/hisse baglami
   kelimesi yoksa kod eslesmesi sayilmaz.
3. Sadece hisse kodu gecmesi KESIN eslesme DEGIL: kod tek basina max 70
   (is_confirmed=False). Kod + baglam (unvan/marka/olay) ile 85+ olabilir.
4. Skor tablosu (config'den ayarlanabilir):
   tam unvan 95 (confirmed), kisa ad 88 (confirmed), eski ad/kod 82
   (confirmed, historical), marka/bagli ortaklik 75, istirak/yonetici 65
   (review), kod tek basina 70, fuzzy>=90 -> 85 (confirmed),
   fuzzy 75-89 -> 60 (needs_review), <75 eslesme yok.
5. DUSUK GUVEN: match_score < confirm_threshold (vars. 80) ->
   is_confirmed=False; haber hisseye KESIN baglanmaz, needs_review.
6. Ayni skorla birden cok hisse -> AMBIGUOUS: hicbirine baglanmaz.
7. AMBIGUOUS_ALIAS: alias birden cok hisseye bagliysa otomatik teyit yok.
8. AI sadece belirsiz aralikta devrededir ve ASLA tek basina teyit olamaz.

Olay+tarih karsilastirmasi: event_keywords() ile cikarilan olay anahtarlari
dedupe motoruna DUPLICATE_SAME_EVENT kaniti olarak kullandirilir.

Deterministik: saat enjekte edilebilir; ag erisimi YOK.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, List, Optional, Tuple

from app.services.stock_scanning.news.aliases import AliasStore
from app.services.stock_scanning.news.fuzzy import (
    best_match,
    normalize,
    significant_tokens,
    tokenize,
    token_set_ratio,
)
from app.services.stock_scanning.news.models import MatchMethod, MatchResult, NewsRecord

# Borsa/hisse baglami kelimeleri (normalize edilmis halde karsilastirilir).
CONTEXT_WORDS = frozenset(
    {
        "hisse", "hissesi", "hisseleri", "hisseler", "borsa", "bist",
        "bist100", "kod", "kodu", "sirket", "sirketi",
        "tl", "fiyat", "fiyati", "fiyatlari", "kapanis",
        "acilis", "halka", "arz", "pay", "paylari", "piyasa", "endeks",
        "lot", "temettu", "bedelsiz", "sermaye", "tahta",
    }
)

# Sadece baglamla teyit edilebilecek zayif varlik tipleri.
_WEAK_METHODS = (
    MatchMethod.BRAND,
    MatchMethod.SUBSIDIARY,
    MatchMethod.AFFILIATE,
    MatchMethod.EXECUTIVE,
)


@dataclass
class MatcherConfig:
    """Eslestirme esik ve skor tablosu (SPEC bolum 6, ayarlanabilir)."""

    score_full_name: int = 95
    score_short_name: int = 88
    score_old: int = 82
    score_brand: int = 75
    score_subsidiary: int = 75
    score_affiliate: int = 65
    score_executive: int = 65
    score_code_alone: int = 70
    score_fuzzy_high: int = 85
    score_fuzzy_mid: int = 60
    fuzzy_high_threshold: int = 90
    fuzzy_mid_threshold: int = 75
    confirm_threshold: int = 80
    combination_bonus: int = 10
    context_bonus: int = 10
    short_code_max_len: int = 2


class NewsMatcher:
    """Haber kaydini XK100 hisseleriyle guven skorlu eslestirir."""

    def __init__(
        self,
        alias_store: AliasStore,
        config: Optional[MatcherConfig] = None,
        ai=None,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self.alias_store = alias_store
        self.config = config or MatcherConfig()
        self.ai = ai
        self._clock: Callable[[], datetime] = clock or datetime.now

    # -- yardimcilar ---------------------------------------------------------
    def _base_score(self, method: MatchMethod) -> int:
        c = self.config
        return {
            MatchMethod.FULL_NAME: c.score_full_name,
            MatchMethod.SHORT_NAME: c.score_short_name,
            MatchMethod.OLD_NAME: c.score_old,
            MatchMethod.OLD_CODE: c.score_old,
            MatchMethod.BRAND: c.score_brand,
            MatchMethod.SUBSIDIARY: c.score_subsidiary,
            MatchMethod.AFFILIATE: c.score_affiliate,
            MatchMethod.EXECUTIVE: c.score_executive,
            MatchMethod.CODE: c.score_code_alone,
        }.get(method, 0)

    @staticmethod
    def _contains_token_seq(tokens: List[str], seq: List[str]) -> bool:
        """TAM TOKEN sinirli ardisik alt-dizi aramasi (substring DEGIL)."""
        n = len(seq)
        if n == 0 or n > len(tokens):
            return False
        return any(tokens[i : i + n] == seq for i in range(len(tokens) - n + 1))

    def _code_hit(self, norm_code: str, tokens: List[str], has_context: bool) -> bool:
        """Kod eslesmesi: tam token + kisa kodlar icin baglam sarti."""
        if not norm_code or norm_code not in tokens:
            return False
        if len(norm_code) <= self.config.short_code_max_len and not has_context:
            return False
        return True

    # -- olay anahtarlari (dedupe'e kanit) -----------------------------------
    def event_keywords(self, news: NewsRecord) -> List[str]:
        """Haberin olay anahtar kelimeleri (baslik agirlikli + metin)."""
        return significant_tokens(f"{news.title or ''} {news.body or ''}")

    # -- ana eslestirme ------------------------------------------------------
    def match(self, news: NewsRecord) -> List[MatchResult]:
        """Haber icin aday eslesmeleri skor sirali dondurur.

        Eslesme yoksa bos liste. Sonuclar skor azalan, esitlikte stock_id
        artan siradadir (deterministik).
        """
        text = f"{news.title or ''} {news.body or ''}"
        tokens = tokenize(text)
        title_norm = normalize(news.title)
        if not tokens:
            return []
        has_context = any(tok in CONTEXT_WORDS for tok in tokens)

        results: List[MatchResult] = []

        for stock_id in self.alias_store.stock_ids():
            hits = self._collect_hits(stock_id, tokens, title_norm, has_context)
            if not hits:
                continue
            score, method, entity = self._combine(hits, has_context)
            if score <= 0:
                continue
            ambiguous_alias = any(
                self.alias_store.is_ambiguous(norm) for _b, _m, _e, norm, _f in hits
            )
            is_confirmed = score >= self.config.confirm_threshold and not ambiguous_alias
            results.append(
                MatchResult(
                    stock_id=stock_id,
                    match_score=score,
                    match_method=method,
                    matched_entity=entity,
                    is_confirmed=is_confirmed,
                    needs_review=not is_confirmed,
                )
            )

        if not results:
            return []

        # AMBIGUOUS: ayni en yuksek skorla birden cok hisse -> hicbiri teyit olmaz.
        max_score = max(r.match_score for r in results)
        top = [r for r in results if r.match_score == max_score]
        top_stocks = {r.stock_id for r in top}
        if len(top_stocks) > 1:
            for r in results:
                if r.match_score == max_score:
                    r.is_confirmed = False
                    r.needs_review = True

        # AI: SADECE belirsiz araliktaki adaylar icin; asla tek basina teyit olamaz.
        if self.ai is not None:
            for r in results:
                if r.is_confirmed:
                    continue
                if self.ai.in_range(r.match_score):
                    self._apply_ai(news, r)

        results.sort(key=lambda r: (-r.match_score, r.stock_id or ""))
        return results

    def _collect_hits(
        self,
        stock_id: str,
        tokens: List[str],
        title_norm: str,
        has_context: bool,
    ) -> List[Tuple[int, MatchMethod, str, str, bool]]:
        """Bir hisse icin tum varlik isabetlerini toplar.

        Donus: (taban_skor, yontem, orijinal_varlik, normalize_varlik, fuzzy_mi)
        """
        hits: List[Tuple[int, MatchMethod, str, str, bool]] = []
        pairs_by_method = self.alias_store.entity_pairs(stock_id)

        for method, pairs in pairs_by_method.items():
            for orig, norm in pairs:
                if not norm:
                    continue
                if method in (MatchMethod.CODE, MatchMethod.OLD_CODE):
                    if self._code_hit(norm, tokens, has_context):
                        hits.append((self._base_score(method), method, orig, norm, False))
                else:
                    seq = norm.split()
                    if self._contains_token_seq(tokens, seq):
                        hits.append((self._base_score(method), method, orig, norm, False))

        # Fuzzy unvan eslestirme (baslik vs tam unvan / kisa ad).
        # Tam isabet varsa fuzzy GEREKSIZDIR (skor tablosu korunur).
        exact_name_hit = any(
            m in (MatchMethod.FULL_NAME, MatchMethod.SHORT_NAME)
            for _b, m, _e, _n, _f in hits
        )
        if exact_name_hit:
            return hits
        name_candidates: List[Tuple[str, str]] = []
        for method in (MatchMethod.FULL_NAME, MatchMethod.SHORT_NAME):
            for orig, norm in pairs_by_method.get(method, []):
                if norm:
                    name_candidates.append((orig, norm))
        if name_candidates and title_norm:
            norms = [norm for _o, norm in name_candidates]
            best_norm, fuzzy_score = best_match(title_norm, norms, scorer=token_set_ratio)
            if best_norm is not None and fuzzy_score >= self.config.fuzzy_mid_threshold:
                orig = next(o for o, n in name_candidates if n == best_norm)
                if fuzzy_score >= self.config.fuzzy_high_threshold:
                    hits.append(
                        (self.config.score_fuzzy_high, MatchMethod.FULL_NAME, orig, best_norm, True)
                    )
                else:
                    hits.append(
                        (self.config.score_fuzzy_mid, MatchMethod.FULL_NAME, orig, best_norm, True)
                    )
        return hits

    def _combine(
        self,
        hits: List[Tuple[int, MatchMethod, str, str, bool]],
        has_context: bool,
    ) -> Tuple[int, MatchMethod, str]:
        """Isabetleri tek skora indirger (SPEC bolum 6 skor tablosu).

        - En yuksek taban skor bazdir.
        - 2+ farkli varlik tipi isabeti -> kombinasyon bonusu (kod+baglam 85+).
        - Sadece zayif varlik (marka/bagli ortaklik/istirak/yonetici) +
          baglam kelimesi -> baglam bonusu.
        """
        best = max(hits, key=lambda h: (h[0], -list(MatchMethod).index(h[1])))
        max_base, method, entity = best[0], best[1], best[2]
        methods = {h[1] for h in hits}
        score = max_base
        if len(methods) >= 2:
            score += self.config.combination_bonus
        elif methods.issubset(set(_WEAK_METHODS)) and has_context:
            score += self.config.context_bonus
        # Hicbir kombinasyon tam unvan guvenini (95) asamaz.
        return min(self.config.score_full_name, score), method, entity

    def _apply_ai(self, news: NewsRecord, result: MatchResult) -> None:
        """AI gorusunu uygular; AI ASLA tek basina teyit edemez."""
        adjustment = self.ai.assess(news, result)
        if adjustment is None:
            return
        stock_id = adjustment.get("stock_id") or result.stock_id
        score = adjustment.get("score")
        if isinstance(score, int):
            result.match_score = max(0, min(100, score))
        result.stock_id = stock_id
        result.match_method = MatchMethod.AI_ASSISTED
        # Kilit: AI skoru ne olursa olsun teyit kural motorundan gelir.
        result.is_confirmed = False
        result.needs_review = True
