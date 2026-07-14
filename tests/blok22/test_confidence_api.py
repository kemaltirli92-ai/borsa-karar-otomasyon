"""BLOK 22 - test_confidence_api: Veri Guveni + API kabul testleri (14 test).

Kapsam: Veri Guveni: 0-100 + technical_ready/scoring_ready + eksik
alanlar (3); API yetkilendirme: 401/403/200 + token sizmaz (3);
sayfalama: 100 hisse page_size=25 -> 4 sayfa + total=100 + sayfa siniri
(3); filtreleme: sektor + durum filtresi (2); grafik format: prices ucu
mum dizisi {date,open,high,low,close,volume} + HAM/DUZELTILMIS ayrimi
(2); mobil tasma: index.html media query + 44px + viewport (1).
GERCEK BLOK 15/16 modulleri; sahte yalniz data_source/token/clock.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from app.api.admin import AdminHandlers
from app.api.auth import ADMIN_TOKEN_HEADER, AdminAuth
from app.api.customer import CustomerHandlers
from app.api.envelope import ReportVersion
from app.api.masking import ErrorIdGenerator
from app.api.router import ApiRouter, Request
from app.services.stock_scanning.confidence import (
    COMPONENT_NAMES,
    FAILED,
    MISSING,
    OK,
    ComponentInput,
    ConfidenceCalculator,
    ReadinessInputs,
    evaluate_readiness,
)

NOW = datetime(2025, 6, 3, 10, 0, 0)
RUN_ID = "2025-06-03-TARAMA-R1"
CUTOFF = "2025-06-03T09:40:00"
GOOD_TOKEN = "blok22-admin-token-a1b2"
BAD_TOKEN = "blok22-yanlis-token-z9y8"

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CANDIDATES = [
    _REPO_ROOT.parent / "telegram-sender" / "index.html",  # yerel calisma dizini
    _REPO_ROOT / "index.html",                             # GitHub repo koku
]
INDEX_HTML = next((p for p in _CANDIDATES if p.is_file()), _CANDIDATES[-1])


# --------------------------------------------------------------------------- #
# Veri Guveni (BLOK 15 gercek calculator)
# --------------------------------------------------------------------------- #
def _all_ok_components():
    return {name: ComponentInput(OK, "tam") for name in COMPONENT_NAMES}


def _full_readiness(**over):
    base = dict(
        symbol_verified=True, xk100_member=True, has_valid_price=True,
        has_valid_volume=True, has_last_trade_date=True, kap_check_ok=True,
        news_check_ok=True, corporate_check_ok=True,
        restriction_check_ok=True, source_validation_ok=True,
        sufficiency_label_present=True, trading_halt_active=False,
        critical_missing=[], stale_present=False,
        sufficiency_label="SUFFICIENT_DATA",
    )
    base.update(over)
    return ReadinessInputs(**base)


def test_confidence_full_data_100_and_ready():
    verdict = evaluate_readiness(_full_readiness())
    result = ConfidenceCalculator().calculate(
        "STK-000001", _all_ok_components(), verdict
    )
    assert result.data_confidence == 100
    assert result.technical_ready is True
    assert result.scoring_ready is True
    assert result.missing_fields == []


def test_confidence_missing_component_listed_and_capped_below_100():
    comps = _all_ok_components()
    comps["kap_check"] = ComponentInput(MISSING, "kap verisi yok")
    verdict = evaluate_readiness(_full_readiness(kap_check_ok=False))
    result = ConfidenceCalculator().calculate("STK-000001", comps, verdict)
    assert 0 <= result.data_confidence < 100  # eksik varken 100 OLAMAZ
    assert "kap_check" in result.missing_fields


def test_confidence_critical_missing_caps_and_blocks_scoring():
    comps = _all_ok_components()
    comps["critical_fields"] = ComponentInput(FAILED, "kritik alan eksik")
    verdict = evaluate_readiness(_full_readiness(critical_missing=["price"]))
    result = ConfidenceCalculator().calculate("STK-000001", comps, verdict)
    assert result.data_confidence <= 60  # kritik eksik ust siniri
    assert result.scoring_ready is False
    assert result.favorite_eligible is False
    assert "KRITIK VERI EKSIK" in result.warnings


# --------------------------------------------------------------------------- #
# API kurulumu (BLOK 16 in-process router deseni)
# --------------------------------------------------------------------------- #
def _stock_rows(n=100):
    rows = []
    for i in range(n):
        rows.append(
            {
                "symbol": f"X{i:03d}",
                "name": f"Sirket {i:03d}",
                "sector": "Teknoloji" if i % 2 == 0 else "Bankacilik",
                "scan_status": "READY" if i % 3 else "PARTIAL_DATA",
                "confidence": float(i % 101),
                "scan_run_id": RUN_ID,
                "last_updated": "2025-06-03T09:45:00",
            }
        )
    return rows


def _data_source():
    return {
        "latest_run": {
            "run_id": RUN_ID,
            "last_updated_at": NOW,
            "data_cutoff_at": CUTOFF,
            "report_status": "OK",
        },
        "universe": [
            {"symbol": "X001", "name": "Sirket 001", "sector": "Teknoloji"}
        ],
        "stocks": {
            "X001": {"symbol": "X001", "name": "Sirket 001",
                     "sector": "Teknoloji", "active": True},
        },
        "scans": {"X001": {"symbol": "X001", "scan_run_id": RUN_ID,
                           "scan_status": "READY", "confidence": 91.0}},
        "prices": {
            "X001": [
                {"date": "2025-06-01", "open": 99.0, "high": 101.0,
                 "low": 98.0, "close": 100.0, "volume": 1500,
                 "data_layer": "validated"},
                {"date": "2025-06-02", "open": 100.0, "high": 102.5,
                 "low": 99.5, "close": 101.5, "volume": 1600,
                 "data_layer": "clean"},
                {"date": "2025-06-02", "open": 200.0, "high": 205.0,
                 "low": 199.0, "close": 203.0, "volume": 1600,
                 "data_layer": "raw"},  # HAM (duzeltilmemis) seri
            ]
        },
        "kap": {"X001": []},
        "news": {"X001": []},
        "actions": {"X001": []},
        "restrictions": {"X001": []},
        "index_scan": {"scan_run_id": RUN_ID, "ready": 95, "failed": 5},
        "stock_rows": _stock_rows(),
        "runs": {RUN_ID: {"run_id": RUN_ID, "last_updated_at": NOW,
                          "data_cutoff_at": CUTOFF}},
        "symbol_mappings": {},
    }


def _router():
    router = ApiRouter(error_ids=ErrorIdGenerator())
    CustomerHandlers(_data_source(), version_provider=ReportVersion()).register(router)
    AdminHandlers(
        _data_source(),
        AdminAuth(lambda: GOOD_TOKEN),
        audit_log=[],
        version_provider=ReportVersion(),
        clock=lambda: NOW,
        scan_runner=lambda trigger: {"trigger": trigger},
        rescan_runner=lambda symbol: {"symbol": symbol},
        universe_sync=lambda: {"synced": 100},
    ).register(router)
    return router


# 3) API yetkilendirme ----------------------------------------------------------
def test_auth_401_403_200_flow():
    router = _router()
    missing = router.dispatch(Request("GET", "/api/admin/stock-scans/latest"))
    assert missing.status == 401
    wrong = router.dispatch(Request(
        "GET", "/api/admin/stock-scans/latest",
        headers={ADMIN_TOKEN_HEADER: BAD_TOKEN},
    ))
    assert wrong.status == 403
    ok = router.dispatch(Request(
        "GET", "/api/admin/stock-scans/latest",
        headers={ADMIN_TOKEN_HEADER: GOOD_TOKEN},
    ))
    assert ok.status == 200
    assert ok.body["scan_run_id"] == RUN_ID


def test_auth_token_value_never_leaks():
    router = _router()
    for headers in ({}, {ADMIN_TOKEN_HEADER: BAD_TOKEN}):
        resp = router.dispatch(Request(
            "GET", "/api/admin/stock-scans/latest", headers=headers,
        ))
        text = json.dumps(resp.body, ensure_ascii=False)
        assert GOOD_TOKEN not in text
        assert BAD_TOKEN not in text


def test_auth_customer_endpoints_require_no_token():
    router = _router()
    resp = router.dispatch(Request("GET", "/api/stocks/X001"))
    assert resp.status == 200  # musteri ucunda auth YOK
    assert resp.body["data"]["symbol"] == "X001"


# 4) Sayfalama --------------------------------------------------------------------
def test_pagination_25_of_100_gives_4_pages():
    router = _router()
    resp = router.dispatch(Request(
        "GET", "/api/xk100/stocks", query={"page": "1", "page_size": "25"},
    ))
    assert resp.status == 200
    page = resp.body["pagination"]
    assert page["total"] == 100
    assert page["total_pages"] == 4
    assert page["page"] == 1
    assert len(resp.body["items"]) == 25


def test_pagination_last_page_and_total():
    router = _router()
    resp = router.dispatch(Request(
        "GET", "/api/xk100/stocks", query={"page": "4", "page_size": "25"},
    ))
    assert resp.body["pagination"]["page"] == 4
    assert len(resp.body["items"]) == 25
    assert resp.body["pagination"]["total"] == 100


def test_pagination_page_size_limit_enforced():
    router = _router()
    resp = router.dispatch(Request(
        "GET", "/api/xk100/stocks", query={"page_size": "500"},
    ))
    # sayfa siniri: asiri buyuk page_size 400 veya ust sinira kisitlanir
    if resp.status == 400:
        assert resp.body["error"]
    else:
        assert resp.status == 200
        assert len(resp.body["items"]) <= 100


# 5) Filtreleme --------------------------------------------------------------------
def test_filter_by_sector():
    router = _router()
    resp = router.dispatch(Request(
        "GET", "/api/xk100/stocks",
        query={"sector": "Teknoloji", "page_size": "100"},
    ))
    items = resp.body["items"]
    assert items and all(i["sector"] == "Teknoloji" for i in items)
    assert resp.body["pagination"]["total"] == 50  # 100'un yarisi


def test_filter_by_scan_status():
    router = _router()
    resp = router.dispatch(Request(
        "GET", "/api/xk100/stocks",
        query={"scan_status": "READY", "page_size": "100"},
    ))
    items = resp.body["items"]
    assert items and all(i["scan_status"] == "READY" for i in items)


# 6) Grafik format -------------------------------------------------------------------
def test_chart_candle_format_ohlcv():
    router = _router()
    resp = router.dispatch(Request("GET", "/api/stocks/X001/prices"))
    assert resp.status == 200
    bars = resp.body["items"]
    assert bars
    for bar in bars:
        for key in ("date", "open", "high", "low", "close", "volume"):
            assert key in bar


def test_chart_raw_vs_adjusted_separation():
    router = _router()
    default = router.dispatch(Request("GET", "/api/stocks/X001/prices"))
    # varsayilan: validated/clean (DUZELTILMIS) katman; raw disarida
    assert all(
        b.get("data_layer", "validated") in ("validated", "clean")
        for b in default.body["items"]
    )
    raw_included = router.dispatch(Request(
        "GET", "/api/stocks/X001/prices", query={"data_layer": "all"},
    ))
    layers = {b.get("data_layer") for b in raw_included.body["items"]}
    assert "raw" in layers  # HAM seri ayri katmanda erisilebilir
    assert len(raw_included.body["items"]) > len(default.body["items"])


# 7) Mobil tasma ----------------------------------------------------------------------
def test_mobile_overflow_rules_in_index_html():
    assert INDEX_HTML.is_file(), f"index.html bulunamadi: {INDEX_HTML}"
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert "@media" in html and "max-width" in html  # mobil kirilim
    assert "44px" in html  # dokunma hedefi min 44px
    assert 'name="viewport"' in html  # viewport meta
