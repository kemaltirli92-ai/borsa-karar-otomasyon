"""BLOK 16 - 10 musteri ucu handler'i (SPEC bolum 5).

Uclar (hepsi GET, hepsi zarfi cevap + publishable filtresi):
 1. /api/stocks/universe/xk100              -> aktif evren listesi
 2. /api/stocks/{symbol}                    -> hisse ozeti
 3. /api/stocks/{symbol}/scan/latest        -> son tarama (confidence dahil)
 4. /api/stocks/{symbol}/prices             -> fiyat serisi (vars. validated/clean)
 5. /api/stocks/{symbol}/kap                -> KAP bildirimleri
 6. /api/stocks/{symbol}/news               -> haberler (canonical dedupe)
 7. /api/stocks/{symbol}/corporate-actions  -> kurumsal islemler
 8. /api/stocks/{symbol}/restrictions       -> tedbirler
 9. /api/xk100/scan/latest                  -> endeks tarama ozeti
10. /api/xk100/stocks                       -> 100 hisse listesi (12 parametre)

Mimari kural: frontend YALNIZCA bu API'yi kullanir; dogrudan yfinance /
KAP / TradingView / haber / DB baglantisi YASAK — bu modulde hicbir dis
kaynak/veri toplayici importu YOKTUR. Tum veriler enjekte data_source
dict'inden okunur; bilinmeyen/pasif/evren-disi sembol -> 404
SYMBOL_NOT_FOUND (musteriye sizdirmaz).

stdlib only; gercek ag/soket YOK; saat/sayac enjekte.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from app.api.envelope import (
    STATUS_OK,
    STATUS_VALUES,
    ApiEnvelope,
)
from app.api.filters import FilterParams, apply_filters, parse_params
from app.api.masking import (
    CODE_INTERNAL,
    ApiError,
    not_found,
    publishable,
    symbol_not_found,
)
from app.api.router import Request, Response

INDEX_CODE = "xk100"


class CustomerHandlers:
    """Enjekte data_source uzerinden 10 musteri ucunun handler'lari.

    data_source (dict enjeksiyonu) beklenen anahtarlar:
      latest_run   : run kaydi {run_id, last_updated_at, data_cutoff_at,
                               [report_status]}
      universe     : aktif evren listesi [{symbol, name, sector, ...}]
      stocks       : {symbol: hisse ozeti dict}
      scans        : {symbol: son tarama dict (confidence dahil)}
      prices       : {symbol: [bar dict]}
      kap          : {symbol: [KAP bildirim dict]}
      news         : {symbol: [haber dict]}
      actions      : {symbol: [kurumsal islem dict]}
      restrictions : {symbol: [tedbir dict]}
      index_scan   : endeks tarama ozeti dict
      stock_rows   : listeleme satirlari (12 parametre ile filtrelenir)
    """

    def __init__(
        self,
        data_source: Dict[str, Any],
        version_provider: Any = None,
        strict_runs: bool = False,
    ) -> None:
        self.data_source = data_source
        self.envelope = ApiEnvelope(version_provider)
        self.strict_runs = strict_runs

    # --- data_source erisim yardimcilari --------------------------------
    def _ds(self, key: str, default: Any = None) -> Any:
        source = self.data_source
        if isinstance(source, dict):
            return source.get(key, default)
        getter = getattr(source, f"get_{key}", None)
        if callable(getter):
            return getter()
        return getattr(source, key, default)

    def _latest_run(self) -> Any:
        run = self._ds("latest_run")
        if run is None:
            raise ApiError(
                CODE_INTERNAL,
                "Servis verisi henuz hazir degil.",
                status=500,
            )
        return run

    def _run_status(self, run: Any) -> str:
        status = None
        if isinstance(run, dict):
            status = run.get("report_status") or run.get("envelope_status")
        else:
            status = getattr(run, "report_status", None) or getattr(
                run, "envelope_status", None
            )
        return status if status in STATUS_VALUES else STATUS_OK

    def _lookup(self, table: Optional[Dict[str, Any]], symbol: str) -> Any:
        """Sembol tablosunda buyuk/kucuk harf toleransli arama."""
        if not isinstance(table, dict):
            return None
        if symbol in table:
            return table[symbol]
        upper = symbol.upper()
        if upper in table:
            return table[upper]
        lower = symbol.lower()
        if lower in table:
            return table[lower]
        return None

    def _require_symbol(self, symbol: str) -> Dict[str, Any]:
        """Bilinmeyen/pasif/evren-disi sembol -> 404 SYMBOL_NOT_FOUND."""
        stock = self._lookup(self._ds("stocks"), symbol)
        if stock is None or not isinstance(stock, dict):
            raise symbol_not_found(symbol)
        if stock.get("active") is False:
            raise symbol_not_found(symbol)
        universe = self._ds("universe")
        if universe is not None:
            known = {
                str(entry.get("symbol"))
                for entry in universe
                if isinstance(entry, dict) and entry.get("symbol")
            }
            if known and stock.get("symbol") is not None:
                if str(stock.get("symbol")).upper() not in {k.upper() for k in known}:
                    raise symbol_not_found(symbol)
        return stock

    def _list_response(self, items: Sequence[Any]) -> Response:
        """Standart liste cevabi: publishable + list_envelope."""
        run = self._latest_run()
        clean = publishable(list(items))
        total = len(clean)
        page_meta = {
            "page": 1,
            "page_size": total if total else 1,
            "total": total,
            "total_pages": 1 if total else 0,
        }
        body = self.envelope.list(
            run, clean, page_meta, status=self._run_status(run)
        )
        return Response(200, body)

    # --- 1. evren --------------------------------------------------------
    def universe(self, request: Request) -> Response:
        return self._list_response(self._ds("universe") or [])

    # --- 2. hisse ozeti ---------------------------------------------------
    def stock_summary(self, request: Request, symbol: str) -> Response:
        stock = self._require_symbol(symbol)
        run = self._latest_run()
        body = self.envelope.build(
            run, publishable(stock), status=self._run_status(run)
        )
        return Response(200, body)

    # --- 3. son tarama -----------------------------------------------------
    def scan_latest(self, request: Request, symbol: str) -> Response:
        self._require_symbol(symbol)
        scan = self._lookup(self._ds("scans"), symbol)
        if scan is None:
            raise not_found()
        run = self._latest_run()
        body = self.envelope.build(
            run, publishable(scan), status=self._run_status(run)
        )
        return Response(200, body)

    # --- 4. fiyat serisi ----------------------------------------------------
    def prices(self, request: Request, symbol: str) -> Response:
        self._require_symbol(symbol)
        bars = self._lookup(self._ds("prices"), symbol) or []
        layer = (request.query.get("data_layer") or "validated")
        layer = str(layer).strip().lower()
        if layer == "all":
            items = list(bars)
        else:
            items = [
                bar
                for bar in bars
                if isinstance(bar, dict)
                and str(bar.get("data_layer", "validated")).lower()
                in ("validated", "clean")
            ]
        return self._list_response(items)

    # --- 5. KAP bildirimleri -------------------------------------------------
    def kap(self, request: Request, symbol: str) -> Response:
        self._require_symbol(symbol)
        return self._list_response(self._lookup(self._ds("kap"), symbol) or [])

    # --- 6. haberler (canonical dedupe) ---------------------------------------
    def news(self, request: Request, symbol: str) -> Response:
        self._require_symbol(symbol)
        items = self._lookup(self._ds("news"), symbol) or []
        canonical = [
            item
            for item in items
            if not isinstance(item, dict) or item.get("canonical", True)
        ]
        return self._list_response(canonical)

    # --- 7. kurumsal islemler --------------------------------------------------
    def corporate_actions(self, request: Request, symbol: str) -> Response:
        self._require_symbol(symbol)
        return self._list_response(self._lookup(self._ds("actions"), symbol) or [])

    # --- 8. tedbirler ------------------------------------------------------------
    def restrictions(self, request: Request, symbol: str) -> Response:
        self._require_symbol(symbol)
        return self._list_response(
            self._lookup(self._ds("restrictions"), symbol) or []
        )

    # --- 9. endeks tarama ozeti ---------------------------------------------------
    def index_scan_latest(self, request: Request) -> Response:
        index_scan = self._ds("index_scan")
        if index_scan is None:
            raise not_found()
        run = self._latest_run()
        body = self.envelope.build(
            run, publishable(index_scan), status=self._run_status(run)
        )
        return Response(200, body)

    # --- 10. 100 hisse listesi (12 parametre) ---------------------------------------
    def stocks_list(self, request: Request) -> Response:
        params = parse_params(request.query)
        rows = self._ds("stock_rows") or self._ds("universe") or []
        page_items, pagination = apply_filters(
            list(rows), params, strict=self.strict_runs
        )
        run = self._latest_run()
        body = self.envelope.list(
            run,
            publishable(page_items),
            pagination,
            status=self._run_status(run),
        )
        return Response(200, body)

    # --- router'a toplu kayit ----------------------------------------------------
    def register(self, router: Any) -> None:
        """10 musteri ucunu router'a kaydeder (scope=customer)."""
        router.register("GET", "/api/stocks/universe/xk100", self.universe)
        router.register("GET", "/api/stocks/{symbol}", self.stock_summary)
        router.register("GET", "/api/stocks/{symbol}/scan/latest", self.scan_latest)
        router.register("GET", "/api/stocks/{symbol}/prices", self.prices)
        router.register("GET", "/api/stocks/{symbol}/kap", self.kap)
        router.register("GET", "/api/stocks/{symbol}/news", self.news)
        router.register(
            "GET", "/api/stocks/{symbol}/corporate-actions", self.corporate_actions
        )
        router.register("GET", "/api/stocks/{symbol}/restrictions", self.restrictions)
        router.register("GET", "/api/xk100/scan/latest", self.index_scan_latest)
        router.register("GET", "/api/xk100/stocks", self.stocks_list)
