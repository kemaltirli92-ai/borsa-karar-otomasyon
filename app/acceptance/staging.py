"""BLOK 22 - Tam gunluk ornek tarama (staging.py).

StagingRunner, 100 sirketlik resmi evreni (UniverseBook) TEK SABAH AKISI ile
tarar: GERCEK modullerle, ENJEKTE fetcher'larla. Gercek ag YOKTUR.

Sembol basina GERCEK akis:
  fetch -> OHLC dogrula (BLOK 9 validation kurallari) ->
  hacim siniflandir (BLOK 10 volume) -> KAP/haber say (enjekte listeler) ->
  kurumsal islem/tedbir (BLOK 13 registry + SuspensionPolicy) ->
  veri yeterliligi (BLOK 9 sufficiency) -> Veri Guveni (BLOK 15
  ConfidenceCalculator).

Kurallar (KESIN):
- Bir sembolun hatasi digerlerini DURDURMAZ: hata o sembolun state=FAILED
  olmasina yol acar, dongu devam eder (hata izolasyonu kaniti).
- Eksik veri None KALIR ve missing_fields'a yazilir — ASLA 0'a CEVRILMEZ
  (price_rows / volume_rows None tasinir). Sayac alanlari (kap_count vb.)
  int'tir; kanal cekilemeyince sayac 0 olur AMA eksiklik missing_fields'da
  kanal adiyla aciklanir (sessiz sifir YOK).
- TRADING_HALT: hisse taramadan SILINMEZ (keep_in_scan), scoring_ready=False
  (BLOK 13 SuspensionPolicy kurali aynen).
- run_id oneki: 'STAGING-YYYY-MM-DD-TARAMA-R1'.
- finished_at = tarama gunu 08:00 + toplam simule sure (durations enjekte).
  finish_by_0935 = finished_at <= ayni gun 09:35.
- Zarf (envelope): scan_run_id/report_version/last_updated_at/
  data_cutoff_at/status (OK|PARTIAL|FAILED).
- Puan kilidi: bu modul skor/sinyal URETMEZ; yalnizca veri guveni (0-100)
  ve hazirlik durumlari tasinir.

Deterministik: clock enjekte edilebilir (default parametre olarak enjekte
clock referansi; modul icinde dogrudan datetime.now() cagrisi YOKTUR).
stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from app.services.stock_scanning.confidence import (
    ComponentScanInputs,
    ConfidenceCalculator,
    ReadinessInputs,
    evaluate_components,
    evaluate_readiness,
)
from app.services.stock_scanning.corporate_actions.models import (
    RestrictionType,
    TradingRestriction,
)
from app.services.stock_scanning.corporate_actions.restrictions import (
    RestrictionRegistry,
)
from app.services.stock_scanning.corporate_actions.suspension import (
    SuspensionPolicy,
)
from app.services.stock_scanning.validation import (
    close_positive,
    high_covers_all,
    high_positive,
    low_below_all,
    low_positive,
    open_positive,
    volume_non_negative,
)
from app.services.stock_scanning.validation.sufficiency import classify_sufficiency
from app.services.stock_scanning.volume import classify_volume

# Durum degerleri
STATE_READY = "READY"
STATE_PARTIAL = "PARTIAL_DATA"
STATE_FAILED = "FAILED"
STATE_INACTIVE = "INACTIVE"

# Zarf durumlari
STATUS_OK = "OK"
STATUS_PARTIAL = "PARTIAL"
STATUS_FAILED = "FAILED"

SCAN_START_TIME = time(8, 0)        # tarama baslangici 08:00
FINISH_LIMIT_TIME = time(9, 35)     # 09:35 bitis siniri
DATA_CUTOFF_TIME = time(9, 40)      # 09:40 veri kesimi (BLOK 14 sabiti)

FETCH_CHANNELS = ("price", "volume", "kap", "news", "actions", "restrictions")

DEFAULT_PER_SYMBOL_SECONDS = 3.0    # simule gorev suresi (sn/sembol)
DEFAULT_STARTUP_SECONDS = 0.0


class StagingSourceError(Exception):
    """fail_symbols ile isaretlenen sembolde simule kaynak hatasi."""


@dataclass(frozen=True)
class StockDayResult:
    """Bir sirketin tek gunluk staging sonucu (degistirilemez)."""

    symbol: str
    state: str  # READY|PARTIAL_DATA|FAILED|INACTIVE
    price_rows: Optional[int]
    volume_rows: Optional[int]
    kap_count: int
    news_count: int
    action_count: int
    restriction_count: int
    data_confidence: int  # 0-100 (ConfidenceCalculator ile)
    missing_fields: Tuple[str, ...]  # eksik alanlar; None->alan adi


@dataclass(frozen=True)
class StagingReport:
    """Tam gunluk staging tarama raporu (degistirilemez)."""

    run_id: str
    day: str
    started_at: str
    finished_at: str
    finish_by_0935: bool  # simulated finished_at <= 09:35
    total: int
    ready: int
    partial: int
    failed: int
    inactive: int
    missing_total: int  # sessiz dusme sayisi: total - len(results)
    results: Tuple[StockDayResult, ...]
    envelope: dict


def _iso_day(value) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(str(value).strip()[:10]).isoformat()


def _to_bar(record) -> SimpleNamespace:
    """Ham kayit dict'ini validation kurallarinin okudugu bar nesnesine cevirir."""
    get = record.get if isinstance(record, dict) else lambda k, d=None: getattr(record, k, d)
    return SimpleNamespace(
        stock_id=get("stock_id", ""),
        trade_date=str(get("trade_date", get("date", ""))),
        open=get("open"),
        high=get("high"),
        low=get("low"),
        close=get("close"),
        volume=get("volume"),
        currency=get("currency", "TRY"),
        source=get("source", "staging"),
    )


def _ohlc_valid(bar) -> bool:
    """BLOK 9 gercek OHLC kurallari: pozitiflik + kapsama + hacim.

    high >= max(open, close, low) VE low <= min(open, close, high)
    (high_covers_all / low_below_all kurallari). Bozuk bar REDDEDILIR.
    """
    checks = (
        open_positive,
        high_positive,
        low_positive,
        close_positive,
        high_covers_all,
        low_below_all,
        volume_non_negative,
    )
    for rule in checks:
        try:
            if not rule(bar).ok:
                return False
        except (TypeError, ValueError):
            return False
    return True


class StagingRunner:
    """Tam gun ornek tarama — GERCEK modullerle, ENJEKTE fetcher'larla.

    fetchers sozlesmesi (None = kanal cekilemedi):
      "price"        : fn(symbol) -> list[bar-dict] | None
      "volume"       : fn(symbol) -> list | None
      "kap"          : fn(symbol) -> list | None
      "news"         : fn(symbol) -> list | None
      "actions"      : fn(symbol) -> list | None
      "restrictions" : fn(symbol) -> list[dict] | None

    durations: {"per_symbol_seconds": float, "startup_seconds": float} —
    toplam sure tarama gunu 08:00'a eklenir -> finished_at (simulasyon).

    fail_symbols: bu sembollerde price fetcher StagingSourceError firlatir
    (1 sembol patlasa bile digerleri devam eder — hata izolasyonu kaniti).
    """

    def __init__(
        self,
        universe,
        fetchers: Dict[str, Callable],
        clock: Optional[Callable[[], datetime]] = None,
        durations: Optional[Dict[str, float]] = None,
        fail_symbols: Optional[Set[str]] = None,
    ):
        self._universe = universe
        self._fetchers = dict(fetchers or {})
        # default parametre olarak enjekte clock referansi (govdede cagri YOK)
        self._clock: Callable[[], datetime] = clock or datetime.now
        self._durations = dict(durations or {})
        self._fail_symbols = set(fail_symbols or set())

    # ------------------------------------------------------------------ #
    # Fetch yardimcisi (kanal hatasi sembol bazli izole)
    # ------------------------------------------------------------------ #
    def _fetch(self, channel: str, symbol: str):
        fetcher = self._fetchers.get(channel)
        if fetcher is None:
            return None
        if channel == "price" and symbol in self._fail_symbols:
            raise StagingSourceError(f"simule kaynak hatasi: {symbol}/{channel}")
        return fetcher(symbol)

    # ------------------------------------------------------------------ #
    # Tek sembol akisi
    # ------------------------------------------------------------------ #
    def _scan_symbol(self, symbol: str, day: str) -> StockDayResult:
        d = date.fromisoformat(day)
        missing: List[str] = []
        kap_count = news_count = action_count = restriction_count = 0
        price_rows: Optional[int] = None
        volume_rows: Optional[int] = None
        last_close: Optional[float] = None
        last_volume: Optional[int] = None
        last_date: Optional[str] = None
        rejected_bars = 0
        halt_active = False

        # 0) Evren uyeligi: o gun uye degilse INACTIVE (fetch YOK)
        if not self._universe.is_member(symbol, day):
            return StockDayResult(
                symbol=symbol,
                state=STATE_INACTIVE,
                price_rows=None,
                volume_rows=None,
                kap_count=0,
                news_count=0,
                action_count=0,
                restriction_count=0,
                data_confidence=0,
                missing_fields=("universe_membership",),
            )

        # 1) Fiyat cek + OHLC dogrula (BLOK 9 kurallari)
        raw_prices = self._fetch("price", symbol)
        valid_bars: List[SimpleNamespace] = []
        if raw_prices is None:
            missing.append("price")
        else:
            for rec in raw_prices:
                bar = _to_bar(rec)
                if _ohlc_valid(bar):
                    valid_bars.append(bar)
                else:
                    rejected_bars += 1
            price_rows = len(valid_bars)
            if valid_bars:
                last = valid_bars[-1]
                last_close = float(last.close)
                last_volume = last.volume
                last_date = str(last.trade_date)

        # 2) Hacim siniflandir (BLOK 10 gercek classifier; NULL vs 0)
        raw_volume = self._fetch("volume", symbol)
        if raw_volume is None:
            missing.append("volume")
        else:
            volume_rows = len(raw_volume)
        if raw_prices is not None and last_volume is None:
            # fiyat serisi var ama son gun hacmi bilinmiyor -> eksik (0'a CEVRILMEZ)
            if "volume" not in missing:
                missing.append("volume")
        volumes = [
            b.volume for b in valid_bars if getattr(b, "volume", None) is not None
        ]
        avg20 = (sum(volumes[-20:]) / len(volumes[-20:])) if volumes else None
        ratio = (
            (float(last_volume) / avg20)
            if (last_volume is not None and avg20)
            else None
        )
        # gercek BLOK 10 siniflandirici cagrilir (durum staging'e yazilmaz)
        classify_volume(last_volume=last_volume, avg20=avg20, ratio=ratio)

        # 3) KAP / haber say (enjekte kanallar; None = kanal cekilemedi)
        kap_items = self._fetch("kap", symbol)
        if kap_items is None:
            missing.append("kap")
        else:
            kap_count = len(kap_items)
        news_items = self._fetch("news", symbol)
        if news_items is None:
            missing.append("news")
        else:
            news_count = len(news_items)

        # 4) Kurumsal islem + tedbir (BLOK 13 gercek registry/policy)
        action_items = self._fetch("actions", symbol)
        if action_items is None:
            missing.append("actions")
        else:
            action_count = len(action_items)
        restriction_items = self._fetch("restrictions", symbol)
        if restriction_items is None:
            missing.append("restrictions")
        else:
            restriction_count = len(restriction_items)

        registry = RestrictionRegistry(clock=lambda: d)
        for item in restriction_items or []:
            try:
                rtype = RestrictionType(str(item.get("restriction_type")))
            except (ValueError, AttributeError):
                continue
            registry.register(
                symbol,
                TradingRestriction(
                    restriction_type=rtype,
                    start_date=str(item.get("start_date", day)),
                    end_date=item.get("end_date"),
                    is_active=bool(item.get("is_active", True)),
                    source=str(item.get("source", "staging")),
                    official_url=item.get("official_url"),
                    collected_at=f"{day}T08:00:00",
                ),
            )
        scan_status = SuspensionPolicy(registry).scan_status(symbol)
        halt_active = not scan_status.scoring_ready

        # 5) Veri yeterliligi (BLOK 9 gercek classify_sufficiency)
        verdict = classify_sufficiency(
            symbol,
            [
                SimpleNamespace(status="VALIDATED", trade_date=b.trade_date)
                for b in valid_bars
            ],
            clock=lambda: d,
        )
        sufficiency_label = verdict.status

        # 6) Veri Guveni (BLOK 15 gercek ConfidenceCalculator)
        critical_missing: List[str] = []
        if price_rows is None:
            critical_missing.append("price")
        if last_date is None:
            critical_missing.append("last_trade_date")
        stale = last_date is not None and last_date < day
        scan_inputs = ComponentScanInputs(
            last_price=last_close,
            source_validation=(
                None
                if raw_prices is None
                else ("VALIDATED" if rejected_bars == 0 else "PENDING")
            ),
            volume=last_volume,
            sufficiency_label=sufficiency_label,
            kap_status=None if kap_items is None else "COMPLETED",
            news_status=None if news_items is None else "COMPLETED",
            corporate_status=None if action_items is None else "COMPLETED",
            restriction_status=None if restriction_items is None else "COMPLETED",
            trading_halt_active=halt_active,
            verification_status="VERIFIED",
            last_data_date=last_date,
            anomaly_count=rejected_bars,
            critical_missing=critical_missing,
        )
        components = evaluate_components(scan_inputs, clock=lambda: d)
        readiness = evaluate_readiness(
            ReadinessInputs(
                symbol_verified=True,
                xk100_member=True,
                has_valid_price=price_rows is not None and price_rows > 0,
                has_valid_volume=last_volume is not None,
                has_last_trade_date=last_date is not None,
                kap_check_ok=kap_items is not None,
                news_check_ok=news_items is not None,
                corporate_check_ok=action_items is not None,
                restriction_check_ok=restriction_items is not None,
                source_validation_ok=raw_prices is not None and rejected_bars == 0,
                sufficiency_label_present=True,
                trading_halt_active=halt_active,
                critical_missing=critical_missing,
                stale_present=stale,
                sufficiency_label=sufficiency_label,
            )
        )
        confidence = ConfidenceCalculator().calculate(symbol, components, readiness)

        if missing:
            state = STATE_PARTIAL
        else:
            state = STATE_READY
        return StockDayResult(
            symbol=symbol,
            state=state,
            price_rows=price_rows,
            volume_rows=volume_rows,
            kap_count=kap_count,
            news_count=news_count,
            action_count=action_count,
            restriction_count=restriction_count,
            data_confidence=int(confidence.data_confidence),
            missing_fields=tuple(missing),
        )

    # ------------------------------------------------------------------ #
    # Tam gun tarama
    # ------------------------------------------------------------------ #
    def run(self, day: str) -> StagingReport:
        """100 sirketlik evreni tek sabah akisiyla tarar (hata izolasyonlu)."""
        day = _iso_day(day)
        d = date.fromisoformat(day)

        # 1) Resmi evren dogrulamasi (100 beklenir; sessiz dusme YOK)
        self._universe.validate_count(day, 100)
        symbols = self._universe.active_symbols(day)

        run_id = f"STAGING-{day}-TARAMA-R1"
        started_dt = datetime.combine(d, SCAN_START_TIME)

        results: List[StockDayResult] = []
        for symbol in symbols:
            try:
                results.append(self._scan_symbol(symbol, day))
            except Exception:
                # Hata izolasyonu: 1 sembol patlar, diger 99 DEVAM EDER.
                results.append(
                    StockDayResult(
                        symbol=symbol,
                        state=STATE_FAILED,
                        price_rows=None,
                        volume_rows=None,
                        kap_count=0,
                        news_count=0,
                        action_count=0,
                        restriction_count=0,
                        data_confidence=0,
                        missing_fields=tuple(FETCH_CHANNELS),
                    )
                )

        total = len(symbols)
        ready = sum(1 for r in results if r.state == STATE_READY)
        partial = sum(1 for r in results if r.state == STATE_PARTIAL)
        failed = sum(1 for r in results if r.state == STATE_FAILED)
        inactive = sum(1 for r in results if r.state == STATE_INACTIVE)

        # 2) Simule bitis: 08:00 + startup + sembol basina sure (enjekte)
        startup = float(self._durations.get("startup_seconds", DEFAULT_STARTUP_SECONDS))
        per_symbol = float(
            self._durations.get("per_symbol_seconds", DEFAULT_PER_SYMBOL_SECONDS)
        )
        finished_dt = started_dt + timedelta(seconds=startup + total * per_symbol)
        finish_limit = datetime.combine(d, FINISH_LIMIT_TIME)
        finish_by = finished_dt <= finish_limit

        # 3) Zarf (BLOK 16 zarf sozlesmesiyle ayni anahtarlar)
        if total > 0 and failed == total:
            status = STATUS_FAILED
        elif partial == 0 and failed == 0 and inactive == 0:
            status = STATUS_OK
        else:
            status = STATUS_PARTIAL
        envelope = {
            "scan_run_id": run_id,
            "report_version": 1,
            "last_updated_at": finished_dt.isoformat(),
            "data_cutoff_at": datetime.combine(d, DATA_CUTOFF_TIME).isoformat(),
            "status": status,
        }

        return StagingReport(
            run_id=run_id,
            day=day,
            started_at=started_dt.isoformat(),
            finished_at=finished_dt.isoformat(),
            finish_by_0935=finish_by,
            total=total,
            ready=ready,
            partial=partial,
            failed=failed,
            inactive=inactive,
            missing_total=total - len(results),
            results=tuple(results),
            envelope=envelope,
        )
