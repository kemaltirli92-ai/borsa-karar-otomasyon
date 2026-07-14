"""BLOK 16 - ApiRouter: yol eslestirme + method kontrolu + 404/405.

Handler duzeyinde calisir — gercek soket YOK. Request/Response duz
veri siniflari; uygulama (http.server) katmani bu yapiyi tasisir.

- register(method, pattern, handler, scope): pattern icinde {symbol} gibi
  yol parametreleri desteklenir.
- dispatch(request) -> Response: eslesme yoksa 404 NOT_FOUND JSON,
  yol var ama method yoksa 405 METHOD_NOT_ALLOWED JSON (+ Allow basligi).
- Handler ApiError/bilinmeyen istisna firlatirsa mask_exception ile
  guvenli JSON cevap uretilir (scope'a gore musteri/admin maskesi).

Mimari kural: frontend YALNIZCA bu API'yi kullanir; dogrudan yfinance /
KAP / TradingView / haber / DB baglantisi YASAK.

stdlib only; deterministik; gercek ag YOK.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from app.api.masking import (
    SCOPE_CUSTOMER,
    mask_exception,
    method_not_allowed,
    not_found,
)

CONTENT_TYPE_JSON = "application/json"

_PARAM_RE = re.compile(r"^\{([A-Za-z_][A-Za-z0-9_]*)\}$")


@dataclass
class Request:
    """Soketsiz istek modeli (handler duzeyi)."""

    method: str
    path: str
    query: Dict[str, Any] = field(default_factory=dict)
    headers: Dict[str, Any] = field(default_factory=dict)
    body: Optional[Dict[str, Any]] = None


@dataclass
class Response:
    """JSON cevap modeli; content_type isareti her zaman application/json."""

    status: int
    body: Dict[str, Any]
    headers: Dict[str, str] = field(default_factory=dict)
    content_type: str = CONTENT_TYPE_JSON


@dataclass
class _Route:
    method: str
    pattern: str
    segments: Tuple[str, ...]
    handler: Callable[..., Any]
    scope: str


def _split_path(path: str) -> Tuple[str, ...]:
    """Yolu segmentlere bol; query string ve tekrarli slash yok sayilir."""
    clean = path.split("?", 1)[0]
    return tuple(segment for segment in clean.split("/") if segment != "")


def _match_segments(pattern: Tuple[str, ...], path: Tuple[str, ...]) -> Optional[Dict[str, str]]:
    """Pattern/path eslesmesi; {param} segmentleri yol parametresi olur."""
    if len(pattern) != len(path):
        return None
    params: Dict[str, str] = {}
    for pat, got in zip(pattern, path):
        match = _PARAM_RE.match(pat)
        if match:
            params[match.group(1)] = got
        elif pat != got:
            return None
    return params


class ApiRouter:
    """Yol/method eslestiren dagitici (soketsiz)."""

    def __init__(self, error_ids: Any = None, error_log: Any = None) -> None:
        self._routes: List[_Route] = []
        self.error_ids = error_ids
        self.error_log = error_log

    # --- kayit ---------------------------------------------------------
    def register(
        self,
        method: str,
        pattern: str,
        handler: Callable[..., Any],
        scope: str = SCOPE_CUSTOMER,
    ) -> None:
        """(method, pattern) -> handler kaydi; cakisma ValueError."""
        method = method.upper()
        segments = _split_path(pattern)
        if not segments:
            raise ValueError("pattern bos olamaz")
        for route in self._routes:
            if route.method == method and route.segments == segments:
                raise ValueError(f"route zaten kayitli: {method} {pattern}")
        self._routes.append(_Route(method, pattern, segments, handler, scope))

    @property
    def routes(self) -> List[Tuple[str, str, str]]:
        """Kayitli (method, pattern, scope) listesi (denetim/test icin)."""
        return [(r.method, r.pattern, r.scope) for r in self._routes]

    # --- eslestirme -----------------------------------------------------
    def _match(
        self, method: str, path: str
    ) -> Tuple[Optional[_Route], Dict[str, str], Set[str]]:
        segments = _split_path(path)
        allowed: Set[str] = set()
        for route in self._routes:
            params = _match_segments(route.segments, segments)
            if params is None:
                continue
            if route.method == method:
                return route, params, allowed
            allowed.add(route.method)
        return None, {}, allowed

    # --- dagitim --------------------------------------------------------
    def dispatch(self, request: Request) -> Response:
        """Istegi handler'a dagitir; her zaman JSON Response dondurur."""
        method = (request.method or "").upper()
        route, path_params, allowed = self._match(method, request.path)

        if route is None:
            if allowed:
                status, body = mask_exception(method_not_allowed(), SCOPE_CUSTOMER)
                return Response(
                    status, body, headers={"Allow": ", ".join(sorted(allowed))}
                )
            status, body = mask_exception(not_found(), SCOPE_CUSTOMER)
            return Response(status, body)

        try:
            result = route.handler(request, **path_params)
            return self._coerce(result)
        except Exception as exc:  # noqa: BLE001 - guvenli maskeleme siniri
            status, body = mask_exception(
                exc, route.scope, self.error_ids, self.error_log
            )
            return Response(status, body)

    @staticmethod
    def _coerce(result: Any) -> Response:
        """Handler ciktisini Response'a cevirir (Response | (status,body) | body)."""
        if isinstance(result, Response):
            return result
        if isinstance(result, tuple) and len(result) == 2:
            status, body = result
            return Response(int(status), dict(body))
        if isinstance(result, dict):
            return Response(200, result)
        raise TypeError(f"handler donus tipi gecersiz: {type(result).__name__}")
