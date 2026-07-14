"""BLOK 12 - Alias deposu (aliases.py).

AliasStore her stock_id icin eslestirme varlik kumesini tutar (SPEC bolum 4):
code, full_name, short_name, old_names[], old_codes[], brand_names[],
subsidiaries[] (bagli ortaklik), affiliates[] (onemli istirak),
executives[] (ops.).

Veri kaynaklari (enjeksiyon):
- identity_service: BLOK 6 SymbolIdentityService (veya uyumlu stub).
  Aktif sembol -> code; kapanmis semboller -> old_codes; sirket adi ->
  full_name. BLOK 6 dosyalarina DOKUNULMAZ; arayuz duck-typing ile okunur.
- extra: {stock_id: {alan: deger}} panel eklentileri (brand_names vb.).

Tum varliklar normalize edilir (Turkce karakter, kucuk harf, noktalama
ayik — fuzzy.normalize, BLOK 6 normalize ile uyumlu).

AMBIGUOUS_ALIAS: ayni normalize alias metni birden cok stock_id'ye
bagliysa isaretlenir; bu alias uzerinden otomatik teyit YAPILMAZ.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from app.services.stock_scanning.news.fuzzy import normalize
from app.services.stock_scanning.news.models import MatchMethod

AMBIGUOUS_ALIAS = "AMBIGUOUS_ALIAS"

# Varlik alani -> MatchMethod eslemesi.
_FIELD_TO_METHOD = {
    "code": MatchMethod.CODE,
    "full_name": MatchMethod.FULL_NAME,
    "short_name": MatchMethod.SHORT_NAME,
    "old_names": MatchMethod.OLD_NAME,
    "old_codes": MatchMethod.OLD_CODE,
    "brand_names": MatchMethod.BRAND,
    "subsidiaries": MatchMethod.SUBSIDIARY,
    "affiliates": MatchMethod.AFFILIATE,
    "executives": MatchMethod.EXECUTIVE,
}

_LIST_FIELDS = (
    "old_names",
    "old_codes",
    "brand_names",
    "subsidiaries",
    "affiliates",
    "executives",
)


@dataclass
class StockAliasProfile:
    """Bir hissenin haber eslestirme varlik profili."""

    stock_id: str
    code: Optional[str] = None
    full_name: Optional[str] = None
    short_name: Optional[str] = None
    old_names: List[str] = field(default_factory=list)
    old_codes: List[str] = field(default_factory=list)
    brand_names: List[str] = field(default_factory=list)
    subsidiaries: List[str] = field(default_factory=list)
    affiliates: List[str] = field(default_factory=list)
    executives: List[str] = field(default_factory=list)


class AliasStore:
    """Hisse basina alias/varlik deposu + belirsiz alias indeksi."""

    def __init__(self, identity_service=None, extra: Optional[Dict[str, dict]] = None):
        self._profiles: Dict[str, StockAliasProfile] = {}
        if identity_service is not None:
            self._load_from_identity(identity_service)
        if extra:
            for stock_id, patch in extra.items():
                self._apply_extra(stock_id, patch)
        self._rebuild_index()

    # -- BLOK 6 yukleme (duck-typing; BLOK 6'ya dokunulmaz) -----------------
    @staticmethod
    def _iter_identity_stocks(identity_service):
        """BLOK 6 servisinden hisse kayitlarini okur (public varsa public)."""
        if hasattr(identity_service, "iter_stocks"):
            return list(identity_service.iter_stocks())
        if hasattr(identity_service, "list_stocks"):
            return list(identity_service.list_stocks())
        stocks = getattr(identity_service, "_stocks", None)
        if isinstance(stocks, dict):
            return list(stocks.values())
        return []

    def _load_from_identity(self, identity_service) -> None:
        """BLOK 6 kayitlarindan code/full_name/old_codes ceker."""
        for stock in self._iter_identity_stocks(identity_service):
            stock_id = getattr(stock, "stock_id", None)
            if not stock_id:
                continue
            profile = self._profiles.get(stock_id) or StockAliasProfile(stock_id=stock_id)
            company_name = getattr(stock, "company_name", None)
            if company_name and not profile.full_name:
                profile.full_name = company_name
            history_fn = getattr(identity_service, "get_symbol_history", None)
            if history_fn is not None:
                try:
                    records = history_fn(stock_id)
                except Exception:
                    records = []
                active: List[str] = []
                closed: List[str] = []
                for rec in records:
                    symbol = getattr(rec, "symbol", None)
                    if not symbol:
                        continue
                    if getattr(rec, "is_active", False):
                        active.append(symbol)
                    else:
                        closed.append(symbol)
                if active and not profile.code:
                    profile.code = active[0]
                for sym in closed:
                    if sym not in profile.old_codes:
                        profile.old_codes.append(sym)
            self._profiles[stock_id] = profile

    def _apply_extra(self, stock_id: str, patch: dict) -> None:
        """Panel eklentisi: {alan: deger} sozlugunu profile uygular."""
        profile = self._profiles.get(stock_id) or StockAliasProfile(stock_id=stock_id)
        for key, value in patch.items():
            if key in _LIST_FIELDS:
                target = getattr(profile, key)
                values = value if isinstance(value, (list, tuple)) else [value]
                for item in values:
                    if item and item not in target:
                        target.append(item)
            elif key in ("code", "full_name", "short_name"):
                if value:
                    setattr(profile, key, value)
        self._profiles[stock_id] = profile

    # -- kayit API'si --------------------------------------------------------
    def register(
        self,
        stock_id: str,
        code: Optional[str] = None,
        full_name: Optional[str] = None,
        short_name: Optional[str] = None,
        old_names: Optional[List[str]] = None,
        old_codes: Optional[List[str]] = None,
        brand_names: Optional[List[str]] = None,
        subsidiaries: Optional[List[str]] = None,
        affiliates: Optional[List[str]] = None,
        executives: Optional[List[str]] = None,
    ) -> StockAliasProfile:
        """Profil kaydeder/gunceller ve belirsizlik indeksini yeniler."""
        profile = self._profiles.get(stock_id) or StockAliasProfile(stock_id=stock_id)
        if code:
            profile.code = code
        if full_name:
            profile.full_name = full_name
        if short_name:
            profile.short_name = short_name
        for field_name, values in (
            ("old_names", old_names),
            ("old_codes", old_codes),
            ("brand_names", brand_names),
            ("subsidiaries", subsidiaries),
            ("affiliates", affiliates),
            ("executives", executives),
        ):
            if values:
                target = getattr(profile, field_name)
                for item in values:
                    if item and item not in target:
                        target.append(item)
        self._profiles[stock_id] = profile
        self._rebuild_index()
        return profile

    # -- belirsiz alias indeksi ----------------------------------------------
    def _rebuild_index(self) -> None:
        """normalize alias -> stock_id kumesi indeksi (tum varlik tipleri)."""
        index: Dict[str, set] = {}
        for stock_id, profile in self._profiles.items():
            for method, pairs in self._profile_pairs(profile).items():
                for _orig, norm in pairs:
                    if norm:
                        index.setdefault(norm, set()).add(stock_id)
        self._index = index

    @staticmethod
    def _profile_pairs(
        profile: StockAliasProfile,
    ) -> Dict[MatchMethod, List[Tuple[str, str]]]:
        """Profili (orijinal, normalize) ciftlerine cevirir."""
        pairs: Dict[MatchMethod, List[Tuple[str, str]]] = {}
        for field_name, method in _FIELD_TO_METHOD.items():
            value = getattr(profile, field_name)
            values = value if isinstance(value, list) else ([value] if value else [])
            method_pairs = []
            for item in values:
                if item is None:
                    continue
                text = str(item).strip()
                if text:
                    method_pairs.append((text, normalize(text)))
            if method_pairs:
                pairs[method] = method_pairs
        return pairs

    # -- sorgu API'si --------------------------------------------------------
    def stock_ids(self) -> List[str]:
        """Kayitli hisseler (deterministik sira)."""
        return sorted(self._profiles.keys())

    def get_profile(self, stock_id: str) -> Optional[StockAliasProfile]:
        return self._profiles.get(stock_id)

    def entities(self, stock_id: str) -> Dict[MatchMethod, List[str]]:
        """stock_id icin varlik kumesi: {MatchMethod: [orijinal metinler]}."""
        profile = self._profiles.get(stock_id)
        if profile is None:
            return {}
        pairs = self._profile_pairs(profile)
        return {method: [orig for orig, _ in p] for method, p in pairs.items()}

    def entity_pairs(self, stock_id: str) -> Dict[MatchMethod, List[Tuple[str, str]]]:
        """Eslestirme icin (orijinal, normalize) ciftleri."""
        profile = self._profiles.get(stock_id)
        if profile is None:
            return {}
        return self._profile_pairs(profile)

    def alias_stock_ids(self, alias_text: str) -> List[str]:
        """Bir alias metnine bagli hisseler (normalize karsilastirma)."""
        norm = normalize(alias_text)
        return sorted(self._index.get(norm, set()))

    def is_ambiguous(self, alias_text: str) -> bool:
        """Alias birden cok hisseye bagliysa True (AMBIGUOUS_ALIAS)."""
        return len(self.alias_stock_ids(alias_text)) > 1

    def ambiguous_aliases(self) -> Dict[str, List[str]]:
        """Tum belirsiz aliaslar: {normalize alias: [stock_id, ...]}."""
        return {
            alias: sorted(owners)
            for alias, owners in sorted(self._index.items())
            if len(owners) > 1
        }
