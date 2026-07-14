"""BLOK 11 - Bildirim -> aktif XK100 sirketi eslestirme (matcher.py).

KapMatcher(identity_service, universe_provider):
- BLOK 6 kimlik servisi ENJEKTE edilir (resolve). Platform "kap".
- universe_provider: aktif XK100 stock_id listesini veren callable veya
  stock_ids/active_stock_ids nitelikli nesne.
- Evren disi sirket -> eslesme yok (OUT_OF_UNIVERSE, kayit yapilmaz).
- YANLIS SIRKET ESLESMESI ENGELI: belirsiz/iki aday -> eslesme YAPILMAZ;
  MATCH_AMBIGUOUS + SYMBOL_VERIFICATION_PENDING (BLOK 6 kuyrugu). Bildirim
  yanlis hisseye ASLA baglanmaz.
- Eslestirilemeyen bildirim UNMATCHED sayacina duser (sessizce hisseye
  baglanmaz).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

# Eslestirme durumlari
MATCHED = "MATCHED"
OUT_OF_UNIVERSE = "OUT_OF_UNIVERSE"
MATCH_AMBIGUOUS = "MATCH_AMBIGUOUS"
UNMATCHED = "UNMATCHED"

# Belirsizlik kuyruk kodu (BLOK 6 kuyruguyla ayni isim)
SYMBOL_VERIFICATION_PENDING = "SYMBOL_VERIFICATION_PENDING"

# BLOK 6 platform adi
KAP_PLATFORM = "kap"


@dataclass
class MatchOutcome:
    """Tek bildirim icin eslestirme sonucu."""

    status: str  # MATCHED | OUT_OF_UNIVERSE | MATCH_AMBIGUOUS | UNMATCHED
    stock_id: Optional[str] = None
    symbol: Optional[str] = None
    query: Optional[str] = None
    notification_id: Optional[str] = None
    code: Optional[str] = None  # OUT_OF_UNIVERSE | SYMBOL_VERIFICATION_PENDING | UNMATCHED
    pending: bool = False


class KapMatcher:
    """KAP bildirimini aktif XK100 hissesine guvenli sekilde baglar."""

    def __init__(self, identity_service, universe_provider):
        self.identity_service = identity_service
        self.universe_provider = universe_provider
        self.outcomes: List[MatchOutcome] = []
        self.counters = {
            MATCHED: 0,
            OUT_OF_UNIVERSE: 0,
            MATCH_AMBIGUOUS: 0,
            UNMATCHED: 0,
        }
        # Belirsiz eslesmeler icin yerel bekleyen kuyruk izi
        self.pending_items: List[dict] = []

    # ------------------------------------------------------------------ #
    def _universe_ids(self) -> set:
        """Aktif XK100 stock_id kumesi (universe_provider duck-typing)."""
        provider = self.universe_provider
        if provider is None:
            return set()
        if callable(provider):
            return {str(s) for s in (provider() or [])}
        for attr in ("stock_ids", "active_stock_ids"):
            value = getattr(provider, attr, None)
            if value is None:
                continue
            value = value() if callable(value) else value
            return {str(s) for s in value}
        return set()

    def _pending_count(self) -> int:
        """BLOK 6 dogrulama kuyrugu uzunlugu (varsa); belirsizlik tespiti icin."""
        getter = getattr(self.identity_service, "get_pending_queue", None)
        if getter is None:
            return 0
        try:
            return len(getter())
        except Exception:
            return 0

    def _resolve(self, query: str):
        """BLOK 6 resolve cagrisi (platform='kap'; dar imzali mock'lar icin geri dusus)."""
        resolver = getattr(self.identity_service, "resolve", None)
        if resolver is None:
            return None
        try:
            return resolver(query, platform=KAP_PLATFORM)
        except TypeError:
            return resolver(query)

    @staticmethod
    def _extract_stock_id(result) -> Optional[str]:
        if result is None:
            return None
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            sid = result.get("stock_id")
            return str(sid) if sid else None
        sid = getattr(result, "stock_id", None)
        return str(sid) if sid else None

    # ------------------------------------------------------------------ #
    def match(self, item: dict) -> MatchOutcome:
        """Bildirim kaydini aktif XK100 hissesiyle eslestirir.

        item beklenen anahtarlar: notification_id, symbol, company_name.
        Belirsiz durumda ESLESME YAPILMAZ (yanlis hisseye baglanti yok).
        """
        nid = item.get("notification_id")
        symbol = item.get("symbol")
        company = item.get("company_name")
        query = symbol or company

        outcome = MatchOutcome(
            status=UNMATCHED, symbol=symbol, query=query, notification_id=nid
        )

        result = None
        if query:
            before = self._pending_count()
            result = self._resolve(str(query))
            stock_id = self._extract_stock_id(result)
            if stock_id is not None:
                if stock_id not in self._universe_ids():
                    outcome.status = OUT_OF_UNIVERSE
                    outcome.code = OUT_OF_UNIVERSE
                    outcome.stock_id = None  # evren disina kayit/baglanti yapilmaz
                else:
                    outcome.status = MATCHED
                    outcome.stock_id = stock_id
                    outcome.code = MATCHED
                self._record(outcome)
                return outcome
            # resolve None: belirsiz mi, hic yok mu?
            after = self._pending_count()
            ambiguous = after > before or bool(
                getattr(self.identity_service, "last_resolve_ambiguous", False)
            )
            if ambiguous:
                outcome.status = MATCH_AMBIGUOUS
                outcome.code = SYMBOL_VERIFICATION_PENDING
                outcome.pending = True
                self.pending_items.append(
                    {
                        "notification_id": nid,
                        "query": query,
                        "reason": SYMBOL_VERIFICATION_PENDING,
                    }
                )
                self._record(outcome)
                return outcome

        outcome.status = UNMATCHED
        outcome.code = UNMATCHED
        self._record(outcome)
        return outcome

    def _record(self, outcome: MatchOutcome) -> None:
        self.outcomes.append(outcome)
        self.counters[outcome.status] = self.counters.get(outcome.status, 0) + 1

    @property
    def unmatched_count(self) -> int:
        return self.counters.get(UNMATCHED, 0)

    @property
    def ambiguous_count(self) -> int:
        return self.counters.get(MATCH_AMBIGUOUS, 0)

    @property
    def out_of_universe_count(self) -> int:
        return self.counters.get(OUT_OF_UNIVERSE, 0)
