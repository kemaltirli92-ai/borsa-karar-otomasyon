"""BLOK 8 - PriceCollector: coklu kaynakli fiyat toplama (collector.py).

Akislar (SPEC bolum 6):
- bootstrap(stock_id): oncelik sirasina gore kaynaklari dener; ilk basarili
  kaynaktan bootstrap_days (260+) gun ceker. Kaynak basarisiz olunca
  digerine gecer ve gecisi LOGLAR (SOURCE_SWITCHED: eski->yeni, neden).
  Hepsi bos/basarisiz ise hicbir sey YAZMAZ: PRICE_DATA_MISSING + NULL paket.
- incremental_update(stock_id): DB'deki son trade_date'ten sonrasini ceker
  ve yazar; son recheck_days (10) gunu TEKRAR cekip karsilastirir — degisen
  bar yeni data_version ile guncellenir, ayni bara DOKUNULMAZ. Ayni veri
  tekrar gelirse kopya OLUSMAZ (unique anahtar).
- validate_against(stock_id, date, primary_bar): dogrulama kaynagi (google)
  ile kapanis karsilastirir; tolerans disi PRICE_SOURCE_DIVERGENCE,
  kaynak yok VALIDATION_SOURCE_UNAVAILABLE.
- Eski veri: en yeni bar stale_days_limit'ten eskiyse STALE_PRICE_DATA.
- Para birimi: allowed_currencies disi bar REDDEDILIR + WRONG_CURRENCY.

Sonuc nesnesi: CollectionResult(stock_id, status, bars_written, source_used,
warnings, errors) — status: OK | PRICE_DATA_MISSING | PARTIAL | FAILED.

Deterministik: saat enjekte (clock: datetime.date / datetime / ISO str
donebilir). Ag erisimi yoktur — tum kaynaklar enjekte fetcher'lidir.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable, Dict, List, Optional, Tuple

from .config import PriceCollectionConfig
from .sources import PriceBar, PriceSource
from .storage import PriceStorage
from .validator import close_diff_pct, validate_bar

# Sonuc durumlari
OK = "OK"
PRICE_DATA_MISSING = "PRICE_DATA_MISSING"
PARTIAL = "PARTIAL"
FAILED = "FAILED"

# Olay / uyari kodlari
SOURCE_SWITCHED = "SOURCE_SWITCHED"
PRICE_SOURCE_DIVERGENCE = "PRICE_SOURCE_DIVERGENCE"
VALIDATION_SOURCE_UNAVAILABLE = "VALIDATION_SOURCE_UNAVAILABLE"
STALE_PRICE_DATA = "STALE_PRICE_DATA"
WRONG_CURRENCY = "WRONG_CURRENCY"
BAR_REJECTED = "BAR_REJECTED"
RECHECK_UPDATED = "RECHECK_UPDATED"


@dataclass
class CollectionResult:
    """Toplama sonucu (SPEC bolum 6).

    bars_updated ve bars_skipped, SPEC alanlarina ek izleme kolayligi icin
    eklenmistir (son-10-gun guncelleme sayisi / kopya atlama sayisi).
    """

    stock_id: str
    status: str
    bars_written: int = 0
    source_used: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    bars_updated: int = 0
    bars_skipped: int = 0


@dataclass
class ValidationResult:
    """validate_against sonucu."""

    stock_id: str
    trade_date: str
    status: str  # OK | PRICE_SOURCE_DIVERGENCE | VALIDATION_SOURCE_UNAVAILABLE
    diff_pct: Optional[float] = None
    reference_source: Optional[str] = None


class PriceCollector:
    """Coklu kaynakli fiyat toplayici."""

    def __init__(
        self,
        sources: Dict[str, PriceSource],
        config: PriceCollectionConfig,
        storage: PriceStorage,
        logger=None,
        clock: Optional[Callable] = None,
    ):
        self.sources = dict(sources)
        self.config = config
        self.storage = storage
        self._logger = logger
        self._clock = clock or (lambda: date.today())
        self.events: List[dict] = []

    # ------------------------------------------------------------------ #
    # Loglama
    # ------------------------------------------------------------------ #
    def _log(self, code: str, **fields) -> None:
        event = {"event": code}
        event.update(fields)
        self.events.append(event)
        lg = self._logger
        if lg is None:
            return
        if callable(lg):
            lg(code, dict(fields))
        elif hasattr(lg, "info"):
            lg.info("%s | %s", code, fields)

    def events_by_code(self, code: str) -> List[dict]:
        return [e for e in self.events if e["event"] == code]

    # ------------------------------------------------------------------ #
    # Saat
    # ------------------------------------------------------------------ #
    def _today(self) -> date:
        now = self._clock()
        if isinstance(now, datetime):
            return now.date()
        if isinstance(now, date):
            return now
        if isinstance(now, str):
            return date.fromisoformat(now[:10])
        raise TypeError("clock date/datetime/ISO str dondurmeli: %r" % (now,))

    # ------------------------------------------------------------------ #
    # Kaynak deneme (oncelik sirasi + gecis logu)
    # ------------------------------------------------------------------ #
    def _filter_bars(self, stock_id: str, source_name: str, bars: List[PriceBar]) -> Tuple[List[PriceBar], List[str]]:
        """Bozuk/yanlis para birimli barlari eler; reddetme kodlarini doner."""
        kept: List[PriceBar] = []
        codes: List[str] = []
        for bar in bars:
            bar_errors = validate_bar(bar)
            if bar_errors:
                self._log(
                    BAR_REJECTED,
                    stock_id=stock_id,
                    source=source_name,
                    trade_date=bar.trade_date,
                    reasons=bar_errors,
                )
                if BAR_REJECTED not in codes:
                    codes.append(BAR_REJECTED)
                continue
            if bar.currency not in self.config.allowed_currencies:
                self._log(
                    WRONG_CURRENCY,
                    stock_id=stock_id,
                    source=source_name,
                    trade_date=bar.trade_date,
                    currency=bar.currency,
                )
                if WRONG_CURRENCY not in codes:
                    codes.append(WRONG_CURRENCY)
                continue
            kept.append(bar)
        return kept, codes

    def _try_sources(self, stock_id: str, days: int) -> Tuple[Optional[str], List[PriceBar], List[str]]:
        """Oncelik sirasina gore kaynaklari dener.

        Donus: (kullanilan kaynak adi veya None, gecerli barlar, reddetme
        kodlari). Bir kaynak basarisiz olunca sonrakine gecilir ve
        SOURCE_SWITCHED loglanir (eski->yeni, neden).
        """
        priority = list(self.config.source_priority)
        all_codes: List[str] = []
        for idx, name in enumerate(priority):
            source = self.sources.get(name)
            next_name = priority[idx + 1] if idx + 1 < len(priority) else None

            def _switch(reason: str) -> None:
                self._log(
                    SOURCE_SWITCHED,
                    stock_id=stock_id,
                    from_source=name,
                    to_source=next_name,
                    reason=reason,
                )

            if source is None:
                _switch("not_registered")
                continue
            try:
                raw_bars = source.fetch_history(stock_id, days)
            except Exception as exc:
                _switch("%s: %s" % (type(exc).__name__, exc))
                continue
            kept, codes = self._filter_bars(stock_id, name, raw_bars)
            for code in codes:
                if code not in all_codes:
                    all_codes.append(code)
            if kept:
                return name, kept, all_codes
            _switch("all_rejected" if raw_bars else "empty")
        return None, [], all_codes

    # ------------------------------------------------------------------ #
    # Stale kontrolu
    # ------------------------------------------------------------------ #
    def _check_stale(self, stock_id: str, newest_trade_date: Optional[str], result: CollectionResult) -> None:
        if newest_trade_date is None:
            return
        days_old = (self._today() - date.fromisoformat(newest_trade_date)).days
        if days_old > self.config.stale_days_limit:
            self._log(
                STALE_PRICE_DATA,
                stock_id=stock_id,
                latest_trade_date=newest_trade_date,
                days_old=days_old,
                stale_days_limit=self.config.stale_days_limit,
            )
            if STALE_PRICE_DATA not in result.warnings:
                result.warnings.append(STALE_PRICE_DATA)

    # ------------------------------------------------------------------ #
    # Bootstrap
    # ------------------------------------------------------------------ #
    def bootstrap(self, stock_id: str) -> CollectionResult:
        """Ilk kurulum: oncelik sirasina gore 260+ gunluk veri ceker.

        Tum kaynaklar bos/basarisiz ise hicbir sey yazilmaz:
        status=PRICE_DATA_MISSING (NULL paket).
        """
        result = CollectionResult(stock_id=stock_id, status=OK)
        name, bars, codes = self._try_sources(stock_id, self.config.bootstrap_days)
        if name is None:
            self._log(PRICE_DATA_MISSING, stock_id=stock_id)
            result.status = PRICE_DATA_MISSING
            result.errors.append(PRICE_DATA_MISSING)
            for code in codes:
                if code not in result.errors:
                    result.errors.append(code)
            return result

        result.source_used = name
        write_result = self.storage.write_bars(stock_id, bars, data_layer="raw")
        result.bars_written = write_result.written
        result.bars_skipped = write_result.skipped
        for code in codes:
            if code not in result.warnings:
                result.warnings.append(code)
        if codes:
            result.status = PARTIAL
        newest = max(b.trade_date for b in bars)
        self._check_stale(stock_id, newest, result)
        return result

    # ------------------------------------------------------------------ #
    # Artimli guncelleme + son 10 gun recheck
    # ------------------------------------------------------------------ #
    def incremental_update(self, stock_id: str) -> CollectionResult:
        """Son trade_date'ten sonrasini ceker-yazar + son 10 gunu recheck eder.

        Depoda hic veri yoksa bootstrap'a duser.
        """
        last = self.storage.get_last_trade_date(stock_id)
        if last is None:
            return self.bootstrap(stock_id)

        result = CollectionResult(stock_id=stock_id, status=OK)
        gap = max((self._today() - date.fromisoformat(last)).days, 0)
        days = gap + self.config.recheck_days + 2
        name, bars, codes = self._try_sources(stock_id, days)
        if name is None:
            self._log(PRICE_DATA_MISSING, stock_id=stock_id, stage="incremental")
            result.status = FAILED
            result.errors.append(PRICE_DATA_MISSING)
            for code in codes:
                if code not in result.errors:
                    result.errors.append(code)
            return result

        result.source_used = name
        new_bars = [b for b in bars if b.trade_date > last]
        write_result = self.storage.write_bars(stock_id, new_bars, data_layer="raw")
        result.bars_written = write_result.written
        result.bars_skipped = write_result.skipped
        for code in codes:
            if code not in result.warnings:
                result.warnings.append(code)
        if codes:
            result.status = PARTIAL

        # Son recheck_days gunu tekrar cek-karsilastir.
        result.bars_updated = self._recheck_recent(stock_id, bars)

        self._check_stale(stock_id, self.storage.get_last_trade_date(stock_id), result)
        return result

    @staticmethod
    def _bar_differs(stored: PriceBar, fresh: PriceBar) -> bool:
        """OHLCV alanlarindan herhangi biri farkliysa True."""
        return (
            stored.open != fresh.open
            or stored.high != fresh.high
            or stored.low != fresh.low
            or stored.close != fresh.close
            or stored.volume != fresh.volume
        )

    def _recheck_recent(self, stock_id: str, fresh_bars: List[PriceBar]) -> int:
        """Son recheck_days gunu taze veriyle karsilastirir.

        Degisen bar yeni data_version ile guncellenir (eski satir korunur);
        ayni bara DOKUNULMAZ. Donus: guncellenen bar sayisi.
        """
        fresh_by_key = {(b.trade_date, b.source): b for b in fresh_bars}
        stored_recent = self.storage.get_bars(stock_id, self.config.recheck_days)
        updated = 0
        for stored in stored_recent:
            fresh = fresh_by_key.get((stored.trade_date, stored.source))
            if fresh is None:
                continue
            if not self._bar_differs(stored, fresh):
                continue
            current_version = (
                self.storage.latest_version(stock_id, stored.trade_date, stored.source)
                or "1"
            )
            try:
                new_version = str(int(current_version) + 1)
            except ValueError:
                new_version = current_version + "-recheck"
            inserted = self.storage.update_bar(
                stock_id, stored.trade_date, stored.source, fresh, new_version
            )
            if inserted:
                updated += 1
                self._log(
                    RECHECK_UPDATED,
                    stock_id=stock_id,
                    trade_date=stored.trade_date,
                    source=stored.source,
                    old_version=current_version,
                    new_version=new_version,
                )
        return updated

    # ------------------------------------------------------------------ #
    # Kaynaklar arasi dogrulama
    # ------------------------------------------------------------------ #
    def validate_against(
        self, stock_id: str, date_str: str, primary_bar: PriceBar
    ) -> ValidationResult:
        """Dogrulama kaynagi (google) ile kapanis karsilastirmasi.

        - fark > close_tolerance_pct -> PRICE_SOURCE_DIVERGENCE (log+isaret)
        - dogrulama kaynagi ulasilamaz -> VALIDATION_SOURCE_UNAVAILABLE
          (dogrulama atlanir, isaretlenir)
        - tolerans icinde -> OK
        """
        date_str = str(date_str)
        ref_name = self.config.validation_source
        result = ValidationResult(
            stock_id=stock_id, trade_date=date_str, status=OK, reference_source=ref_name
        )

        def _unavailable(reason: str) -> ValidationResult:
            self._log(
                VALIDATION_SOURCE_UNAVAILABLE,
                stock_id=stock_id,
                trade_date=date_str,
                source=ref_name,
                reason=reason,
            )
            result.status = VALIDATION_SOURCE_UNAVAILABLE
            return result

        source = self.sources.get(ref_name)
        if source is None:
            return _unavailable("not_registered")
        try:
            ref_bar = source.fetch_date(stock_id, date_str)
        except Exception as exc:
            return _unavailable("%s: %s" % (type(exc).__name__, exc))
        if ref_bar is None:
            return _unavailable("no_bar")

        diff = close_diff_pct(primary_bar.close, ref_bar.close)
        result.diff_pct = diff
        if diff > self.config.close_tolerance_pct:
            self._log(
                PRICE_SOURCE_DIVERGENCE,
                stock_id=stock_id,
                trade_date=date_str,
                primary_source=primary_bar.source,
                reference_source=ref_name,
                primary_close=primary_bar.close,
                reference_close=ref_bar.close,
                diff_pct=diff,
                tolerance_pct=self.config.close_tolerance_pct,
            )
            result.status = PRICE_SOURCE_DIVERGENCE
        return result
