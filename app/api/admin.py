"""BLOK 16 - Yonetici uclari handler'i (SPEC bolum 6).

7 yonetici ucu (hepsi auth ZORUNLU + admin_audit_log kaydi):
 1. GET  /api/admin/stock-scans/latest        -> son run detayi (ham durumlar)
 2. GET  /api/admin/stock-scans/{run_id}      -> run detayi
 3. POST /api/admin/stock-scans/run           -> manuel tarama baslat
                                                 (R1/R2 kurali BLOK 14'e delege:
                                                 scan_runner enjeksiyonu)
 4. POST /api/admin/stock-scans/{symbol}/rescan -> hisse yeniden tarama
 5. POST /api/admin/stock-universe/sync       -> evren senkronu tetikle
 6. GET  /api/admin/symbols/{stock_id}        -> sembol eslestirme goruntule
 7. PUT  /api/admin/symbols/{stock_id}        -> sembol eslestirme guncelle + audit

Auth: AdminAuth enjeksiyonu — handler govdesinin ILK adimi; basarisizsa
audit yazilmaz. Audit: enjekte admin_audit_log (liste/.write/callable).
Admin cevaplari publishable filtresinden GECMEZ (ham durumlar gorulur);
secret sizintisi yalnizca hata maskeleme katmaninda engellenir.

stdlib only; gercek ag/soket YOK; saat enjekte (clock).
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from app.api.envelope import STATUS_OK, STATUS_VALUES, ApiEnvelope
from app.api.masking import (
    CODE_INTERNAL,
    ApiError,
    invalid_parameter,
    run_not_found,
    symbol_not_found,
)
from app.api.router import Request, Response


class AdminHandlers:
    """Enjekte data_source + auth + audit ile 7 yonetici ucu.

    data_source beklenen anahtarlar:
      latest_run       : son run kaydi (ham)
      runs             : {run_id: run kaydi}
      symbol_mappings  : {stock_id: eslestirme kaydi}

    Enjekte servisler (callable):
      scan_runner(trigger)        -> run kaydi/sonuc (R1/R2 kurali icte)
      rescan_runner(symbol)       -> yeniden tarama sonucu
      universe_sync()             -> senkron sonucu
      symbol_updater(stock_id, body) -> guncel eslestirme kaydi
    """

    def __init__(
        self,
        data_source: Dict[str, Any],
        auth: Any,
        audit_log: Any = None,
        version_provider: Any = None,
        clock: Optional[Callable[[], Any]] = None,
        scan_runner: Optional[Callable[..., Any]] = None,
        rescan_runner: Optional[Callable[..., Any]] = None,
        universe_sync: Optional[Callable[[], Any]] = None,
        symbol_updater: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.data_source = data_source
        self.auth = auth
        self.audit_log = audit_log
        self.clock = clock
        self.envelope = ApiEnvelope(version_provider)
        self.scan_runner = scan_runner
        self.rescan_runner = rescan_runner
        self.universe_sync = universe_sync
        self.symbol_updater = symbol_updater

    # --- yardimcilar ------------------------------------------------------
    def _ds(self, key: str, default: Any = None) -> Any:
        source = self.data_source
        if isinstance(source, dict):
            return source.get(key, default)
        getter = getattr(source, f"get_{key}", None)
        if callable(getter):
            return getter()
        return getattr(source, key, default)

    def _authenticate(self, request: Request) -> None:
        """Tum admin uclarinin ilk adimi: auth ZORUNLU."""
        if self.auth is None:
            raise ApiError(
                CODE_INTERNAL, "Yonetici kimlik dogrulama yapilandirilmamis.", 500
            )
        self.auth.authenticate(request.headers)

    def _audit(self, request: Request, action: str, detail: Any = None) -> None:
        """admin_audit_log'a kayit yazar (auth basarili sonrasi cagrilir)."""
        log = self.audit_log
        if log is None:
            return
        entry: Dict[str, Any] = {
            "endpoint": request.path,
            "method": (request.method or "").upper(),
            "action": action,
        }
        if detail is not None:
            entry["detail"] = detail
        if self.clock is not None:
            entry["timestamp"] = self.clock().isoformat()
        if hasattr(log, "write"):
            log.write(entry)
        elif hasattr(log, "append"):
            log.append(entry)
        elif callable(log):
            log(entry)

    def _latest_run(self) -> Any:
        run = self._ds("latest_run")
        if run is None:
            raise ApiError(CODE_INTERNAL, "Servis verisi henuz hazir degil.", 500)
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

    def _wrap(self, data: Any) -> Response:
        """Ham veriyi zarfla (publishable UYGULANMAZ - admin ham gorur)."""
        run = self._latest_run()
        body = self.envelope.build(run, data, status=self._run_status(run))
        return Response(200, body)

    def _lookup_run(self, run_id: str) -> Dict[str, Any]:
        runs = self._ds("runs") or {}
        run = runs.get(run_id) if isinstance(runs, dict) else None
        if run is None:
            raise run_not_found(run_id)
        return run

    def _lookup_mapping(self, stock_id: str) -> Dict[str, Any]:
        mappings = self._ds("symbol_mappings") or {}
        mapping = mappings.get(stock_id) if isinstance(mappings, dict) else None
        if mapping is None:
            raise symbol_not_found(stock_id)
        return mapping

    # --- 1. son run detayi (ham) ------------------------------------------
    def stock_scans_latest(self, request: Request) -> Response:
        self._authenticate(request)
        self._audit(request, "stock_scans_latest")
        return self._wrap(self._latest_run())

    # --- 2. run detayi ------------------------------------------------------
    def stock_scan_by_id(self, request: Request, run_id: str) -> Response:
        self._authenticate(request)
        run = self._lookup_run(run_id)
        self._audit(request, "stock_scan_by_id", {"run_id": run_id})
        body = self.envelope.build(run, run, status=self._run_status(run))
        return Response(200, body)

    # --- 3. manuel tarama baslat ---------------------------------------------
    def run_scan(self, request: Request) -> Response:
        self._authenticate(request)
        self._audit(request, "run_scan")
        if self.scan_runner is None:
            raise ApiError(CODE_INTERNAL, "Tarama motoru bagli degil.", 500)
        result = self.scan_runner(trigger="admin")
        return self._wrap(result)

    # --- 4. hisse yeniden tarama -----------------------------------------------
    def rescan(self, request: Request, symbol: str) -> Response:
        self._authenticate(request)
        self._audit(request, "rescan", {"symbol": symbol})
        if self.rescan_runner is None:
            raise ApiError(CODE_INTERNAL, "Yeniden tarama motoru bagli degil.", 500)
        result = self.rescan_runner(symbol)
        return self._wrap(result)

    # --- 5. evren senkronu --------------------------------------------------------
    def sync_universe(self, request: Request) -> Response:
        self._authenticate(request)
        self._audit(request, "sync_universe")
        if self.universe_sync is None:
            raise ApiError(CODE_INTERNAL, "Evren senkron servisi bagli degil.", 500)
        result = self.universe_sync()
        return self._wrap(result)

    # --- 6. sembol eslestirme goruntule ----------------------------------------------
    def symbol_get(self, request: Request, stock_id: str) -> Response:
        self._authenticate(request)
        mapping = self._lookup_mapping(stock_id)
        self._audit(request, "symbol_get", {"stock_id": stock_id})
        return self._wrap(mapping)

    # --- 7. sembol eslestirme guncelle -------------------------------------------------
    def symbol_put(self, request: Request, stock_id: str) -> Response:
        self._authenticate(request)
        mapping = self._lookup_mapping(stock_id)
        body = request.body
        if not isinstance(body, dict) or not body:
            raise invalid_parameter("body", "guncelleme govdesi zorunlu")
        self._audit(
            request,
            "symbol_put",
            {"stock_id": stock_id, "fields": sorted(body.keys())},
        )
        if self.symbol_updater is not None:
            updated = self.symbol_updater(stock_id, body)
        else:
            mapping.update(body)
            updated = mapping
        return self._wrap(updated)

    # --- router'a toplu kayit ----------------------------------------------------------
    def register(self, router: Any) -> None:
        """7 yonetici ucunu router'a kaydeder (scope=admin)."""
        router.register(
            "GET", "/api/admin/stock-scans/latest", self.stock_scans_latest, scope="admin"
        )
        router.register(
            "GET",
            "/api/admin/stock-scans/{run_id}",
            self.stock_scan_by_id,
            scope="admin",
        )
        router.register(
            "POST", "/api/admin/stock-scans/run", self.run_scan, scope="admin"
        )
        router.register(
            "POST",
            "/api/admin/stock-scans/{symbol}/rescan",
            self.rescan,
            scope="admin",
        )
        router.register(
            "POST", "/api/admin/stock-universe/sync", self.sync_universe, scope="admin"
        )
        router.register(
            "GET", "/api/admin/symbols/{stock_id}", self.symbol_get, scope="admin"
        )
        router.register(
            "PUT", "/api/admin/symbols/{stock_id}", self.symbol_put, scope="admin"
        )
