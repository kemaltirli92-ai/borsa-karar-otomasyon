"""BLOK 12 - stdlib fuzzy motor (fuzzy.py).

RapidFuzz KURULMAZ. Tum benzerlik olcumleri stdlib difflib.SequenceMatcher
tabanlidir (SPEC bolum 5):

- normalize(text): Turkce karakter katlama + kucuk harf + noktalama ayik
  (BLOK 6 normalize ile uyumlu karakter haritasi).
- tokenize(text): normalize edilmis metni token listesine ayirir.
- token_set_ratio(a, b): sirali ortak token kumeleri uzerinden 0-100 skor
  (fuzzywuzzy/RapidFuzz token_set_ratio muadili, saf stdlib).
- partial_ratio(a, b): kisa metnin uzun metin icindeki en iyi pencere skoru.
- best_match(query, candidates): en yuksek skorlu aday (esitlikte ilk aday).

Deterministik: ayni girdi -> ayni skor. Ag erisimi YOK.
"""
from __future__ import annotations

import difflib
import re
from typing import Callable, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Turkce karakter normalizasyonu (BLOK 6 ile uyumlu harita; kucuk harf cikti)
# ---------------------------------------------------------------------------
_TR_FOLD = str.maketrans(
    {
        "İ": "i",
        "I": "i",
        "ı": "i",
        "Ş": "s",
        "ş": "s",
        "Ç": "c",
        "ç": "c",
        "Ğ": "g",
        "ğ": "g",
        "Ö": "o",
        "ö": "o",
        "Ü": "u",
        "ü": "u",
    }
)

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

# Eslestirme/olay anahtari cikarirken elenen genel gecer kelimeler.
STOPWORDS = frozenset(
    {
        "ve", "ile", "veya", "icin", "olan", "olarak", "gore", "sonra",
        "once", "bugun", "dun", "yarin", "daha", "cok", "az", "ancak",
        "fakat", "ama", "bir", "bu", "su", "da", "de", "ki", "mi", "mu",
        "ise", "kadar", "gibi", "uzerine", "altinda", "uzerinde",
        "borsa", "hisse", "hissesi", "hisseleri", "hisseler", "fiyat",
        "fiyati", "fiyatlari", "piyasa", "piyasasi", "kapanis", "acilis",
        "endeks", "bist", "bist100", "yatirim", "yatirimci", "haber",
        "haberi", "haberler", "ajans", "ajansi", "ekonomi", "finans",
        "gundem", "basin", "aciklama", "aciklamasi", "bildirdi",
        "belirtti", "soyledi", "dedi", "gore", "edildi", "oldu",
        "turkiye", "istanbul",
    }
)


def normalize(text: Optional[str]) -> str:
    """Turkce karakter katlama + kucuk harf + noktalama ayik.

    Ornek: "Türkiye İş Bankası A.Ş." -> "turkiye is bankasi a s"
    """
    if text is None:
        return ""
    folded = str(text).strip().translate(_TR_FOLD).lower()
    return _NON_ALNUM_RE.sub(" ", folded).strip()


def tokenize(text: Optional[str]) -> List[str]:
    """Normalize edilmis metni token listesine ayirir."""
    norm = normalize(text)
    return norm.split() if norm else []


def significant_tokens(text: Optional[str], min_len: int = 4) -> List[str]:
    """Olay anahtari icin anlamli tokenlar (stopword ve kisa kelimeler elenir)."""
    return sorted(
        {tok for tok in tokenize(text) if len(tok) >= min_len and tok not in STOPWORDS}
    )


def _seq_ratio(a: str, b: str) -> float:
    """difflib tabanli ham benzerlik (0.0-1.0)."""
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def ratio(a: Optional[str], b: Optional[str]) -> int:
    """Normalize edilmis ham string benzerligi (0-100)."""
    return round(100 * _seq_ratio(normalize(a), normalize(b)))


def token_set_ratio(a: Optional[str], b: Optional[str]) -> int:
    """Token kumesi benzerligi (0-100), difflib tabanli.

    Algoritma (fuzzywuzzy token_set_ratio muadili):
    ortak tokenlar sirali birlesik string; her iki taraftaki fark tokenlari
    ortak kume ile birlestirilip karsilastirilir; en yuksek skor alinir.
    """
    tokens_a = set(tokenize(a))
    tokens_b = set(tokenize(b))
    if not tokens_a or not tokens_b:
        return 0
    inter = tokens_a & tokens_b
    if not inter:
        return 0
    inter_s = " ".join(sorted(inter))
    diff_a = " ".join(sorted(tokens_a - tokens_b))
    diff_b = " ".join(sorted(tokens_b - tokens_a))
    combined_a = (inter_s + " " + diff_a).strip()
    combined_b = (inter_s + " " + diff_b).strip()
    return round(
        100
        * max(
            _seq_ratio(inter_s, combined_a),
            _seq_ratio(inter_s, combined_b),
            _seq_ratio(combined_a, combined_b),
        )
    )


def partial_ratio(a: Optional[str], b: Optional[str]) -> int:
    """Kisa metnin uzun metin icindeki en iyi hizalanma skoru (0-100)."""
    a_n = normalize(a)
    b_n = normalize(b)
    if not a_n or not b_n:
        return 0
    shorter, longer = (a_n, b_n) if len(a_n) <= len(b_n) else (b_n, a_n)
    matcher = difflib.SequenceMatcher(None, shorter, longer)
    best = 0.0
    for block in matcher.get_matching_blocks():
        if block.size == 0:
            continue
        long_start = max(block.b - block.a, 0)
        long_end = long_start + len(shorter)
        window = longer[long_start:long_end]
        score = _seq_ratio(shorter, window)
        if score >= 0.995:
            return 100
        best = max(best, score)
    return round(100 * best)


def best_match(
    query: Optional[str],
    candidates: Sequence[str],
    scorer: Optional[Callable[[Optional[str], Optional[str]], int]] = None,
) -> Tuple[Optional[str], int]:
    """En yuksek skorlu adayi dondurur.

    Esit skorda listede once gelen aday kazanir (deterministik).
    Bos aday listesinde (None, 0) doner.
    """
    score_fn = scorer or token_set_ratio
    best_text: Optional[str] = None
    best_score = -1
    for cand in candidates:
        sc = score_fn(query, cand)
        if sc > best_score:
            best_text, best_score = cand, sc
    if best_text is None:
        return None, 0
    return best_text, best_score
