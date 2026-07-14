"""BLOK 16 - OpenAPI 3.0.3 sema uretici (SPEC bolum 10).

build_openapi() -> dict: info, servers (VPS placeholder), paths
(10 musteri + 7 admin), components.schemas (ApiEnvelope, StockSummary,
ScanResult, PriceBar, KapNotification, NewsItem, CorporateAction,
Restriction, Pagination, Error), securitySchemes (AdminToken header).

Mimari kural (info.description'da sabit): frontend yalnizca bu API'yi
kullanir; dogrudan kaynak baglantisi yasak (yfinance/KAP/TradingView/
haber/DB). Semaya musteri disi kaynak URL'si (dogrudan yfinance/KAP
adresi) EKLENMEZ — yalnizca VPS placeholder server tanimlanir.

stdlib only; deterministik; gercek ag YOK.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.api.filters import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    PARAMETER_NAMES,
    SORT_DIRECTIONS,
    SORT_FIELDS,
)

OPENAPI_VERSION = "3.0.3"
API_TITLE = "XK100 Borsa Karar Otomasyonu API"
API_VERSION = "1.0.0"

# Mimari kural notu: info.description icine sabit yazilir (SPEC bolum 11).
FRONTEND_RULE_NOTE = (
    "frontend yalnizca bu API'yi kullanir; dogrudan kaynak baglantisi yasak"
)

_API_DESCRIPTION = (
    "VPS uzerinde calisan TEK veri kaynagi. Mimari kural: "
    + FRONTEND_RULE_NOTE
    + " (yfinance, KAP, TradingView, haber kaynaklari veya veritabanina "
    "istemci tarafindan dogrudan erisim YASAKTIR). Tum cevaplar zorunlu "
    "rapor zarfi (scan_run_id, report_version, last_updated_at, "
    "data_cutoff_at, status) ile doner."
)

_ENVELOPE_REF = {"$ref": "#/components/schemas/ApiEnvelope"}
_ERROR_REF = {"$ref": "#/components/schemas/Error"}

_SCAN_STATES_ENUM = [
    "WAITING",
    "COLLECTING_PRICE",
    "COLLECTING_KAP",
    "COLLECTING_NEWS",
    "COLLECTING_ACTIONS",
    "COLLECTING_RESTRICTIONS",
    "VALIDATING",
    "READY",
    "PARTIAL_DATA",
    "FAILED",
    "INACTIVE",
]


def _responses(*codes: str) -> Dict[str, Dict[str, Any]]:
    """Standart response kumesi: 200 zarf $ref, digerleri Error $ref."""
    responses: Dict[str, Dict[str, Any]] = {}
    for code in codes:
        if code == "200":
            responses[code] = {
                "description": "Basarili (zorunlu rapor zarfi)",
                "content": {"application/json": {"schema": dict(_ENVELOPE_REF)}},
            }
        else:
            responses[code] = {
                "description": {
                    "400": "Gecersiz parametre (INVALID_PARAMETER)",
                    "401": "Kimlik dogrulama gerekli (ADMIN_TOKEN_MISSING)",
                    "403": "Kimlik dogrulama basarisiz (ADMIN_TOKEN_INVALID)",
                    "404": "Kaynak bulunamadi (SYMBOL_NOT_FOUND / NOT_FOUND)",
                    "500": "Sunucu hatasi (INTERNAL_ERROR + error_id)",
                }[code],
                "content": {"application/json": {"schema": dict(_ERROR_REF)}},
            }
    return responses


def _symbol_param() -> Dict[str, Any]:
    return {
        "name": "symbol",
        "in": "path",
        "required": True,
        "schema": {"type": "string"},
        "description": "BIST hisse sembolu (ornegin THYAO)",
    }


def _list_query_params() -> List[Dict[str, Any]]:
    """12 liste parametresinin OpenAPI tanimlari."""
    return [
        {"name": "page", "in": "query", "schema": {"type": "integer", "minimum": 1, "default": 1}},
        {
            "name": "page_size",
            "in": "query",
            "schema": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_PAGE_SIZE,
                "default": DEFAULT_PAGE_SIZE,
            },
        },
        {"name": "search", "in": "query", "schema": {"type": "string", "maxLength": 64}},
        {"name": "sector", "in": "query", "schema": {"type": "string"}},
        {
            "name": "scan_status",
            "in": "query",
            "schema": {"type": "string", "enum": list(_SCAN_STATES_ENUM)},
        },
        {
            "name": "minimum_confidence",
            "in": "query",
            "schema": {"type": "number", "minimum": 0, "maximum": 100},
        },
        {"name": "has_kap", "in": "query", "schema": {"type": "string", "enum": ["true", "false"]}},
        {"name": "has_news", "in": "query", "schema": {"type": "string", "enum": ["true", "false"]}},
        {"name": "has_action", "in": "query", "schema": {"type": "string", "enum": ["true", "false"]}},
        {"name": "has_restriction", "in": "query", "schema": {"type": "string", "enum": ["true", "false"]}},
        {"name": "sort_by", "in": "query", "schema": {"type": "string", "enum": list(SORT_FIELDS)}},
        {
            "name": "sort_direction",
            "in": "query",
            "schema": {"type": "string", "enum": list(SORT_DIRECTIONS)},
        },
    ]


def _customer_op(
    summary: str,
    params: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    op: Dict[str, Any] = {
        "summary": summary,
        "tags": ["customer"],
        "responses": _responses("200", "400", "404", "500"),
    }
    if params:
        op["parameters"] = params
    return op


def _admin_op(
    summary: str,
    params: Optional[List[Dict[str, Any]]] = None,
    request_body: bool = False,
) -> Dict[str, Any]:
    op: Dict[str, Any] = {
        "summary": summary,
        "tags": ["admin"],
        "security": [{"AdminToken": []}],
        "responses": _responses("200", "400", "401", "403", "404", "500"),
    }
    if params:
        op["parameters"] = params
    if request_body:
        op["requestBody"] = {
            "required": True,
            "content": {
                "application/json": {"schema": {"type": "object"}}
            },
        }
    return op


def _build_paths() -> Dict[str, Any]:
    """10 musteri + 7 admin ucu (SPEC bolum 5-6)."""
    sym = [_symbol_param()]
    return {
        # --- musteri (10) ---
        "/api/stocks/universe/xk100": {
            "get": _customer_op("Aktif XK100 evren listesi")
        },
        "/api/stocks/{symbol}": {
            "get": _customer_op("Hisse ozeti", sym)
        },
        "/api/stocks/{symbol}/scan/latest": {
            "get": _customer_op("Son tarama sonucu (confidence dahil)", sym)
        },
        "/api/stocks/{symbol}/prices": {
            "get": _customer_op(
                "Fiyat serisi (varsayilan data_layer: validated/clean)",
                sym
                + [
                    {
                        "name": "data_layer",
                        "in": "query",
                        "schema": {
                            "type": "string",
                            "enum": ["validated", "all"],
                            "default": "validated",
                        },
                    }
                ],
            )
        },
        "/api/stocks/{symbol}/kap": {
            "get": _customer_op("KAP bildirimleri", sym)
        },
        "/api/stocks/{symbol}/news": {
            "get": _customer_op("Haberler (canonical dedupe)", sym)
        },
        "/api/stocks/{symbol}/corporate-actions": {
            "get": _customer_op("Kurumsal islemler", sym)
        },
        "/api/stocks/{symbol}/restrictions": {
            "get": _customer_op("Tedbirler", sym)
        },
        "/api/xk100/scan/latest": {
            "get": _customer_op("Endeks tarama ozeti")
        },
        "/api/xk100/stocks": {
            "get": _customer_op(
                "100 hisse listesi (12 parametre)", _list_query_params()
            )
        },
        # --- admin (7) ---
        "/api/admin/stock-scans/latest": {
            "get": _admin_op("Son run detayi (ham durumlar)")
        },
        "/api/admin/stock-scans/{run_id}": {
            "get": _admin_op(
                "Run detayi",
                [
                    {
                        "name": "run_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
            )
        },
        "/api/admin/stock-scans/run": {
            "post": _admin_op("Manuel tarama baslat (R1/R2 kurali BLOK 14)")
        },
        "/api/admin/stock-scans/{symbol}/rescan": {
            "post": _admin_op("Hisse yeniden tarama", sym)
        },
        "/api/admin/stock-universe/sync": {
            "post": _admin_op("Evren senkronu tetikle")
        },
        "/api/admin/symbols/{stock_id}": {
            "get": _admin_op(
                "Sembol eslestirme goruntule",
                [
                    {
                        "name": "stock_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
            ),
            "put": _admin_op(
                "Sembol eslestirme guncelle (audit)",
                [
                    {
                        "name": "stock_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                request_body=True,
            ),
        },
    }


def _build_schemas() -> Dict[str, Any]:
    """components.schemas (SPEC bolum 10 listesi)."""
    return {
        "ApiEnvelope": {
            "type": "object",
            "required": [
                "scan_run_id",
                "report_version",
                "last_updated_at",
                "data_cutoff_at",
                "status",
            ],
            "properties": {
                "scan_run_id": {"type": "string"},
                "report_version": {"type": "integer", "minimum": 1},
                "last_updated_at": {"type": "string", "format": "date-time"},
                "data_cutoff_at": {"type": "string", "format": "date-time"},
                "status": {
                    "type": "string",
                    "enum": ["OK", "PARTIAL", "FAILED", "STALE"],
                },
                "data": {"type": "object"},
                "items": {"type": "array", "items": {"type": "object"}},
                "pagination": {"$ref": "#/components/schemas/Pagination"},
            },
        },
        "StockSummary": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "name": {"type": "string"},
                "sector": {"type": "string"},
                "active": {"type": "boolean"},
                "last_updated": {"type": "string", "format": "date-time"},
            },
        },
        "ScanResult": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "scan_run_id": {"type": "string"},
                "scan_status": {"type": "string", "enum": list(_SCAN_STATES_ENUM)},
                "confidence": {"type": "number", "minimum": 0, "maximum": 100},
                "last_updated": {"type": "string", "format": "date-time"},
            },
        },
        "PriceBar": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "format": "date"},
                "open": {"type": "number"},
                "high": {"type": "number"},
                "low": {"type": "number"},
                "close": {"type": "number"},
                "volume": {"type": "integer"},
                "data_layer": {"type": "string"},
            },
        },
        "KapNotification": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "symbol": {"type": "string"},
                "title": {"type": "string"},
                "published_at": {"type": "string", "format": "date-time"},
            },
        },
        "NewsItem": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "symbol": {"type": "string"},
                "title": {"type": "string"},
                "source": {"type": "string"},
                "canonical": {"type": "boolean"},
            },
        },
        "CorporateAction": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "symbol": {"type": "string"},
                "action_type": {"type": "string"},
                "ex_date": {"type": "string", "format": "date"},
            },
        },
        "Restriction": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "symbol": {"type": "string"},
                "restriction_type": {"type": "string"},
                "start_date": {"type": "string", "format": "date"},
                "end_date": {"type": "string", "format": "date"},
            },
        },
        "Pagination": {
            "type": "object",
            "required": ["page", "page_size", "total", "total_pages"],
            "properties": {
                "page": {"type": "integer", "minimum": 1},
                "page_size": {"type": "integer", "minimum": 1, "maximum": MAX_PAGE_SIZE},
                "total": {"type": "integer", "minimum": 0},
                "total_pages": {"type": "integer", "minimum": 0},
            },
        },
        "Error": {
            "type": "object",
            "required": ["error"],
            "properties": {
                "error": {"type": "string"},
                "message": {"type": "string"},
                "field": {"type": "string"},
                "error_id": {"type": "string"},
            },
        },
    }


def build_openapi() -> Dict[str, Any]:
    """OpenAPI 3.0.3 belgesini uretir (JSON-serialize edilebilir dict)."""
    return {
        "openapi": OPENAPI_VERSION,
        "info": {
            "title": API_TITLE,
            "version": API_VERSION,
            "description": _API_DESCRIPTION,
        },
        "servers": [
            {
                "url": "https://vps-placeholder.invalid/api",
                "description": "VPS placeholder (gercek adres dagitimda ayarlanir)",
            }
        ],
        "paths": _build_paths(),
        "components": {
            "schemas": _build_schemas(),
            "securitySchemes": {
                "AdminToken": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-Admin-Token",
                    "description": "Yonetici token'i (env'den okunur; kodda sabit YOK)",
                }
            },
        },
    }


__all__ = [
    "OPENAPI_VERSION",
    "FRONTEND_RULE_NOTE",
    "PARAMETER_NAMES",
    "build_openapi",
]
