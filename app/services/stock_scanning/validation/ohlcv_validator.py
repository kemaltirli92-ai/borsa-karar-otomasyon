"""BLOK 9 - OhlcvValidator: bar/seri dogrulama ve katman atama (ohlcv_validator.py).

SPEC BLOK 9 bolum 6.

- validate_bar(bar) -> BarVerdict: tek bar icin 13 kural; kati ihlal ->
  REJECTED, supheli -> REVIEW_REQUIRED, gecen -> CLEAN.
- validate_series(stock_id, bars) -> SeriesVerdict: seri bazli dogrulama;
  tekrar tarih takibi (DUPLICATE_DATE) ve outlier zincirleme (onceki
  guvenilir CLEAN kapanisa gore).
- promote_validated(bar_ids) -> PromotionReport: CLEAN + kaynak
  karsilastirma OK + kurumsal kontrol OK kosuluyla VALIDATED'a yukseltir
  (BLOK 7 repo.promote_to_validated zincirine uyumlu; istege bagli
  `promoter` enjeksiyonu ile dis sisteme delege edilebilir).
- Ham kayit HICBIR ZAMAN silinmez: REJECTED dahil tum kararlar
  validator'un kaydinda (verdict registry) kalir; silme API'si yoktur.

Enjeksiyonlar:
- calendar: TradingCalendar (None -> varsayilan hafta sonu takvimi)
- identity_service: BLOK 6 SymbolIdentityService benzeri (mock) —
  symbol_belongs_to / callable / resolve protokolleri desteklenir.
- corporate_lookup: (stock_id, trade_date) -> list | None (None = kontrol
  yapilmadi; liste = kontrol yapildi, listedeki aksiyonlar outlier
  aciklamasi sayilir)
- source_compare: (bar) -> bool | (bool, dict) — VALIDATED yukseltmesinde
  kaynak karsilastirma adimi.
- config: ValidationConfig (para birimi seti, outlier esigi, kaynak
  toleransi)
- clock: takvim icin 'bugun' saglayici.

Gercek ag YOK; stdlib only; deterministik.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .calendar import TradingCalendar
from .rules import (
    BarContext,
    CORPORATE_NOT_CHECKED,
    DEFAULT_ALLOWED_CURRENCIES,
    DEFAULT_OUTLIER_THRESHOLD_PCT,
    DEFAULT_SOURCE_TOLERANCE_PCT,
    LayerStatus,
    RuleResult,
    SOURCE_DIVERGENCE_REVIEW,
    evaluate_bar,
)

# Promosyon red nedenleri
BAR_NOT_FOUND = "BAR_NOT_FOUND"
STATUS_NOT_CLEAN = "STATUS_NOT_CLEAN"
SOURCE_CHECK_MISSING = "SOURCE_CHECK_MISSING"
CORPORATE_CHECK_MISSING = "CORPORATE_CHECK_MISSING"
PROMOTED_TO_VALIDATED = "PROMOTED_TO_VALIDATED"


@dataclass
class ValidationConfig:
    """Dogrulama esikleri (yonetici ayari)."""

    allowed_currencies: Set[str] = field(
        default_factory=lambda: set(DEFAULT_ALLOWED_CURRENCIES)
    )
    outlier_threshold_pct: float = DEFAULT_OUTLIER_THRESHOLD_PCT
    source_tolerance_pct: float = DEFAULT_SOURCE_TOLERANCE_PCT


@dataclass
class BarVerdict:
    """Tek bar icin dogrulama karari (ham bar nesnesi degistirilmez)."""

    bar_id: str
    bar: Any
    status: LayerStatus
    rule_results: List[RuleResult] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def failed_codes(self) -> List[str]:
        """Basarisiz kural kodlari."""
        return [r.code for r in self.rule_results if not r.ok]


@dataclass
class SeriesVerdict:
    """Seri dogrulama sonucu: bar kararlari + durum sayimlari."""

    stock_id: str
    bar_verdicts: List[BarVerdict] = field(default_factory=list)
    status_counts: Dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return len(self.bar_verdicts)

    def count(self, status: LayerStatus) -> int:
        return self.status_counts.get(status.value, 0)


@dataclass
class PromotionReport:
    """promote_validated sonucu."""

    promoted: List[str] = field(default_factory=list)
    failed: Dict[str, str] = field(default_factory=dict)


class OhlcvValidator:
    """OHLCV dogrulayici + katman yoneticisi."""

    def __init__(
        self,
        calendar: Optional[TradingCalendar] = None,
        identity_service: Optional[Any] = None,
        corporate_lookup: Optional[Callable] = None,
        source_compare: Optional[Callable] = None,
        config: Optional[ValidationConfig] = None,
        clock: Optional[Callable] = None,
        promoter: Optional[Callable] = None,
    ):
        self.calendar = calendar or TradingCalendar(clock=clock)
        self.identity_service = identity_service
        self.corporate_lookup = corporate_lookup
        self.source_compare = source_compare
        self.config = config or ValidationConfig()
        self._promoter = promoter
        # Karar kaydi: bar_id -> BarVerdict. HICBIR ZAMAN silinmez.
        self._verdicts: Dict[str, BarVerdict] = {}
        # Elle eklenen outlier aciklamalari: (stock_id, trade_date) -> neden
        self._explanations: Dict[Tuple[str, str], str] = {}

    # ------------------------------------------------------------------ #
    # Kayit (silme yok — ham kayit daima korunur)
    # ------------------------------------------------------------------ #
    def verdict(self, bar_id: str) -> Optional[BarVerdict]:
        return self._verdicts.get(bar_id)

    def all_verdicts(self) -> List[BarVerdict]:
        return list(self._verdicts.values())

    def review_queue(self) -> List[BarVerdict]:
        """Yonetici incelemesi bekleyen (cozulmemis) barlar."""
        return [
            v
            for v in self._verdicts.values()
            if v.status == LayerStatus.REVIEW_REQUIRED
        ]

    def add_outlier_explanation(self, stock_id: str, trade_date: str, reason: str) -> None:
        """Bir gun icin outlier aciklamasi kaydeder (or. TRADING_HALT_RESUME)."""
        if not reason or not str(reason).strip():
            raise ValueError("reason bos olamaz")
        self._explanations[(stock_id, str(trade_date))] = str(reason)

    def _bar_id(self, bar) -> str:
        explicit = getattr(bar, "bar_id", None)
        if explicit:
            return str(explicit)
        return "%s|%s|%s" % (
            getattr(bar, "stock_id", ""),
            getattr(bar, "trade_date", ""),
            getattr(bar, "source", "") or "",
        )

    def _resolve_explanation(self, bar) -> Optional[str]:
        """Outlier aciklamasi cozumleme: bar niteligi > elle kayit > kurumsal."""
        note = getattr(bar, "outlier_explanation", None)
        if note:
            return str(note)
        stock_id = getattr(bar, "stock_id", None)
        trade_date = getattr(bar, "trade_date", None)
        saved = self._explanations.get((stock_id, str(trade_date)))
        if saved:
            return saved
        if self.corporate_lookup is not None:
            actions = self.corporate_lookup(stock_id, trade_date)
            if actions:
                refs = [
                    str(getattr(a, "kap_notice_no", None) or a) for a in actions
                ]
                return "CORPORATE_ACTION:%s" % ",".join(refs)
        return None

    # ------------------------------------------------------------------ #
    # Tek bar dogrulama
    # ------------------------------------------------------------------ #
    def validate_bar(
        self,
        bar,
        prev_close: Optional[float] = None,
        seen_keys: Optional[Set[Tuple[str, str]]] = None,
        reference_close: Optional[float] = None,
        outlier_explanation: Optional[str] = None,
    ) -> BarVerdict:
        """Tek bar icin 13 kurali calistirir; BarVerdict dondurur ve kaydeder.

        FATAL ihlal -> REJECTED; WARN -> REVIEW_REQUIRED; temiz -> CLEAN.
        """
        ctx = BarContext(
            calendar=self.calendar,
            allowed_currencies=set(self.config.allowed_currencies),
            identity_service=self.identity_service,
            corporate_lookup=self.corporate_lookup,
            prev_close=prev_close,
            outlier_threshold_pct=self.config.outlier_threshold_pct,
            outlier_explanation=outlier_explanation or self._resolve_explanation(bar),
            reference_close=reference_close,
            source_tolerance_pct=self.config.source_tolerance_pct,
            seen_keys=seen_keys,
        )
        status, results = evaluate_bar(bar, ctx)
        verdict = BarVerdict(
            bar_id=self._bar_id(bar),
            bar=bar,
            status=status,
            rule_results=list(results),
            notes=[r.code for r in results if not r.ok],
        )
        self._verdicts[verdict.bar_id] = verdict
        return verdict

    # ------------------------------------------------------------------ #
    # Seri dogrulama (tekrar tarih + outlier zincirleme)
    # ------------------------------------------------------------------ #
    def validate_series(self, stock_id: str, bars) -> SeriesVerdict:
        """Bar serisini tarih sirasina gore dogrular.

        - Ayni (trade_date, source) ikinci kez gelirse DUPLICATE_DATE (FATAL).
        - Outlier referansi onceki CLEAN kapanistir; REJECTED/REVIEW_REQUIRED
          barlar referans GUNCELLEMEZ (guvenilir degil).
        """
        ordered = sorted(bars, key=lambda b: str(getattr(b, "trade_date", "")))
        seen: Set[Tuple[str, str]] = set()
        prev_close: Optional[float] = None
        series = SeriesVerdict(stock_id=stock_id)
        counts: Dict[str, int] = {}
        for bar in ordered:
            verdict = self.validate_bar(bar, prev_close=prev_close, seen_keys=seen)
            key = (
                str(getattr(bar, "trade_date", "")),
                str(getattr(bar, "source", "") or ""),
            )
            seen.add(key)
            if verdict.status == LayerStatus.CLEAN:
                prev_close = getattr(bar, "close", None)
            series.bar_verdicts.append(verdict)
            counts[verdict.status.value] = counts.get(verdict.status.value, 0) + 1
        series.status_counts = counts
        return series

    # ------------------------------------------------------------------ #
    # VALIDATED yukseltmesi
    # ------------------------------------------------------------------ #
    def _source_check_ok(self, verdict: BarVerdict) -> Tuple[bool, str]:
        """Kaynak karsilastirma adimi: (basarili mi, red nedeni)."""
        if self.source_compare is not None:
            res = self.source_compare(verdict.bar)
            ok = bool(res[0]) if isinstance(res, tuple) else bool(res)
            return (True, "") if ok else (False, SOURCE_DIVERGENCE_REVIEW)
        for r in verdict.rule_results:
            if r.code == SOURCE_DIVERGENCE_REVIEW:
                return (r.ok, "" if r.ok else SOURCE_DIVERGENCE_REVIEW)
        return False, SOURCE_CHECK_MISSING

    def _corporate_check_ok(self, verdict: BarVerdict) -> Tuple[bool, str]:
        """Kurumsal kontrol adimi: (basarili mi, red nedeni).

        Yukseltme aninda enjekte lookup ile YENIDEN dogrulanir: lookup
        enjekte edilmemisse kurumsal altyapi yok (CORPORATE_CHECK_MISSING);
        lookup None dondururse o gun kontrol yapilmamis (CORPORATE_NOT_CHECKED).
        """
        if self.corporate_lookup is None:
            return False, CORPORATE_CHECK_MISSING
        bar = verdict.bar
        res = self.corporate_lookup(
            getattr(bar, "stock_id", None), getattr(bar, "trade_date", None)
        )
        return (True, "") if res is not None else (False, CORPORATE_NOT_CHECKED)

    def promote_validated(self, bar_ids) -> PromotionReport:
        """CLEAN barlari VALIDATED'a yukseltir.

        Kosullar (SPEC bolum 6): status == CLEAN + kaynak karsilastirma OK
        + kurumsal kontrol OK. Kosulu saglamayan barlar yukseltilmez;
        nedenleri raporlanir. Yukseltme ham kaydi DEGISTIRMEZ: sadece
        karar (verdict) katman etiketi ilerler. `promoter` enjekte
        edildiyse basariyla yukseltilen id'ler dis sisteme delege edilir
        (BLOK 7 repo.promote_to_validated zincirine uyumlu).
        """
        report = PromotionReport()
        for bar_id in bar_ids:
            verdict = self._verdicts.get(bar_id)
            if verdict is None:
                report.failed[bar_id] = BAR_NOT_FOUND
                continue
            if verdict.status != LayerStatus.CLEAN:
                report.failed[bar_id] = STATUS_NOT_CLEAN
                continue
            ok, reason = self._source_check_ok(verdict)
            if not ok:
                report.failed[bar_id] = reason
                continue
            ok, reason = self._corporate_check_ok(verdict)
            if not ok:
                report.failed[bar_id] = reason
                continue
            verdict.status = LayerStatus.VALIDATED
            verdict.notes.append(PROMOTED_TO_VALIDATED)
            report.promoted.append(bar_id)
        if self._promoter is not None and report.promoted:
            self._promoter(list(report.promoted))
        return report

    # ------------------------------------------------------------------ #
    # Inceleme cozumu (yonetici karari)
    # ------------------------------------------------------------------ #
    def resolve_review(self, bar_id: str, approved: bool, note: Optional[str] = None) -> BarVerdict:
        """REVIEW_REQUIRED barini cozer: onay -> CLEAN, red -> REJECTED.

        Ham kayit korunur; sadece karar katmani degisir ve neden notu eklenir.
        """
        verdict = self._verdicts.get(bar_id)
        if verdict is None:
            raise KeyError("bar kaydi bulunamadi: %r" % (bar_id,))
        if verdict.status != LayerStatus.REVIEW_REQUIRED:
            raise ValueError(
                "bar inceleme durumunda degil: %r (%s)" % (bar_id, verdict.status.value)
            )
        verdict.status = LayerStatus.CLEAN if approved else LayerStatus.REJECTED
        verdict.notes.append(
            "REVIEW_RESOLVED:%s%s"
            % ("APPROVED" if approved else "REJECTED", ("|" + note) if note else "")
        )
        return verdict
