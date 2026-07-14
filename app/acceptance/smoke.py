"""BLOK 22 - Deployment sonrasi smoke suite (smoke.py).

SmokeSuite 8 kontrol calistirir:
  health_200, health_fields, summary_envelope_keys, pagination_25_of_100,
  admin_missing_token_401, admin_wrong_token_403, chart_format,
  api_contract_ok.

fetch_fn sozlesmesi: callable(method, path, headers=None) -> (status:int,
body:dict|str). Varsayilan fetch urllib tabanlidir ve YALNIZCA kullanici
VPS'te gercek deployment'a karsi calistirir; TESTLERDE ASLA kullanilmaz
(testlerde in-process Router dispatch'ine baglanir, BLOK 16 deseni).

Gercek ag bu modulun TEST akisinda YOKTUR; kontroller yalnizca enjekte
fetch_fn uzerinden akar. Sir/token hicbir kontrol govdesine yazilmaz
(admin token yalnizca istek basliginda tasinir).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

ENVELOPE_KEYS = (
    "scan_run_id",
    "report_version",
    "last_updated_at",
    "data_cutoff_at",
    "status",
)
HEALTH_KEYS = ("status", "version", "time", "uptime_s", "disk", "checks")
CHART_BAR_KEYS = ("date", "open", "high", "low", "close", "volume")

FetchFn = Callable[[str, str, Optional[Dict[str, str]]], Tuple[int, Any]]


@dataclass(frozen=True)
class SmokeCheck:
    """Tek smoke kontrolunun sonucu."""

    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class SmokeReport:
    """Tum smoke kontrollerinin ozeti."""

    ok: bool
    checks: Tuple[SmokeCheck, ...]
    base_url: str


def _default_fetch(base_url: str) -> FetchFn:
    """urllib tabanli gercek istemci (YALNIZ kullanici VPS'te calistirir).

    Testlerde ASLA kullanilmaz — testler fetch_fn'i enjekte eder.
    """

    def fetch(method: str, path: str, headers: Optional[Dict[str, str]] = None):
        url = base_url.rstrip("/") + path
        req = urllib.request.Request(url, method=method, headers=dict(headers or {}))
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                body = ""
            return exc.code, body

    return fetch


class SmokeSuite:
    """Deployment sonrasi 8 kontrolluk smoke suite."""

    def __init__(
        self,
        base_url: str,
        fetch_fn: Optional[FetchFn] = None,
        admin_token: Optional[str] = None,
    ):
        self.base_url = str(base_url)
        self._fetch = fetch_fn or _default_fetch(self.base_url)
        self._admin_token = admin_token

    # ------------------------------------------------------------------ #
    # Tek kontrol yardimcilari
    # ------------------------------------------------------------------ #
    def _check_health_200(self) -> SmokeCheck:
        status, _ = self._fetch("GET", "/health", None)
        ok = status == 200
        return SmokeCheck("health_200", ok, f"GET /health -> {status}")

    def _check_health_fields(self) -> SmokeCheck:
        status, body = self._fetch("GET", "/health", None)
        if status != 200 or not isinstance(body, dict):
            return SmokeCheck(
                "health_fields", False, f"beklenmeyen cevap: {status}"
            )
        missing = [k for k in HEALTH_KEYS if k not in body]
        ok = not missing and body.get("status") == "ok"
        return SmokeCheck(
            "health_fields",
            ok,
            "health alanlari tam"
            if ok
            else f"health alanlari eksik: {missing}",
        )

    def _first_symbol(self) -> Optional[str]:
        status, body = self._fetch("GET", "/api/stocks/universe/xk100", None)
        if status != 200 or not isinstance(body, dict):
            return None
        items = body.get("items") or body.get("data") or []
        if items and isinstance(items[0], dict):
            return items[0].get("symbol")
        return None

    def _check_summary_envelope(self, symbol: Optional[str]) -> SmokeCheck:
        if not symbol:
            return SmokeCheck(
                "summary_envelope_keys", False, "evren listesi bos"
            )
        status, body = self._fetch("GET", f"/api/stocks/{symbol}", None)
        if status != 200 or not isinstance(body, dict):
            return SmokeCheck(
                "summary_envelope_keys", False, f"ozet ucu {status}"
            )
        missing = [k for k in ENVELOPE_KEYS if k not in body]
        ok = not missing
        return SmokeCheck(
            "summary_envelope_keys",
            ok,
            "zarf anahtarlari tam" if ok else f"zarf eksik: {missing}",
        )

    def _check_pagination(self) -> SmokeCheck:
        status, body = self._fetch(
            "GET", "/api/xk100/stocks?page=1&page_size=25", None
        )
        if status != 200 or not isinstance(body, dict):
            return SmokeCheck("pagination_25_of_100", False, f"liste ucu {status}")
        page = body.get("pagination") or {}
        items = body.get("items") or []
        ok = (
            page.get("page") == 1
            and page.get("page_size") == 25
            and page.get("total") == 100
            and page.get("total_pages") == 4
            and len(items) == 25
        )
        return SmokeCheck(
            "pagination_25_of_100",
            ok,
            f"page={page.get('page')}/{page.get('total_pages')} total={page.get('total')}",
        )

    def _check_admin_missing_token(self) -> SmokeCheck:
        status, body = self._fetch("GET", "/api/admin/stock-scans/latest", None)
        ok = status == 401
        if ok and isinstance(body, dict):
            # token degeri govdeye SIZMAMALI
            ok = "token" not in json.dumps(body).lower() or "error" in body
        return SmokeCheck(
            "admin_missing_token_401", ok, f"tokensuz admin ucu -> {status}"
        )

    def _check_admin_wrong_token(self) -> SmokeCheck:
        status, _ = self._fetch(
            "GET",
            "/api/admin/stock-scans/latest",
            {"X-Admin-Token": "smoke-yanlis-token"},
        )
        ok = status == 403
        return SmokeCheck(
            "admin_wrong_token_403", ok, f"yanlis token admin ucu -> {status}"
        )

    def _check_chart_format(self, symbol: Optional[str]) -> SmokeCheck:
        if not symbol:
            return SmokeCheck("chart_format", False, "evren listesi bos")
        status, body = self._fetch("GET", f"/api/stocks/{symbol}/prices", None)
        if status != 200 or not isinstance(body, dict):
            return SmokeCheck("chart_format", False, f"prices ucu {status}")
        items = body.get("items") or []
        if not items:
            return SmokeCheck("chart_format", False, "fiyat serisi bos")
        ok = all(
            isinstance(bar, dict)
            and all(key in bar for key in CHART_BAR_KEYS)
            for bar in items
        )
        return SmokeCheck(
            "chart_format",
            ok,
            f"{len(items)} mum {CHART_BAR_KEYS} formatinda"
            if ok
            else "mum dizisi formati bozuk",
        )

    def _check_api_contract(self, symbol: Optional[str]) -> SmokeCheck:
        """Web/mobil ayni API sozlesmesi: farkli uclar ayni scan_run_id."""
        if not symbol:
            return SmokeCheck("api_contract_ok", False, "evren listesi bos")
        s1, b1 = self._fetch("GET", "/api/xk100/scan/latest", None)
        s2, b2 = self._fetch("GET", f"/api/stocks/{symbol}", None)
        if s1 != 200 or s2 != 200:
            return SmokeCheck(
                "api_contract_ok", False, f"uclusler {s1}/{s2}"
            )
        rid1 = b1.get("scan_run_id") if isinstance(b1, dict) else None
        rid2 = b2.get("scan_run_id") if isinstance(b2, dict) else None
        ok = bool(rid1) and rid1 == rid2
        return SmokeCheck(
            "api_contract_ok",
            ok,
            f"scan_run_id eslesmesi: {rid1}"
            if ok
            else f"scan_run_id uyusmazligi: {rid1!r} != {rid2!r}",
        )

    # ------------------------------------------------------------------ #
    # Toplu calistirma
    # ------------------------------------------------------------------ #
    def run_all(self) -> SmokeReport:
        """8 kontrolu sirayla calistirir (birinin hatasi digerini durdurmaz)."""
        checks = []
        checks.append(self._safe(self._check_health_200, "health_200"))
        checks.append(self._safe(self._check_health_fields, "health_fields"))
        symbol = self._first_symbol()
        checks.append(
            self._safe(lambda: self._check_summary_envelope(symbol),
                       "summary_envelope_keys")
        )
        checks.append(self._safe(self._check_pagination, "pagination_25_of_100"))
        checks.append(
            self._safe(self._check_admin_missing_token, "admin_missing_token_401")
        )
        checks.append(
            self._safe(self._check_admin_wrong_token, "admin_wrong_token_403")
        )
        checks.append(
            self._safe(lambda: self._check_chart_format(symbol), "chart_format")
        )
        checks.append(
            self._safe(lambda: self._check_api_contract(symbol), "api_contract_ok")
        )
        return SmokeReport(
            ok=all(check.ok for check in checks),
            checks=tuple(checks),
            base_url=self.base_url,
        )

    @staticmethod
    def _safe(fn: Callable[[], SmokeCheck], name: str) -> SmokeCheck:
        try:
            return fn()
        except Exception as exc:  # kontrol hatasi suite'i durdurmaz
            return SmokeCheck(name, False, f"kontrol hatasi: {exc}")
