"""BLOK 12 - Icerik etiketleme (tagger.py).

ContentTagger kurallari (SPEC bolum 8):
- reklam/sponsorlu: baslik/metinde "reklam", "advertorial", "tanitim yazisi",
  "sponsorlu" vb. + kaynak etiketi -> ADVERTISEMENT / SPONSORED.
- forum: forum/kullanici yorumu URL desenleri veya source_name forum
  listesinde -> FORUM.
- otomatik fiyat tablosu: govde cogunlukla fiyat/oran satirlari (satir bazli
  oran esigi) + baslik sablonu -> AUTO_PRICE_TABLE (dedupe ve dogrulama
  kredisine katilmaz).
- Sonuc: birincil content_type + tum etiketler (tags) + tag_reasons
  (birden cok etiket olabilir; NEWS varsayilan).

Etiketli icerik eslestirmeye GIRER; etiket ayrica isaretlenir.
Deterministik; ag erisimi YOK.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from app.services.stock_scanning.news.fuzzy import normalize, tokenize
from app.services.stock_scanning.news.models import ContentType, NewsRecord

# Etiket neden kodlari
REASON_AD_KEYWORD = "AD_KEYWORD"
REASON_SPONSORED_KEYWORD = "SPONSORED_KEYWORD"
REASON_FORUM_URL = "FORUM_URL"
REASON_FORUM_SOURCE = "FORUM_SOURCE"
REASON_PRICE_ROW_RATIO = "PRICE_ROW_RATIO"
REASON_PRICE_TITLE_TEMPLATE = "PRICE_TITLE_TEMPLATE"

_AD_KEYWORDS = ("reklam", "advertorial", "tanitim yazisi", "tanitimdir", "ilan", "pr haber")
_SPONSORED_KEYWORDS = ("sponsorlu", "sponsorluk", "is birligi", "isbirligi", "sponsor")

_FORUM_URL_RE = re.compile(
    r"(forum|viewtopic|showthread|/konu/|/topic/|/threads/|/yorum/)", re.IGNORECASE
)

_DEFAULT_FORUM_SOURCES = (
    "donanimhaber",
    "donanim haber",
    "eksi sozluk",
    "eksisozluk",
    "inci sozluk",
    "incisozluk",
    "kizlarsoruyor",
    "sikayetvar",
    "forum",
)

# Fiyat/oran satiri: sembol benzeri token + sayi, ya da yuzde/TL iceren satir.
_PRICE_ROW_RE = re.compile(r"^[A-Za-z]{2,6}\s+[-+]?[\d.,]+")
_PERCENT_RE = re.compile(r"[-+]?\d+[.,]?\d*\s*(%|tl|try)")

_DEFAULT_PRICE_TITLES = (
    "gunluk fiyat tablosu",
    "fiyat tablosu",
    "kapanis fiyatlari",
    "gunluk kapanis",
    "seans kapanis",
    "piyasa ozeti tablosu",
    "hisse fiyatlari tablosu",
    "borsa gunluk",
    "gun sonu fiyat",
)

# Birincil tip onceligi: oto fiyat tablosu (dedupe disi) en ustte.
_PRIMARY_PRIORITY = (
    ContentType.AUTO_PRICE_TABLE,
    ContentType.ADVERTISEMENT,
    ContentType.SPONSORED,
    ContentType.FORUM,
    ContentType.NEWS,
)


@dataclass
class TaggerConfig:
    """Etiketleme esikleri ve listeleri (ayarlanabilir)."""

    price_row_ratio: float = 0.6
    ad_keywords: tuple = _AD_KEYWORDS
    sponsored_keywords: tuple = _SPONSORED_KEYWORDS
    forum_sources: tuple = _DEFAULT_FORUM_SOURCES
    price_title_templates: tuple = _DEFAULT_PRICE_TITLES


@dataclass
class TagResult:
    """Etiketleme ciktisi: birincil tip + tum etiketler + nedenler."""

    content_type: ContentType = ContentType.NEWS
    tags: List[ContentType] = field(default_factory=list)
    tag_reasons: List[str] = field(default_factory=list)


class ContentTagger:
    """Haber kaydini icerik tipine gore etiketler."""

    def __init__(self, config: Optional[TaggerConfig] = None):
        self.config = config or TaggerConfig()

    def tag(self, news: NewsRecord) -> TagResult:
        """Haberi etiketler; saf fonksiyon (kaydi degistirmez)."""
        tags: List[ContentType] = []
        reasons: List[str] = []
        title_norm = normalize(news.title)
        text_tokens = tokenize(f"{news.title or ''} {news.body or ''}")

        # -- reklam / sponsorlu (TAM TOKEN sinirli ifade aramasi) -------------
        ad_hit = next(
            (
                kw
                for kw in self.config.ad_keywords
                if self._contains_phrase(text_tokens, kw)
            ),
            None,
        )
        if ad_hit:
            tags.append(ContentType.ADVERTISEMENT)
            reasons.append(f"{REASON_AD_KEYWORD}:{ad_hit}")
        sp_hit = next(
            (
                kw
                for kw in self.config.sponsored_keywords
                if self._contains_phrase(text_tokens, kw)
            ),
            None,
        )
        if sp_hit:
            tags.append(ContentType.SPONSORED)
            reasons.append(f"{REASON_SPONSORED_KEYWORD}:{sp_hit}")

        # -- forum -----------------------------------------------------------
        if news.original_url and _FORUM_URL_RE.search(news.original_url):
            tags.append(ContentType.FORUM)
            reasons.append(REASON_FORUM_URL)
        source_norm = normalize(news.source_name)
        if source_norm and any(
            self._source_matches(source_norm, fs) for fs in self.config.forum_sources
        ):
            if ContentType.FORUM not in tags:
                tags.append(ContentType.FORUM)
            reasons.append(f"{REASON_FORUM_SOURCE}:{source_norm}")

        # -- otomatik fiyat tablosu ------------------------------------------
        lines = [ln.strip() for ln in (news.body or "").splitlines() if ln.strip()]
        if lines:
            price_rows = sum(1 for ln in lines if self._is_price_row(ln))
            row_ratio = price_rows / len(lines)
            title_hit = next(
                (tpl for tpl in self.config.price_title_templates if tpl in title_norm),
                None,
            )
            if row_ratio >= self.config.price_row_ratio and title_hit:
                tags.append(ContentType.AUTO_PRICE_TABLE)
                reasons.append(f"{REASON_PRICE_ROW_RATIO}:{row_ratio:.2f}")
                reasons.append(f"{REASON_PRICE_TITLE_TEMPLATE}:{title_hit}")

        if not tags:
            return TagResult(content_type=ContentType.NEWS, tags=[ContentType.NEWS], tag_reasons=[])
        primary = next(t for t in _PRIMARY_PRIORITY if t in tags)
        return TagResult(content_type=primary, tags=tags, tag_reasons=reasons)

    @staticmethod
    def _is_price_row(line: str) -> bool:
        """Satir fiyat/oran satiri mi? (sembol+sayi ya da yuzde/TL deseni)."""
        if _PRICE_ROW_RE.match(line):
            return True
        return len(_PERCENT_RE.findall(line)) >= 2

    @staticmethod
    def _contains_phrase(tokens: List[str], phrase: str) -> bool:
        """Anahtar ifadeyi TAM TOKEN sinirli arar (kelime-ici eslesme YOK)."""
        seq = tokenize(phrase)
        n = len(seq)
        if n == 0 or n > len(tokens):
            return False
        return any(tokens[i : i + n] == seq for i in range(len(tokens) - n + 1))

    @staticmethod
    def _source_matches(source_norm: str, forum_source: str) -> bool:
        """Kaynak adi forum listesiyle eslesir mi?

        Bosluksuz (compact) esitlik ya da token kumesi kapsamasi; rastgele
        alt-string eslesmesi YAPILMAZ ("y" != "sikayetvar").
        """
        fs_norm = normalize(forum_source)
        if not fs_norm:
            return False
        compact_source = source_norm.replace(" ", "")
        compact_fs = fs_norm.replace(" ", "")
        if compact_source == compact_fs:
            return True
        return set(fs_norm.split()) <= set(source_norm.split())
