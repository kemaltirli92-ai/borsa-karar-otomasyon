"""BLOK 9 - 13 dogrulama kurali + durum katmanlari (rules.py).

SPEC BLOK 9 bolum 3-4. Her kural ayri bir fonksiyondur ve makine okunur
bir kural kodu tasiyan RuleResult dondurur.

Kural kodlari:
    OPEN_NOT_POSITIVE, HIGH_NOT_POSITIVE, LOW_NOT_POSITIVE,
    CLOSE_NOT_POSITIVE, NEGATIVE_VOLUME, HIGH_LT_PRICE, LOW_GT_PRICE,
    NON_TRADING_DAY, DUPLICATE_DATE, CURRENCY_MISMATCH,
    SYMBOL_OWNER_MISMATCH, UNEXPLAINED_OUTLIER, CORPORATE_NOT_CHECKED
Ek (zorunlu VALIDATED adimi): SOURCE_DIVERGENCE_REVIEW (source_cross_check).

Severity -> katman eslemesi (SPEC bolum 3-4):
    FATAL -> REJECTED (kati ihlal: fiyat<=0, high<low, yanlis para birimi,
             yanlis sembol-sirket, tekrarlanan tarih, islem gunu degil)
    WARN  -> REVIEW_REQUIRED (supheli: aciklanamayan outlier, kaynak
             uyusmazligi tolerans disi)
    INFO  -> durumu etkilemez (kontrol yapilmadi / bilgilendirme)

Durum katmanlari (LayerStatus): RAW, CLEAN, VALIDATED, REJECTED,
REVIEW_REQUIRED.

Bar erisimi duck-typing iledir: open/high/low/close/volume/currency/
trade_date/stock_id/source nitelikleri olan her nesne kabul edilir
(BLOK 8 PriceBar dahil; import zorunlu degildir).

Dis bagimlilik yoktur (stdlib). Saat takvim uzerinden enjekte edilir.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable, List, Optional, Sequence, Set, Tuple

from .calendar import FUTURE_DATE, TradingCalendar

# --------------------------------------------------------------------------- #
# Kural kodlari
# --------------------------------------------------------------------------- #
OPEN_NOT_POSITIVE = "OPEN_NOT_POSITIVE"
HIGH_NOT_POSITIVE = "HIGH_NOT_POSITIVE"
LOW_NOT_POSITIVE = "LOW_NOT_POSITIVE"
CLOSE_NOT_POSITIVE = "CLOSE_NOT_POSITIVE"
NEGATIVE_VOLUME = "NEGATIVE_VOLUME"
HIGH_LT_PRICE = "HIGH_LT_PRICE"
LOW_GT_PRICE = "LOW_GT_PRICE"
NON_TRADING_DAY = "NON_TRADING_DAY"
DUPLICATE_DATE = "DUPLICATE_DATE"
CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
SYMBOL_OWNER_MISMATCH = "SYMBOL_OWNER_MISMATCH"
UNEXPLAINED_OUTLIER = "UNEXPLAINED_OUTLIER"
CORPORATE_NOT_CHECKED = "CORPORATE_NOT_CHECKED"
SOURCE_DIVERGENCE_REVIEW = "SOURCE_DIVERGENCE_REVIEW"

ALL_RULE_CODES = (
    OPEN_NOT_POSITIVE,
    HIGH_NOT_POSITIVE,
    LOW_NOT_POSITIVE,
    CLOSE_NOT_POSITIVE,
    NEGATIVE_VOLUME,
    HIGH_LT_PRICE,
    LOW_GT_PRICE,
    NON_TRADING_DAY,
    DUPLICATE_DATE,
    CURRENCY_MISMATCH,
    SYMBOL_OWNER_MISMATCH,
    UNEXPLAINED_OUTLIER,
    CORPORATE_NOT_CHECKED,
)

# --------------------------------------------------------------------------- #
# Severity
# --------------------------------------------------------------------------- #
FATAL = "FATAL"
WARN = "WARN"
INFO = "INFO"

DEFAULT_ALLOWED_CURRENCIES = frozenset({"TRY"})
DEFAULT_OUTLIER_THRESHOLD_PCT = 20.0
DEFAULT_SOURCE_TOLERANCE_PCT = 0.5


class LayerStatus(Enum):
    """Veri katmani durumlari (SPEC bolum 3)."""

    RAW = "RAW"
    CLEAN = "CLEAN"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


@dataclass
class RuleResult:
    """Tek bir kuralin sonucu: makine kodu + basari + agirlik."""

    code: str
    ok: bool
    severity: str = INFO


@dataclass
class BarContext:
    """evaluate_bar icin enjekte baglam (takvim, servisler, esikler)."""

    calendar: Optional[Any] = None
    allowed_currencies: Optional[Set[str]] = None
    identity_service: Optional[Any] = None
    corporate_lookup: Optional[Callable] = None
    prev_close: Optional[float] = None
    outlier_threshold_pct: float = DEFAULT_OUTLIER_THRESHOLD_PCT
    outlier_explanation: Optional[str] = None
    reference_close: Optional[float] = None
    source_tolerance_pct: float = DEFAULT_SOURCE_TOLERANCE_PCT
    seen_keys: Optional[Set[Tuple[str, str]]] = None


# --------------------------------------------------------------------------- #
# Yardimcilar (duck-typing erisim + sayi kontrolleri)
# --------------------------------------------------------------------------- #
def _get(bar, name, default=None):
    return getattr(bar, name, default)


def _is_number(value) -> bool:
    if isinstance(value, bool):
        return False
    return isinstance(value, (int, float))


def _is_positive(value) -> bool:
    return _is_number(value) and value > 0


def _fatal(code: str, ok: bool) -> RuleResult:
    return RuleResult(code=code, ok=ok, severity=FATAL)


def _info(code: str, ok: bool) -> RuleResult:
    return RuleResult(code=code, ok=ok, severity=INFO)


# --------------------------------------------------------------------------- #
# Kural 1-4: fiyat pozitifligi (FATAL)
# --------------------------------------------------------------------------- #
def open_positive(bar) -> RuleResult:
    """Kural 1: Open > 0 (OPEN_NOT_POSITIVE)."""
    return _fatal(OPEN_NOT_POSITIVE, _is_positive(_get(bar, "open")))


def high_positive(bar) -> RuleResult:
    """Kural 2: High > 0 (HIGH_NOT_POSITIVE)."""
    return _fatal(HIGH_NOT_POSITIVE, _is_positive(_get(bar, "high")))


def low_positive(bar) -> RuleResult:
    """Kural 3: Low > 0 (LOW_NOT_POSITIVE)."""
    return _fatal(LOW_NOT_POSITIVE, _is_positive(_get(bar, "low")))


def close_positive(bar) -> RuleResult:
    """Kural 4: Close > 0 (CLOSE_NOT_POSITIVE)."""
    return _fatal(CLOSE_NOT_POSITIVE, _is_positive(_get(bar, "close")))


# --------------------------------------------------------------------------- #
# Kural 5: hacim (FATAL)
# --------------------------------------------------------------------------- #
def volume_non_negative(bar) -> RuleResult:
    """Kural 5: Volume >= 0 (NEGATIVE_VOLUME)."""
    v = _get(bar, "volume")
    ok = _is_number(v) and v >= 0
    return _fatal(NEGATIVE_VOLUME, ok)


# --------------------------------------------------------------------------- #
# Kural 6-7: high/low kapsama (FATAL)
# --------------------------------------------------------------------------- #
def high_covers_all(bar) -> RuleResult:
    """Kural 6: High >= Open, High >= Low, High >= Close (HIGH_LT_PRICE).

    Fiyatlardan herhangi biri sayisal degilse kapsama kontrolu atlanir
    (pozitiflik kurallari ihlali zaten yakalar) -> INFO ok.
    """
    o, h, l, c = (_get(bar, f) for f in ("open", "high", "low", "close"))
    if not all(_is_number(v) for v in (o, h, l, c)):
        return _info(HIGH_LT_PRICE, True)
    ok = h >= o and h >= l and h >= c
    return _fatal(HIGH_LT_PRICE, ok)


def low_below_all(bar) -> RuleResult:
    """Kural 7: Low <= Open, Low <= High, Low <= Close (LOW_GT_PRICE)."""
    o, h, l, c = (_get(bar, f) for f in ("open", "high", "low", "close"))
    if not all(_is_number(v) for v in (o, h, l, c)):
        return _info(LOW_GT_PRICE, True)
    ok = l <= o and l <= h and l <= c
    return _fatal(LOW_GT_PRICE, ok)


# --------------------------------------------------------------------------- #
# Kural 8: islem gunu (FATAL)
# --------------------------------------------------------------------------- #
def valid_trading_day(bar, calendar=None) -> RuleResult:
    """Kural 8: tarih gecerli islem gunu (NON_TRADING_DAY / FUTURE_DATE).

    calendar None ise kontrol atlanir (INFO ok). Takvim duck-typing:
    non_trading_reason(date_str) varsa neden kodu kullanilir (FUTURE_DATE
    ayrimi), yoksa is_trading_day(date_str) bool sonucu kullanilir.
    """
    if calendar is None:
        return _info(NON_TRADING_DAY, True)
    trade_date = _get(bar, "trade_date")
    reason = None
    if hasattr(calendar, "non_trading_reason"):
        reason = calendar.non_trading_reason(trade_date)
        if reason == FUTURE_DATE:
            return _fatal(FUTURE_DATE, False)
        return _fatal(NON_TRADING_DAY, reason is None)
    ok = bool(calendar.is_trading_day(trade_date))
    return _fatal(NON_TRADING_DAY, ok)


# --------------------------------------------------------------------------- #
# Kural 9: tekrarlanan tarih (FATAL)
# --------------------------------------------------------------------------- #
def no_duplicate_date(bar, seen_keys=None) -> RuleResult:
    """Kural 9: ayni stock_id+trade_date+source katmaninda tekrar YOK.

    seen_keys: (trade_date, source) ikililerinden olusan set. None ise
    kontrol atlanir (INFO ok). Anahtar set'te varsa DUPLICATE_DATE FATAL.
    """
    if seen_keys is None:
        return _info(DUPLICATE_DATE, True)
    key = (str(_get(bar, "trade_date")), str(_get(bar, "source") or ""))
    return _fatal(DUPLICATE_DATE, key not in seen_keys)


# --------------------------------------------------------------------------- #
# Kural 10: para birimi (FATAL)
# --------------------------------------------------------------------------- #
def currency_ok(bar, allowed_currencies=None) -> RuleResult:
    """Kural 10: para birimi izinli sette (CURRENCY_MISMATCH)."""
    allowed = allowed_currencies
    if allowed is None:
        allowed = DEFAULT_ALLOWED_CURRENCIES
    currency = _get(bar, "currency")
    ok = isinstance(currency, str) and currency in allowed
    return _fatal(CURRENCY_MISMATCH, ok)


# --------------------------------------------------------------------------- #
# Kural 11: sembol-sirket sahipligi (FATAL; BLOK 6 enjeksiyonu)
# --------------------------------------------------------------------------- #
def _symbol_belongs_to(identity_service, stock_id, symbol) -> Optional[bool]:
    """Enjekte kimlik servisiyle sembol sahipligini cozer.

    Desteklenen protokoller (sirayla):
    1. service.symbol_belongs_to(stock_id, symbol) -> bool
    2. service callable: service(stock_id, symbol) -> bool
    3. BLOK 6 SymbolIdentityService.resolve(symbol) -> ResolveResult(stock_id)
    Cozulemezse None (kontrol yapilamadi).
    """
    if hasattr(identity_service, "symbol_belongs_to"):
        return bool(identity_service.symbol_belongs_to(stock_id, symbol))
    if callable(identity_service):
        return bool(identity_service(stock_id, symbol))
    if hasattr(identity_service, "resolve"):
        res = identity_service.resolve(symbol)
        if res is None:
            return False
        return getattr(res, "stock_id", None) == stock_id
    return None


def symbol_owner_ok(bar, identity_service=None) -> RuleResult:
    """Kural 11: sembol dogru sirkete ait (SYMBOL_OWNER_MISMATCH).

    Servis veya bar'da symbol yoksa kontrol atlanir (INFO ok).
    Uyusmazlik kati ihlaldir -> FATAL.
    """
    symbol = _get(bar, "symbol")
    stock_id = _get(bar, "stock_id")
    if identity_service is None or symbol is None:
        return _info(SYMBOL_OWNER_MISMATCH, True)
    verdict = _symbol_belongs_to(identity_service, stock_id, symbol)
    if verdict is None:
        return _info(SYMBOL_OWNER_MISMATCH, True)
    return _fatal(SYMBOL_OWNER_MISMATCH, verdict)


# --------------------------------------------------------------------------- #
# Kural 12: olagan disi fark aciklamasi (WARN)
# --------------------------------------------------------------------------- #
def pct_change(close, prev_close) -> float:
    """Kapanis degisim yuzdesi (prev_close'a gore, mutlak)."""
    return abs(float(close) - float(prev_close)) / float(prev_close) * 100.0


def outlier_explained(
    bar,
    prev_close=None,
    threshold_pct: float = DEFAULT_OUTLIER_THRESHOLD_PCT,
    explanation: Optional[str] = None,
) -> RuleResult:
    """Kural 12: fark > esik ise aciklama gerekir (UNEXPLAINED_OUTLIER).

    Aciklama kaynaklari: `explanation` parametresi veya bar'in
    `outlier_explanation` niteligi (or. kurumsal islem, islem durdurma
    sonrasi, kaynak duzeltmesi). Esik asimi + aciklama yok -> WARN.
    """
    close = _get(bar, "close")
    if not _is_positive(prev_close) or not _is_number(close):
        return _info(UNEXPLAINED_OUTLIER, True)
    if pct_change(close, prev_close) <= threshold_pct:
        return _info(UNEXPLAINED_OUTLIER, True)
    note = explanation or _get(bar, "outlier_explanation")
    if note:
        return _info(UNEXPLAINED_OUTLIER, True)
    return RuleResult(code=UNEXPLAINED_OUTLIER, ok=False, severity=WARN)


# --------------------------------------------------------------------------- #
# Kural 13: kurumsal islem kontrolu yapildi mi (INFO)
# --------------------------------------------------------------------------- #
def corporate_checked(bar, corporate_lookup=None) -> RuleResult:
    """Kural 13: o gun icin kurumsal islem kaydi kontrol edildi mi.

    corporate_lookup(stock_id, trade_date) -> list | None protokolu:
    liste (bos olabilir) donmesi "kontrol yapildi" demektir; None "kontrol
    yapilmadi". Kontrol yapilmamasi tek basina katman dusurmez (INFO);
    VALIDATED yukseltmesinde zorunlu kosul olarak yeniden denetlenir.
    """
    if corporate_lookup is None:
        return _info(CORPORATE_NOT_CHECKED, False)
    res = corporate_lookup(_get(bar, "stock_id"), _get(bar, "trade_date"))
    return _info(CORPORATE_NOT_CHECKED, res is not None)


# --------------------------------------------------------------------------- #
# Ek: kaynak karsilastirma (WARN; VALIDATED icin zorunlu adim)
# --------------------------------------------------------------------------- #
def source_cross_check(
    bar,
    reference_close=None,
    tolerance_pct: float = DEFAULT_SOURCE_TOLERANCE_PCT,
) -> RuleResult:
    """Ana/yedek kaynak kapanislari karsilastirildi mi.

    reference_close None ise kontrol yapilmadi (INFO ok, kod
    SOURCE_DIVERGENCE_REVIEW). Fark tolerans disinda -> WARN.
    """
    if reference_close is None:
        return _info(SOURCE_DIVERGENCE_REVIEW, True)
    close = _get(bar, "close")
    if not _is_number(close) or not _is_positive(reference_close):
        return _info(SOURCE_DIVERGENCE_REVIEW, True)
    ok = pct_change(close, reference_close) <= tolerance_pct
    return RuleResult(code=SOURCE_DIVERGENCE_REVIEW, ok=ok, severity=WARN)


# --------------------------------------------------------------------------- #
# Toplu degerlendirme
# --------------------------------------------------------------------------- #
def status_from_results(results: Sequence[RuleResult]) -> LayerStatus:
    """Kural sonuclarindan katman durumu: FATAL -> REJECTED, WARN ->
    REVIEW_REQUIRED, aksi -> CLEAN."""
    status = LayerStatus.CLEAN
    for r in results:
        if r.ok:
            continue
        if r.severity == FATAL:
            return LayerStatus.REJECTED
        if r.severity == WARN:
            status = LayerStatus.REVIEW_REQUIRED
    return status


def evaluate_bar(bar, context: Optional[BarContext] = None):
    """13 kurali (+ varsa kaynak karsilastirmasini) calistirir.

    Donus: (LayerStatus, [RuleResult]). Kural listesi sabit 13 kurali
    icerir; reference_close verildiyse SOURCE_DIVERGENCE_REVIEW eklenir.
    """
    ctx = context or BarContext()
    results: List[RuleResult] = [
        open_positive(bar),
        high_positive(bar),
        low_positive(bar),
        close_positive(bar),
        volume_non_negative(bar),
        high_covers_all(bar),
        low_below_all(bar),
        valid_trading_day(bar, ctx.calendar),
        no_duplicate_date(bar, ctx.seen_keys),
        currency_ok(bar, ctx.allowed_currencies),
        symbol_owner_ok(bar, ctx.identity_service),
        outlier_explained(
            bar,
            prev_close=ctx.prev_close,
            threshold_pct=ctx.outlier_threshold_pct,
            explanation=ctx.outlier_explanation,
        ),
        corporate_checked(bar, ctx.corporate_lookup),
    ]
    if ctx.reference_close is not None:
        results.append(
            source_cross_check(bar, ctx.reference_close, ctx.source_tolerance_pct)
        )
    return status_from_results(results), results
