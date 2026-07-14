"""BLOK 16 - API ve Rapor Surumu paketi.

Web sitesi ve mobil uygulamanin TEK veri kaynagi: 10 musteri ucu +
7 yonetici ucu, zorunlu rapor zarfi, 12 liste parametresi, run
tutarliligi, yonetici kimlik dogrulama, musteri hata maskesi ve
OpenAPI 3.0.3 semasi.

Mimari kural: frontend YALNIZCA bu API'yi kullanir; dogrudan yfinance /
KAP / TradingView / haber / DB baglantisi YASAK.

stdlib only; gercek soket YOK (handler duzeyi); saat/sayac enjekte.
"""
from app.api.admin import AdminHandlers
from app.api.auth import ADMIN_TOKEN_HEADER, AdminAuth
from app.api.customer import CustomerHandlers
from app.api.envelope import (
    STATUS_FAILED,
    STATUS_OK,
    STATUS_PARTIAL,
    STATUS_STALE,
    STATUS_VALUES,
    ApiEnvelope,
    InvalidEnvelopeError,
    ReportVersion,
    RunMismatchError,
    build_envelope,
    list_envelope,
)
from app.api.filters import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    PARAMETER_NAMES,
    FilterParams,
    apply_filters,
    parse_params,
)
from app.api.masking import (
    ApiError,
    ErrorIdGenerator,
    mask_exception,
    publishable,
)
from app.api.openapi import FRONTEND_RULE_NOTE, OPENAPI_VERSION, build_openapi
from app.api.router import ApiRouter, Request, Response

__all__ = [
    "ADMIN_TOKEN_HEADER",
    "AdminAuth",
    "AdminHandlers",
    "ApiEnvelope",
    "ApiError",
    "ApiRouter",
    "CustomerHandlers",
    "DEFAULT_PAGE_SIZE",
    "ErrorIdGenerator",
    "FRONTEND_RULE_NOTE",
    "FilterParams",
    "InvalidEnvelopeError",
    "MAX_PAGE_SIZE",
    "OPENAPI_VERSION",
    "PARAMETER_NAMES",
    "ReportVersion",
    "Request",
    "Response",
    "RunMismatchError",
    "STATUS_FAILED",
    "STATUS_OK",
    "STATUS_PARTIAL",
    "STATUS_STALE",
    "STATUS_VALUES",
    "apply_filters",
    "build_envelope",
    "build_openapi",
    "list_envelope",
    "mask_exception",
    "parse_params",
    "publishable",
]
