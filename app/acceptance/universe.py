"""BLOK 22 - Resmi XK100 evren defteri (universe.py).

UniverseBook resmi XK100 uyelik defteridir:

- Resmi liste bu modulde URETILMEZ; her zaman ENJEKTE provider'dan
  (load_official cagiran taraf) gelir. Sahte evren listesi YOKTUR.
- Uyelik araliklari yarim aciktir: [entered, exited). exited=None -> hala
  aktif uye. Bir sirket ciktiginda kayit SILINMEZ; araligin exited alani
  kapanir ve tarihsel uyelik korunur (is_member ile gecmis gun sorgusu).
- Giris (enter): yeni sirket girisi (+ halka arz). Sirket BLOK 6
  SymbolIdentityService'te yoksa register_stock + add_symbol("bist") ile
  acilir; uyelik araligi baslatilir. Zaten aktif uyeyse no-op (idempotent).
- Cikis (exit): acik araligi kapatir; kayit korunur. Tekrar giris yeni
  aralik acar (aralik zinciri history() ile okunur).
- validate_count(day, expected=100): o gun aktif uye sayisini dogrular;
  extra/missing son load_official'daki resmi listeye gore raporlanir.

Deterministik: clock enjekte edilebilir (default parametre olarak enjekte
clock referansi; modul icinde dogrudan datetime.now() cagrisi YOKTUR).
Gercek ag YOK; stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Dict, List, Optional

from app.services.stock_scanning.symbol_identity import SymbolIdentityService

EXPECTED_UNIVERSE_SIZE = 100


@dataclass(frozen=True)
class MembershipInterval:
    """Tek uyelik araligi: [entered, exited) — exited None ise hala aktif."""

    symbol: str
    entered: str  # ISO gun (YYYY-MM-DD)
    exited: Optional[str]  # ISO gun veya None


def _day(value) -> str:
    """date/datetime/ISO string girdiyi ISO gun stringine cevirir."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    return date.fromisoformat(text[:10]).isoformat()


def _norm_symbol(symbol: str) -> str:
    text = str(symbol).strip().upper()
    if not text:
        raise ValueError("symbol bos olamaz")
    return text


class UniverseBook:
    """Resmi XK100 uyelik defteri (liste ENJEKTE provider'dan gelir)."""

    def __init__(
        self,
        identity: SymbolIdentityService,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self._identity = identity
        # default parametre olarak enjekte clock referansi (cagri govdede YOK)
        self._clock: Callable[[], datetime] = clock or datetime.now
        self._intervals: Dict[str, List[MembershipInterval]] = {}
        self._official: List[str] = []  # son load_official'daki resmi liste

    # ------------------------------------------------------------------ #
    # Kimlik yardimcisi: sembol -> stock_id (yoksa kaydet)
    # ------------------------------------------------------------------ #
    def _ensure_identity(self, symbol: str, company_name: Optional[str]) -> str:
        res = self._identity.resolve(symbol, platform="bist")
        if res is not None:
            return res.stock_id
        name = (company_name or symbol).strip()
        stock_id = self._identity.register_stock(name)
        self._identity.add_symbol(stock_id, "bist", symbol)
        return stock_id

    def _open_interval(self, symbol: str) -> Optional[MembershipInterval]:
        for interval in self._intervals.get(symbol, []):
            if interval.exited is None:
                return interval
        return None

    # ------------------------------------------------------------------ #
    # Resmi liste yukleme (ilk yukleme / gunluk senkron)
    # ------------------------------------------------------------------ #
    def load_official(self, symbols: List[str], day: str) -> None:
        """Resmi listeyi ENJEKTE provider'dan yukler.

        - Her sembol icin identity'de kayit yoksa register_stock+add_symbol.
        - Acik uyelik araligi yoksa o gunden baslayan aralik acilir.
        - Bu metod listede OLMAYAN sirketleri CIKARMAZ (cikis yalnizca
          exit() ile, acik kayitla yapilir; sessiz dusme YOK).
        """
        d = _day(day)
        official: List[str] = []
        for raw in symbols:
            symbol = _norm_symbol(raw)
            self._ensure_identity(symbol, None)
            if self._open_interval(symbol) is None:
                self._intervals.setdefault(symbol, []).append(
                    MembershipInterval(symbol=symbol, entered=d, exited=None)
                )
            if symbol not in official:
                official.append(symbol)
        self._official = official

    # ------------------------------------------------------------------ #
    # Uyelik sorgulari (tarihsel)
    # ------------------------------------------------------------------ #
    def is_member(self, symbol: str, day: str) -> bool:
        """O gun sirket evrenin aktif uyesi miydi? (tarihsel sorgu)"""
        symbol = _norm_symbol(symbol)
        d = _day(day)
        for interval in self._intervals.get(symbol, []):
            if interval.entered <= d and (
                interval.exited is None or d < interval.exited
            ):
                return True
        return False

    def active_symbols(self, day: str) -> List[str]:
        """O gun aktif uyeler (tarihsel uyelik; alfabetik, deterministik)."""
        return sorted(
            symbol
            for symbol in self._intervals
            if self.is_member(symbol, day)
        )

    def active_count(self, day: str) -> int:
        return len(self.active_symbols(day))

    def validate_count(self, day: str, expected: int = EXPECTED_UNIVERSE_SIZE) -> dict:
        """O gun aktif uye sayisini beklenen degerle karsilastirir.

        extra   : aktif ama son resmi listede olmayan semboller.
        missing : son resmi listede olup o gun aktif olmayan semboller.
        """
        d = _day(day)
        active = set(self.active_symbols(d))
        official = set(self._official)
        actual = len(active)
        return {
            "day": d,
            "expected": int(expected),
            "actual": actual,
            "ok": actual == int(expected),
            "extra": sorted(active - official),
            "missing": sorted(official - active),
        }

    # ------------------------------------------------------------------ #
    # Giris / cikis
    # ------------------------------------------------------------------ #
    def enter(self, symbol: str, company_name: str, day: str) -> None:
        """Yeni sirket girisi (+ halka arz). Zaten aktifse no-op."""
        symbol = _norm_symbol(symbol)
        d = _day(day)
        self._ensure_identity(symbol, company_name)
        if self._open_interval(symbol) is not None:
            return  # idempotent: zaten aktif uye
        self._intervals.setdefault(symbol, []).append(
            MembershipInterval(symbol=symbol, entered=d, exited=None)
        )

    def exit(self, symbol: str, day: str) -> None:
        """Sirket cikisi: acik araligi kapatir. Kayit SILINMEZ (tarihsel)."""
        symbol = _norm_symbol(symbol)
        d = _day(day)
        current = self._open_interval(symbol)
        if current is None:
            raise ValueError(f"Aktif uyelik yok (cikis yapilamaz): {symbol}")
        if d < current.entered:
            raise ValueError(
                f"Cikis gunu ({d}) giris gununden ({current.entered}) once olamaz"
            )
        intervals = self._intervals[symbol]
        intervals[intervals.index(current)] = MembershipInterval(
            symbol=symbol, entered=current.entered, exited=d
        )

    def history(self, symbol: str) -> List[MembershipInterval]:
        """Sembolun tum uyelik araliklari (giris sirasi; kayitlar korunur)."""
        return list(self._intervals.get(_norm_symbol(symbol), []))
