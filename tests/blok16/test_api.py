"""BLOK 16 - API ve Rapor Surumu: TAM 100 pytest testi.

Kategoriler (toplam = 100, SPEC BLOK 16 bolum 12):
1. Yetkilendirme: token eksik 401, yanlis 403, dogru 200, token sizintisi
   yok, musteri ucunda auth yok (14)
2. Sayfalama: page/page_size sinirlari, total_pages, bos sayfa (12)
3. Filtreleme: search/sector/scan_status/minimum_confidence/has_* (16)
4. Siralama: sort_by/direction, gecersiz deger 400 (10)
5. Run_id tutarliligi: zarf zorunlu alanlari, karisik run reddi,
   report_version artisi (14)
6. Hata maskesi: 500 INTERNAL_ERROR + error_id, stack/SQL/yol sizintisi
   yok, admin maske (14)
7. Uclar: 10 musteri + 7 admin ucu dogru yol/method/404/405 (12)
8. OpenAPI + yayinlanabilirlik + frontend kurali (8)

Hicbir test ag/soket erisimi yapmaz: handler duzeyi Request/Response,
data_source dict enjeksiyonu, saat enjekte (sabit 2024-06-28 10:00),
token/sayac enjekte. BLOK 6-15'e DOKUNULMAZ.
"""
from __future__ import annotations

import inspect
import json
import re
from datetime import datetime

import pytest

from app.api import customer as customer_mod
from app.api.admin import AdminHandlers
from app.api.auth import ADMIN_TOKEN_HEADER, AdminAuth
from app.api.customer import CustomerHandlers
from app.api.envelope import (
    STATUS_VALUES,
    InvalidEnvelopeError,
    ReportVersion,
    RunMismatchError,
    build_envelope,
    list_envelope,
)
from app.api.filters import DEFAULT_SCAN_STATES, FilterParams, apply_filters, parse_params
from app.api.masking import (
    ApiError,
    ErrorIdGenerator,
    find_admin_fields,
    mask_exception,
    publishable,
)
from app.api.openapi import FRONTEND_RULE_NOTE, OPENAPI_VERSION, build_openapi
from app.api.router import ApiRouter, Request, Response

# ---------------------------------------------------------------------- #
# Sabitler + fixture fabrikalari (deterministik; saat enjekte)
# ---------------------------------------------------------------------- #

NOW = datetime(2024, 6, 28, 10, 0, 0)
CUTOFF = "2024-06-28T09:40:00"  # 09:40 veri kesimi
RUN_ID = "2024-06-28-TARAMA-R1"
OLD_RUN_ID = "2024-06-27-TARAMA-R1"
GOOD_TOKEN = "enjekte-test-token-7f3a"
BAD_TOKEN = "yanlis-token-degeri-zzz"

CUSTOMER_PATHS = [
    "/api/stocks/universe/xk100",
    "/api/stocks/THYAO",
    "/api/stocks/THYAO/scan/latest",
    "/api/stocks/THYAO/prices",
    "/api/stocks/THYAO/kap",
    "/api/stocks/THYAO/news",
    "/api/stocks/THYAO/corporate-actions",
    "/api/stocks/THYAO/restrictions",
    "/api/xk100/scan/latest",
    "/api/xk100/stocks",
]

ADMIN_REQUESTS = [
    ("GET", "/api/admin/stock-scans/latest", None),
    ("GET", "/api/admin/stock-scans/" + RUN_ID, None),
    ("POST", "/api/admin/stock-scans/run", None),
    ("POST", "/api/admin/stock-scans/THYAO/rescan", None),
    ("POST", "/api/admin/stock-universe/sync", None),
    ("GET", "/api/admin/symbols/stk-1", None),
    ("PUT", "/api/admin/symbols/stk-1", {"sector": "Teknoloji"}),
]


def make_run(**overrides):
    run = {
        "run_id": RUN_ID,
        "last_updated_at": NOW,
        "data_cutoff_at": CUTOFF,
        "report_status": "OK",
        "scanned": 100,
    }
    run.update(overrides)
    return run


def make_rows(n=120):
    """12 parametre ile filtrelenebilir deterministik hisse satirlari."""
    special = [
        {
            "symbol": "THYAO",
            "name": "Turk Hava Yollari",
            "sector": "Tasimacilik",
            "scan_status": "READY",
            "confidence": 95.0,
            "has_kap": True,
            "has_news": True,
            "has_action": False,
            "has_restriction": False,
        },
        {
            "symbol": "ASELS",
            "name": "Aselsan Elektronik",
            "sector": "Teknoloji",
            "scan_status": "PARTIAL_DATA",
            "confidence": 61.0,
            "has_kap": False,
            "has_news": True,
            "has_action": True,
            "has_restriction": False,
        },
        {
            "symbol": "GARAN",
            "name": "Garanti Bankasi",
            "sector": "Bankacilik",
            "scan_status": "FAILED",
            "confidence": 12.0,
            "has_kap": True,
            "has_news": False,
            "has_action": False,
            "has_restriction": True,
        },
    ]
    rows = []
    for i in range(n):
        rows.append(
            {
                "symbol": f"X{i:03d}",
                "name": f"Sirket {i:03d} Holding",
                "sector": ["Teknoloji", "Bankacilik", "Enerji", "Gida"][i % 4],
                "scan_status": DEFAULT_SCAN_STATES[i % len(DEFAULT_SCAN_STATES)],
                "confidence": float((i * 7) % 101),
                "has_kap": i % 2 == 0,
                "has_news": i % 3 == 0,
                "has_action": i % 5 == 0,
                "has_restriction": i % 7 == 0,
                "last_updated": f"2024-06-28T09:{i % 60:02d}:00",
            }
        )
    all_rows = special + rows
    for row in all_rows:
        row["scan_run_id"] = RUN_ID
        row.setdefault("last_updated", "2024-06-28T09:45:00")
    return all_rows


def make_data_source(**overrides):
    ds = {
        "latest_run": make_run(),
        "universe": [
            {"symbol": "THYAO", "name": "Turk Hava Yollari", "sector": "Tasimacilik"},
            {"symbol": "ASELS", "name": "Aselsan Elektronik", "sector": "Teknoloji"},
            {"symbol": "GARAN", "name": "Garanti Bankasi", "sector": "Bankacilik"},
            {"symbol": "PASIF", "name": "Pasif Sirket", "sector": "Enerji"},
        ],
        "stocks": {
            "THYAO": {
                "symbol": "THYAO",
                "name": "Turk Hava Yollari",
                "sector": "Tasimacilik",
                "active": True,
                "internal_notes": "ic not - sizmamali",
                "admin_flag": True,
            },
            "ASELS": {"symbol": "ASELS", "name": "Aselsan", "sector": "Teknoloji", "active": True},
            "GARAN": {"symbol": "GARAN", "name": "Garanti", "sector": "Bankacilik", "active": True},
            "PASIF": {"symbol": "PASIF", "name": "Pasif Sirket", "sector": "Enerji", "active": False},
            "EVRENDISI": {"symbol": "EVRENDISI", "name": "Evren Disi", "sector": "Gida", "active": True},
        },
        "scans": {
            "THYAO": {
                "symbol": "THYAO",
                "scan_run_id": RUN_ID,
                "scan_status": "READY",
                "confidence": 92.5,
                "raw_error": "ham hata - sizmamali",
            }
        },
        "prices": {
            "THYAO": [
                {"date": "2024-06-25", "close": 298.0, "data_layer": "validated"},
                {"date": "2024-06-26", "close": 299.5, "data_layer": "clean"},
                {"date": "2024-06-27", "close": 300.0, "data_layer": "raw"},
            ]
        },
        "kap": {"THYAO": [{"id": "k1", "symbol": "THYAO", "title": "Bildirim 1"}]},
        "news": {
            "THYAO": [
                {"id": "n1", "symbol": "THYAO", "title": "Haber A", "canonical": True},
                {"id": "n2", "symbol": "THYAO", "title": "Haber B", "canonical": True},
                {"id": "n3", "symbol": "THYAO", "title": "Haber A kopya", "canonical": False},
            ]
        },
        "actions": {"THYAO": [{"id": "a1", "symbol": "THYAO", "action_type": "TEMETTU"}]},
        "restrictions": {"THYAO": [{"id": "r1", "symbol": "THYAO", "restriction_type": "VBTS"}]},
        "index_scan": {
            "scan_run_id": RUN_ID,
            "ready": 95,
            "failed": 5,
            "pending_review": 3,
        },
        "stock_rows": make_rows(),
        "runs": {RUN_ID: make_run(), OLD_RUN_ID: make_run(run_id=OLD_RUN_ID)},
        "symbol_mappings": {
            "stk-1": {"stock_id": "stk-1", "symbol": "THYAO", "verified": True}
        },
    }
    ds.update(overrides)
    return ds


def make_router(ds=None, audit=None, strict_runs=False):
    """Tam kayitli router + enjekte cagri kayitlari (deterministik)."""
    ds = ds if ds is not None else make_data_source()
    audit_log = audit if audit is not None else []
    calls = {"scan": [], "rescan": [], "sync": 0, "update": []}

    def scan_runner(trigger):
        calls["scan"].append(trigger)
        return {"trigger": trigger, "started": True}

    def rescan_runner(symbol):
        calls["rescan"].append(symbol)
        return {"symbol": symbol, "rescan": "scheduled"}

    def universe_sync():
        calls["sync"] += 1
        return {"synced": 100}

    router = ApiRouter(error_ids=ErrorIdGenerator())
    customer = CustomerHandlers(
        ds, version_provider=ReportVersion(), strict_runs=strict_runs
    )
    customer.register(router)
    admin = AdminHandlers(
        ds,
        AdminAuth(lambda: GOOD_TOKEN),
        audit_log=audit_log,
        version_provider=ReportVersion(),
        clock=lambda: NOW,
        scan_runner=scan_runner,
        rescan_runner=rescan_runner,
        universe_sync=universe_sync,
    )
    admin.register(router)
    return router, calls, audit_log


def admin_headers():
    return {ADMIN_TOKEN_HEADER: GOOD_TOKEN}


# ---------------------------------------------------------------------- #
# 1. Yetkilendirme (14 test)
# ---------------------------------------------------------------------- #

class TestYetkilendirme:
    def test_admin_token_eksik_401(self):
        router, _, _ = make_router()
        resp = router.dispatch(Request("GET", "/api/admin/stock-scans/latest"))
        assert resp.status == 401

    def test_admin_token_eksik_kod(self):
        router, _, _ = make_router()
        resp = router.dispatch(Request("GET", "/api/admin/stock-scans/latest"))
        assert resp.body["error"] == "ADMIN_TOKEN_MISSING"

    def test_admin_token_yanlis_403(self):
        router, _, _ = make_router()
        resp = router.dispatch(
            Request(
                "GET",
                "/api/admin/stock-scans/latest",
                headers={ADMIN_TOKEN_HEADER: BAD_TOKEN},
            )
        )
        assert resp.status == 403

    def test_admin_token_yanlis_kod(self):
        router, _, _ = make_router()
        resp = router.dispatch(
            Request(
                "GET",
                "/api/admin/stock-scans/latest",
                headers={ADMIN_TOKEN_HEADER: BAD_TOKEN},
            )
        )
        assert resp.body["error"] == "ADMIN_TOKEN_INVALID"

    def test_admin_token_dogru_200(self):
        router, _, _ = make_router()
        resp = router.dispatch(
            Request("GET", "/api/admin/stock-scans/latest", headers=admin_headers())
        )
        assert resp.status == 200
        assert resp.body["scan_run_id"] == RUN_ID

    def test_admin_401_govdesinde_token_sizintisi_yok(self):
        router, _, _ = make_router()
        resp = router.dispatch(Request("GET", "/api/admin/stock-scans/latest"))
        text = json.dumps(resp.body, ensure_ascii=False)
        assert GOOD_TOKEN not in text and BAD_TOKEN not in text

    def test_admin_403_yanlis_token_degeri_yanitta_yok(self):
        router, _, _ = make_router()
        resp = router.dispatch(
            Request(
                "GET",
                "/api/admin/stock-scans/latest",
                headers={ADMIN_TOKEN_HEADER: BAD_TOKEN},
            )
        )
        text = json.dumps(resp.body, ensure_ascii=False)
        assert BAD_TOKEN not in text
        assert GOOD_TOKEN not in text

    def test_header_buyuk_kucuk_harf_duyarsiz(self):
        router, _, _ = make_router()
        resp = router.dispatch(
            Request(
                "GET",
                "/api/admin/stock-scans/latest",
                headers={"x-admin-token": GOOD_TOKEN},
            )
        )
        assert resp.status == 200

    def test_bos_token_401(self):
        router, _, _ = make_router()
        resp = router.dispatch(
            Request(
                "GET",
                "/api/admin/stock-scans/latest",
                headers={ADMIN_TOKEN_HEADER: "   "},
            )
        )
        assert resp.status == 401
        assert resp.body["error"] == "ADMIN_TOKEN_MISSING"

    def test_7_admin_ucu_tokensuz_reddedilir(self):
        router, _, _ = make_router()
        for method, path, body in ADMIN_REQUESTS:
            resp = router.dispatch(Request(method, path, body=body))
            assert resp.status == 401, f"{method} {path} tokensuz reddedilmedi"

    def test_musteri_10_ucu_tokensuz_erisilebilir(self):
        router, _, _ = make_router()
        for path in CUSTOMER_PATHS:
            resp = router.dispatch(Request("GET", path))
            assert resp.status == 200, f"{path} musteri icin acik olmali"

    def test_musteri_ucunda_auth_basligi_gerekmez(self):
        router, _, _ = make_router()
        resp = router.dispatch(Request("GET", "/api/stocks/THYAO", headers={}))
        assert resp.status == 200
        assert "error" not in resp.body

    def test_auth_basarisizda_audit_yazilmaz(self):
        router, _, audit = make_router()
        router.dispatch(Request("GET", "/api/admin/stock-scans/latest"))
        router.dispatch(
            Request(
                "GET",
                "/api/admin/stock-scans/latest",
                headers={ADMIN_TOKEN_HEADER: BAD_TOKEN},
            )
        )
        assert audit == []

    def test_auth_basarili_islemler_auditlenir(self):
        router, _, audit = make_router()
        for method, path, body in ADMIN_REQUESTS:
            router.dispatch(Request(method, path, headers=admin_headers(), body=body))
        assert len(audit) == len(ADMIN_REQUESTS)
        assert all(entry["endpoint"].startswith("/api/admin/") for entry in audit)
        assert all(entry["timestamp"] == NOW.isoformat() for entry in audit)


# ---------------------------------------------------------------------- #
# 2. Sayfalama (12 test)
# ---------------------------------------------------------------------- #

class TestSayfalama:
    def _list(self, router, **query):
        return router.dispatch(Request("GET", "/api/xk100/stocks", query=query))

    def test_varsayilan_page_1_page_size_50(self):
        router, _, _ = make_router()
        resp = self._list(router)
        assert resp.status == 200
        pagination = resp.body["pagination"]
        assert pagination["page"] == 1
        assert pagination["page_size"] == 50
        assert len(resp.body["items"]) == 50

    def test_page_size_siniri_200_kabul(self):
        router, _, _ = make_router()
        resp = self._list(router, page_size="200")
        assert resp.status == 200
        assert resp.body["pagination"]["page_size"] == 200
        assert len(resp.body["items"]) == resp.body["pagination"]["total"]

    def test_page_size_201_reddedilir_400(self):
        router, _, _ = make_router()
        resp = self._list(router, page_size="201")
        assert resp.status == 400
        assert resp.body["error"] == "INVALID_PARAMETER"
        assert resp.body["field"] == "page_size"

    def test_page_size_0_reddedilir_400(self):
        router, _, _ = make_router()
        resp = self._list(router, page_size="0")
        assert resp.status == 400
        assert resp.body["field"] == "page_size"

    def test_page_0_reddedilir_400(self):
        router, _, _ = make_router()
        resp = self._list(router, page="0")
        assert resp.status == 400
        assert resp.body["error"] == "INVALID_PARAMETER"
        assert resp.body["field"] == "page"

    def test_page_negatif_reddedilir_400(self):
        router, _, _ = make_router()
        resp = self._list(router, page="-2")
        assert resp.status == 400
        assert resp.body["field"] == "page"

    def test_page_size_sayisal_olmayan_400(self):
        router, _, _ = make_router()
        resp = self._list(router, page_size="elli")
        assert resp.status == 400
        assert resp.body["field"] == "page_size"

    def test_total_pages_hesap_dogru(self):
        router, _, _ = make_router()
        resp = self._list(router, page_size="50")
        pagination = resp.body["pagination"]
        assert pagination["total"] == 123  # 3 ozel + 120 uretilmis
        assert pagination["total_pages"] == 3

    def test_son_sayfa_kismi_doluluk(self):
        router, _, _ = make_router()
        resp = self._list(router, page="3", page_size="50")
        assert resp.status == 200
        assert len(resp.body["items"]) == 23

    def test_asiri_sayfa_bos_items(self):
        router, _, _ = make_router()
        resp = self._list(router, page="99")
        assert resp.status == 200
        assert resp.body["items"] == []
        assert resp.body["pagination"]["total"] == 123

    def test_bos_liste_pagination_sifir(self):
        router, _, _ = make_router()
        resp = self._list(router, search="hic-boyle-sembol-yok")
        assert resp.status == 200
        pagination = resp.body["pagination"]
        assert pagination["total"] == 0
        assert pagination["total_pages"] == 0
        assert resp.body["items"] == []

    def test_pagination_4_alan_tam(self):
        router, _, _ = make_router()
        resp = self._list(router, page="2", page_size="10")
        pagination = resp.body["pagination"]
        assert set(pagination) == {"page", "page_size", "total", "total_pages"}
        assert pagination["page"] == 2
        assert pagination["page_size"] == 10


# ---------------------------------------------------------------------- #
# 3. Filtreleme (16 test)
# ---------------------------------------------------------------------- #

class TestFiltreleme:
    def _list(self, router, **query):
        query.setdefault("page_size", "200")
        return router.dispatch(Request("GET", "/api/xk100/stocks", query=query))

    def test_search_sembol_eslesmesi(self):
        router, _, _ = make_router()
        resp = self._list(router, search="THYAO")
        assert resp.status == 200
        symbols = [item["symbol"] for item in resp.body["items"]]
        assert symbols == ["THYAO"]

    def test_search_unvan_eslesmesi(self):
        router, _, _ = make_router()
        resp = self._list(router, search="Garanti")
        names = [item["name"] for item in resp.body["items"]]
        assert names == ["Garanti Bankasi"]

    def test_search_buyuk_kucuk_harf_duyarsiz(self):
        router, _, _ = make_router()
        resp = self._list(router, search="asels")
        assert [item["symbol"] for item in resp.body["items"]] == ["ASELS"]

    def test_search_kelime_siniri_asimi_400(self):
        router, _, _ = make_router()
        resp = self._list(router, search="bir iki uc dort bes alti")
        assert resp.status == 400
        assert resp.body["error"] == "INVALID_PARAMETER"
        assert resp.body["field"] == "search"

    def test_sector_filtresi(self):
        router, _, _ = make_router()
        resp = self._list(router, sector="Bankacilik")
        sectors = {item["sector"] for item in resp.body["items"]}
        assert sectors == {"Bankacilik"}
        assert resp.body["pagination"]["total"] == 31  # GARAN + 120/4

    def test_sector_eslesmezse_bos(self):
        router, _, _ = make_router()
        resp = self._list(router, sector="OlmayanSektor")
        assert resp.status == 200
        assert resp.body["items"] == []
        assert resp.body["pagination"]["total"] == 0

    def test_scan_status_filtresi(self):
        router, _, _ = make_router()
        resp = self._list(router, scan_status="READY")
        statuses = {item["scan_status"] for item in resp.body["items"]}
        assert statuses == {"READY"}
        assert resp.body["pagination"]["total"] >= 1

    def test_scan_status_gecersiz_400(self):
        router, _, _ = make_router()
        resp = self._list(router, scan_status="BOZUK_DURUM")
        assert resp.status == 400
        assert resp.body["field"] == "scan_status"

    def test_minimum_confidence_filtresi(self):
        router, _, _ = make_router()
        resp = self._list(router, minimum_confidence="90")
        confidences = [item["confidence"] for item in resp.body["items"]]
        assert confidences
        assert all(c >= 90 for c in confidences)
        assert any(c >= 95 for c in confidences)  # THYAO 95 dahil

    def test_minimum_confidence_sinir_0_ve_100_kabul(self):
        router, _, _ = make_router()
        resp0 = self._list(router, minimum_confidence="0")
        assert resp0.status == 200
        assert resp0.body["pagination"]["total"] == 123
        resp100 = self._list(router, minimum_confidence="100")
        assert resp100.status == 200
        assert all(
            item["confidence"] >= 100 for item in resp100.body["items"]
        )

    def test_minimum_confidence_101_reddedilir_400(self):
        router, _, _ = make_router()
        resp = self._list(router, minimum_confidence="101")
        assert resp.status == 400
        assert resp.body["field"] == "minimum_confidence"

    def test_minimum_confidence_negatif_reddedilir_400(self):
        router, _, _ = make_router()
        resp = self._list(router, minimum_confidence="-5")
        assert resp.status == 400
        assert resp.body["field"] == "minimum_confidence"

    def test_has_kap_true_filtresi(self):
        router, _, _ = make_router()
        resp = self._list(router, has_kap="true")
        assert resp.status == 200
        assert all(item["has_kap"] is True for item in resp.body["items"])
        assert resp.body["pagination"]["total"] == 62  # THYAO+GARAN + 60

    def test_has_news_false_filtresi(self):
        router, _, _ = make_router()
        resp = self._list(router, has_news="false")
        assert resp.status == 200
        assert all(item["has_news"] is False for item in resp.body["items"])

    def test_has_action_ve_restriction_kombinasyon(self):
        router, _, _ = make_router()
        resp = self._list(router, has_action="true", has_restriction="true")
        assert resp.status == 200
        for item in resp.body["items"]:
            assert item["has_action"] is True
            assert item["has_restriction"] is True
        # yalnizca i%5==0 ve i%7==0 (i%35==0): X000,X035,X070,X105
        symbols = {item["symbol"] for item in resp.body["items"]}
        assert symbols == {"X000", "X035", "X070", "X105"}

    def test_has_parametre_gecersiz_deger_400(self):
        router, _, _ = make_router()
        resp = self._list(router, has_kap="evet")
        assert resp.status == 400
        assert resp.body["error"] == "INVALID_PARAMETER"
        assert resp.body["field"] == "has_kap"


# ---------------------------------------------------------------------- #
# 4. Siralama (10 test)
# ---------------------------------------------------------------------- #

class TestSiralama:
    def _symbols(self, router, **query):
        query.setdefault("page_size", "200")
        resp = router.dispatch(Request("GET", "/api/xk100/stocks", query=query))
        assert resp.status == 200, resp.body
        return [item["symbol"] for item in resp.body["items"]]

    def test_sort_by_symbol_asc_varsayilan(self):
        router, _, _ = make_router()
        symbols = self._symbols(router)
        assert symbols == sorted(symbols)
        assert symbols[0] == "ASELS"

    def test_sort_by_symbol_desc(self):
        router, _, _ = make_router()
        symbols = self._symbols(router, sort_by="symbol", sort_direction="desc")
        assert symbols == sorted(symbols, reverse=True)
        assert symbols[0] == "X119"

    def test_sort_by_confidence_desc(self):
        router, _, _ = make_router()
        resp = router.dispatch(
            Request(
                "GET",
                "/api/xk100/stocks",
                query={"page_size": "200", "sort_by": "confidence", "sort_direction": "desc"},
            )
        )
        confidences = [item["confidence"] for item in resp.body["items"]]
        assert confidences == sorted(confidences, reverse=True)
        assert confidences[0] == 100.0  # X072: (72*7)%101 = 100 en yuksek
        assert 95.0 in confidences  # THYAO listede

    def test_sort_by_scan_status(self):
        router, _, _ = make_router()
        resp = router.dispatch(
            Request(
                "GET",
                "/api/xk100/stocks",
                query={"page_size": "200", "sort_by": "scan_status"},
            )
        )
        statuses = [item["scan_status"] for item in resp.body["items"]]
        assert statuses == sorted(statuses)

    def test_sort_by_sector(self):
        router, _, _ = make_router()
        resp = router.dispatch(
            Request(
                "GET",
                "/api/xk100/stocks",
                query={"page_size": "200", "sort_by": "sector"},
            )
        )
        sectors = [item["sector"] for item in resp.body["items"]]
        assert sectors == sorted(sectors)

    def test_sort_by_last_updated(self):
        router, _, _ = make_router()
        resp = router.dispatch(
            Request(
                "GET",
                "/api/xk100/stocks",
                query={"page_size": "200", "sort_by": "last_updated", "sort_direction": "desc"},
            )
        )
        stamps = [item["last_updated"] for item in resp.body["items"]]
        assert stamps == sorted(stamps, reverse=True)

    def test_sort_by_gecersiz_400(self):
        router, _, _ = make_router()
        resp = router.dispatch(
            Request("GET", "/api/xk100/stocks", query={"sort_by": "piyasa_degeri"})
        )
        assert resp.status == 400
        assert resp.body["error"] == "INVALID_PARAMETER"
        assert resp.body["field"] == "sort_by"

    def test_sort_direction_gecersiz_400(self):
        router, _, _ = make_router()
        resp = router.dispatch(
            Request(
                "GET",
                "/api/xk100/stocks",
                query={"sort_by": "symbol", "sort_direction": "yukari"},
            )
        )
        assert resp.status == 400
        assert resp.body["field"] == "sort_direction"

    def test_none_confidence_her_zaman_sonda(self):
        items = [
            {"symbol": "A", "confidence": None, "scan_run_id": RUN_ID},
            {"symbol": "B", "confidence": 50.0, "scan_run_id": RUN_ID},
            {"symbol": "C", "confidence": 10.0, "scan_run_id": RUN_ID},
        ]
        asc, _ = apply_filters(
            items, FilterParams(sort_by="confidence", sort_direction="asc")
        )
        desc, _ = apply_filters(
            items, FilterParams(sort_by="confidence", sort_direction="desc")
        )
        assert asc[-1]["symbol"] == "A"
        assert desc[-1]["symbol"] == "A"

    def test_esit_degerlerde_symbol_ikincil_anahtar(self):
        items = [
            {"symbol": "Z", "confidence": 50.0, "scan_run_id": RUN_ID},
            {"symbol": "A", "confidence": 50.0, "scan_run_id": RUN_ID},
            {"symbol": "M", "confidence": 50.0, "scan_run_id": RUN_ID},
        ]
        page, _ = apply_filters(
            items, FilterParams(sort_by="confidence", sort_direction="asc")
        )
        assert [item["symbol"] for item in page] == ["A", "M", "Z"]


# ---------------------------------------------------------------------- #
# 5. Run_id tutarliligi (14 test)
# ---------------------------------------------------------------------- #

ZORUNLU_ZARF_ALANLARI = {
    "scan_run_id",
    "report_version",
    "last_updated_at",
    "data_cutoff_at",
    "status",
}


class TestRunIdTutarliligi:
    def test_tum_musteri_uclarinda_zarf_zorunlu_alanlar(self):
        router, _, _ = make_router()
        for path in CUSTOMER_PATHS:
            resp = router.dispatch(Request("GET", path))
            assert resp.status == 200
            assert ZORUNLU_ZARF_ALANLARI <= set(resp.body), path
            assert resp.body["scan_run_id"] == RUN_ID
            assert resp.body["status"] in STATUS_VALUES

    def test_report_version_int_tipte(self):
        router, _, _ = make_router()
        resp = router.dispatch(Request("GET", "/api/stocks/THYAO"))
        assert isinstance(resp.body["report_version"], int)

    def test_report_version_artan(self):
        router, _, _ = make_router()
        v1 = router.dispatch(Request("GET", "/api/stocks/THYAO")).body["report_version"]
        v2 = router.dispatch(Request("GET", "/api/stocks/THYAO")).body["report_version"]
        v3 = router.dispatch(Request("GET", "/api/xk100/stocks")).body["report_version"]
        assert v1 < v2 < v3

    def test_build_envelope_enjekte_surum_artan(self):
        provider = ReportVersion(start=41)
        run = make_run()
        e1 = build_envelope(run, {"a": 1}, version_provider=provider)
        e2 = build_envelope(run, {"a": 2}, version_provider=provider)
        assert e1["report_version"] == 42
        assert e2["report_version"] == 43

    def test_build_envelope_dict_run_mismatch(self):
        with pytest.raises(RunMismatchError) as err:
            build_envelope(make_run(), {"scan_run_id": OLD_RUN_ID, "x": 1})
        assert err.value.code == "RUN_MISMATCH"
        assert err.value.envelope_run_id == RUN_ID
        assert err.value.data_run_id == OLD_RUN_ID

    def test_build_envelope_liste_run_mismatch(self):
        data = [
            {"scan_run_id": RUN_ID, "symbol": "A"},
            {"scan_run_id": OLD_RUN_ID, "symbol": "B"},
        ]
        with pytest.raises(RunMismatchError):
            build_envelope(make_run(), data)

    def test_list_envelope_karisik_run_reddedilir(self):
        items = [
            {"scan_run_id": RUN_ID, "symbol": "A"},
            {"scan_run_id": OLD_RUN_ID, "symbol": "B"},
        ]
        page_meta = {"page": 1, "page_size": 50, "total": 2, "total_pages": 1}
        with pytest.raises(RunMismatchError):
            list_envelope(make_run(), items, page_meta)

    def test_apply_filters_karisik_run_son_run_a_hizalanir(self):
        items = [
            {"symbol": "ESKI", "scan_run_id": OLD_RUN_ID},
            {"symbol": "YENI1", "scan_run_id": RUN_ID},
            {"symbol": "YENI2", "scan_run_id": RUN_ID},
        ]
        page, pagination = apply_filters(items)
        assert {item["symbol"] for item in page} == {"YENI1", "YENI2"}
        assert pagination["total"] == 2

    def test_apply_filters_strict_karisik_run_raise(self):
        items = [
            {"symbol": "ESKI", "scan_run_id": OLD_RUN_ID},
            {"symbol": "YENI", "scan_run_id": RUN_ID},
        ]
        with pytest.raises(RunMismatchError):
            apply_filters(items, strict=True)

    def test_status_degerlerinin_hepsi_kabul(self):
        run = make_run()
        for status in STATUS_VALUES:
            body = build_envelope(run, {"x": 1}, status=status)
            assert body["status"] == status
        assert set(STATUS_VALUES) == {"OK", "PARTIAL", "FAILED", "STALE"}

    def test_status_gecersiz_reddedilir(self):
        with pytest.raises(InvalidEnvelopeError):
            build_envelope(make_run(), {"x": 1}, status="BOZUK")

    def test_musteri_liste_cevabinda_items_tek_run_id(self):
        router, _, _ = make_router()
        resp = router.dispatch(Request("GET", "/api/xk100/stocks", query={"page_size": "200"}))
        assert resp.status == 200
        run_ids = {item.get("scan_run_id") for item in resp.body["items"]}
        assert run_ids == {RUN_ID}
        assert resp.body["scan_run_id"] == RUN_ID

    def test_data_cutoff_at_0940_kesim_tasinir(self):
        router, _, _ = make_router()
        resp = router.dispatch(Request("GET", "/api/stocks/THYAO"))
        assert resp.body["data_cutoff_at"] == CUTOFF
        assert "09:40" in resp.body["data_cutoff_at"]
        assert resp.body["last_updated_at"] == NOW.isoformat()

    def test_list_envelope_pagination_alanlari_zorunlu(self):
        with pytest.raises(InvalidEnvelopeError):
            list_envelope(make_run(), [], {"page": 1, "page_size": 50})


# ---------------------------------------------------------------------- #
# 6. Hata maskesi (14 test)
# ---------------------------------------------------------------------- #

class TestHataMaskesi:
    def test_bilinmeyen_hata_500_internal_error(self):
        # last_updated_at bozuk (int) -> zarf uretimi patlar -> 500 maskeli
        ds = make_data_source(latest_run=make_run(last_updated_at=12345))
        router, _, _ = make_router(ds=ds)
        resp = router.dispatch(Request("GET", "/api/stocks/THYAO"))
        assert resp.status == 500
        assert resp.body["error"] == "INTERNAL_ERROR"

    def test_500_cevabinda_error_id_var(self):
        ds = make_data_source(latest_run=make_run(last_updated_at=12345))
        router, _, _ = make_router(ds=ds)
        resp = router.dispatch(Request("GET", "/api/stocks/THYAO"))
        assert re.fullmatch(r"ERR-\d{6}", resp.body["error_id"])

    def test_error_id_deterministik_artan(self):
        ids = ErrorIdGenerator()
        s1, b1 = mask_exception(RuntimeError("x"), "customer", ids)
        s2, b2 = mask_exception(RuntimeError("y"), "customer", ids)
        assert (s1, s2) == (500, 500)
        assert b1["error_id"] == "ERR-000001"
        assert b2["error_id"] == "ERR-000002"

    def test_stack_sizintisi_yok(self):
        status, body = mask_exception(RuntimeError("boom"), "customer")
        text = json.dumps(body, ensure_ascii=False)
        assert "Traceback" not in text and "File " not in text
        assert status == 500

    def test_dosya_yolu_sizintisi_yok(self):
        _, body = mask_exception(
            OSError("/var/lib/app/secret/config.yaml okunamadi"), "customer"
        )
        text = json.dumps(body, ensure_ascii=False)
        assert "/var" not in text and ".yaml" not in text

    def test_sql_sizintisi_yok(self):
        _, body = mask_exception(
            RuntimeError("SELECT * FROM admin_tokens WHERE id=1 failed"), "customer"
        )
        text = json.dumps(body, ensure_ascii=False)
        assert "SELECT" not in text and "admin_tokens" not in text

    def test_kaynak_url_sizintisi_yok(self):
        _, body = mask_exception(
            ConnectionError("https://query1.finance.yahoo.com/v8 timeout"),
            "customer",
        )
        text = json.dumps(body, ensure_ascii=False)
        assert "http" not in text and "yahoo" not in text

    def test_ham_exception_mesaji_sizintisi_yok(self):
        mesaj = "cok gizli ic hata detayi 42"
        _, body = mask_exception(ValueError(mesaj), "customer")
        assert mesaj not in json.dumps(body, ensure_ascii=False)
        assert set(body) == {"error", "error_id"}

    def test_bilinen_kod_kontrollu_mesaj(self):
        err = ApiError("INVALID_PARAMETER", "Gecersiz parametre: page", 400, field="page")
        status, body = mask_exception(err, "customer")
        assert status == 400
        assert body == {
            "error": "INVALID_PARAMETER",
            "message": "Gecersiz parametre: page",
            "field": "page",
        }

    def test_symbol_not_found_kontrollu_404(self):
        router, _, _ = make_router()
        resp = router.dispatch(Request("GET", "/api/stocks/YOKBOYLESYMBOL"))
        assert resp.status == 404
        assert resp.body["error"] == "SYMBOL_NOT_FOUND"
        assert "message" in resp.body

    def test_admin_bilinmeyen_hata_detail_maskeli(self):
        ds = make_data_source()

        def patlayan_runner(trigger):
            raise RuntimeError("DB password=gizli123 ile baglanti koptu")

        router = ApiRouter(error_ids=ErrorIdGenerator())
        admin = AdminHandlers(
            ds,
            AdminAuth(lambda: GOOD_TOKEN),
            audit_log=[],
            scan_runner=patlayan_runner,
        )
        admin.register(router)
        resp = router.dispatch(
            Request("POST", "/api/admin/stock-scans/run", headers=admin_headers())
        )
        assert resp.status == 500
        assert resp.body["error"] == "INTERNAL_ERROR"
        assert "gizli123" not in json.dumps(resp.body)
        assert "password=***" in resp.body["detail"]

    def test_admin_hata_token_degeri_maskeli(self):
        ds = make_data_source()

        def patlayan_sync():
            raise RuntimeError(f"X-Admin-Token={GOOD_TOKEN} reddedildi")

        router = ApiRouter(error_ids=ErrorIdGenerator())
        admin = AdminHandlers(
            ds,
            AdminAuth(lambda: GOOD_TOKEN),
            audit_log=[],
            universe_sync=patlayan_sync,
        )
        admin.register(router)
        resp = router.dispatch(
            Request("POST", "/api/admin/stock-universe/sync", headers=admin_headers())
        )
        text = json.dumps(resp.body)
        assert GOOD_TOKEN not in text
        assert "X-Admin-Token=***" in resp.body["detail"]

    def test_publishable_ic_ice_admin_alanlari_cikarilir(self):
        data = {
            "symbol": "THYAO",
            "internal_notes": "not",
            "raw_error": "hata",
            "debug": {"trace": 1},
            "pending_review": True,
            "admin_flag": 1,
            "nested": {"debug": 2, "ok": 3, "items": [{"raw_error": "e", "keep": 1}]},
        }
        clean = publishable(data)
        assert clean == {"symbol": "THYAO", "nested": {"ok": 3, "items": [{"keep": 1}]}}
        assert "internal_notes" in data  # orijinal dokunulmadi
        assert find_admin_fields(clean) == []

    def test_error_log_gercek_hata_ile_eslesir(self):
        logs = []
        ids = ErrorIdGenerator()
        _, body = mask_exception(
            RuntimeError("gizli"), "customer", ids, error_log=logs.append
        )
        assert len(logs) == 1
        assert logs[0]["error_id"] == body["error_id"]
        assert "gizli" in logs[0]["exception_repr"]  # logda var, cevapta yok


# ---------------------------------------------------------------------- #
# 7. Uclar (12 test)
# ---------------------------------------------------------------------- #

class TestUclar:
    def test_10_musteri_ucu_dogru_yol_method_200(self):
        router, _, _ = make_router()
        for path in CUSTOMER_PATHS:
            resp = router.dispatch(Request("GET", path))
            assert resp.status == 200, f"{path} -> {resp.status}"
            assert resp.content_type == "application/json"

    def test_7_admin_ucu_dogru_tokenla_200(self):
        router, calls, _ = make_router()
        for method, path, body in ADMIN_REQUESTS:
            resp = router.dispatch(
                Request(method, path, headers=admin_headers(), body=body)
            )
            assert resp.status == 200, f"{method} {path} -> {resp.status}: {resp.body}"
        assert calls["scan"] == ["admin"]
        assert calls["rescan"] == ["THYAO"]
        assert calls["sync"] == 1

    def test_bilinmeyen_yol_404_not_found(self):
        router, _, _ = make_router()
        resp = router.dispatch(Request("GET", "/api/olmayan/yol"))
        assert resp.status == 404
        assert resp.body["error"] == "NOT_FOUND"

    def test_method_uyusmazligi_405_allow_basligi(self):
        router, _, _ = make_router()
        resp = router.dispatch(Request("DELETE", "/api/stocks/THYAO"))
        assert resp.status == 405
        assert resp.body["error"] == "METHOD_NOT_ALLOWED"
        assert "GET" in resp.headers.get("Allow", "")

    def test_musteri_ucunda_post_405(self):
        router, _, _ = make_router()
        resp = router.dispatch(Request("POST", "/api/xk100/stocks"))
        assert resp.status == 405
        assert resp.body["error"] == "METHOD_NOT_ALLOWED"

    def test_bilinmeyen_sembol_404_symbol_not_found(self):
        router, _, _ = make_router()
        resp = router.dispatch(Request("GET", "/api/stocks/ZZZZZ"))
        assert resp.status == 404
        assert resp.body["error"] == "SYMBOL_NOT_FOUND"

    def test_pasif_hisse_404_sizdirmaz(self):
        router, _, _ = make_router()
        resp = router.dispatch(Request("GET", "/api/stocks/PASIF"))
        assert resp.status == 404
        assert resp.body["error"] == "SYMBOL_NOT_FOUND"
        assert "Pasif" not in json.dumps(resp.body, ensure_ascii=False)

    def test_evren_disi_hisse_404(self):
        router, _, _ = make_router()
        resp = router.dispatch(Request("GET", "/api/stocks/EVRENDISI"))
        assert resp.status == 404
        assert resp.body["error"] == "SYMBOL_NOT_FOUND"

    def test_prices_varsayilan_validated_clean_filtresi(self):
        router, _, _ = make_router()
        resp = router.dispatch(Request("GET", "/api/stocks/THYAO/prices"))
        layers = [item["data_layer"] for item in resp.body["items"]]
        assert layers == ["validated", "clean"]  # raw elendi
        resp_all = router.dispatch(
            Request("GET", "/api/stocks/THYAO/prices", query={"data_layer": "all"})
        )
        assert len(resp_all.body["items"]) == 3

    def test_scan_latest_confidence_dahil(self):
        router, _, _ = make_router()
        resp = router.dispatch(Request("GET", "/api/stocks/THYAO/scan/latest"))
        assert resp.status == 200
        data = resp.body["data"]
        assert data["confidence"] == 92.5
        assert data["scan_status"] == "READY"
        assert "raw_error" not in data  # publishable filtresi

    def test_news_canonical_dedupe(self):
        router, _, _ = make_router()
        resp = router.dispatch(Request("GET", "/api/stocks/THYAO/news"))
        ids = [item["id"] for item in resp.body["items"]]
        assert ids == ["n1", "n2"]  # canonical=False elendi

    def test_admin_run_bilinmeyen_404_run_not_found(self):
        router, _, _ = make_router()
        resp = router.dispatch(
            Request(
                "GET",
                "/api/admin/stock-scans/2099-01-01-TARAMA-R9",
                headers=admin_headers(),
            )
        )
        assert resp.status == 404
        assert resp.body["error"] == "RUN_NOT_FOUND"


# ---------------------------------------------------------------------- #
# 8. OpenAPI + yayinlanabilirlik + frontend kurali (8 test)
# ---------------------------------------------------------------------- #

BEKLENEN_SEMALAR = {
    "ApiEnvelope",
    "StockSummary",
    "ScanResult",
    "PriceBar",
    "KapNotification",
    "NewsItem",
    "CorporateAction",
    "Restriction",
    "Pagination",
    "Error",
}


class TestOpenApiVeYayinlanabilirlik:
    def test_openapi_surum_ve_info(self):
        spec = build_openapi()
        assert spec["openapi"] == "3.0.3"
        assert OPENAPI_VERSION == "3.0.3"
        assert spec["info"]["title"]
        assert spec["info"]["version"]
        assert spec["servers"][0]["url"].startswith("https://")

    def test_paths_10_musteri_7_admin_operasyon(self):
        spec = build_openapi()
        customer_ops = 0
        admin_ops = 0
        for path, methods in spec["paths"].items():
            for method, op in methods.items():
                if path.startswith("/api/admin/"):
                    admin_ops += 1
                else:
                    customer_ops += 1
        assert customer_ops == 10
        assert admin_ops == 7
        assert len(spec["paths"]) == 16  # symbols ucu get+put birlesik

    def test_schemas_tam_10_ad(self):
        spec = build_openapi()
        schemas = spec["components"]["schemas"]
        assert BEKLENEN_SEMALAR <= set(schemas)
        env = schemas["ApiEnvelope"]
        assert set(env["required"]) == {
            "scan_run_id",
            "report_version",
            "last_updated_at",
            "data_cutoff_at",
            "status",
        }
        assert env["properties"]["status"]["enum"] == ["OK", "PARTIAL", "FAILED", "STALE"]

    def test_security_scheme_admin_token_header(self):
        spec = build_openapi()
        scheme = spec["components"]["securitySchemes"]["AdminToken"]
        assert scheme["type"] == "apiKey"
        assert scheme["in"] == "header"
        assert scheme["name"] == "X-Admin-Token"
        admin_get = spec["paths"]["/api/admin/stock-scans/latest"]["get"]
        assert admin_get["security"] == [{"AdminToken": []}]

    def test_info_description_frontend_kurali(self):
        spec = build_openapi()
        description = spec["info"]["description"]
        assert FRONTEND_RULE_NOTE in description
        assert (
            "frontend yalnizca bu API'yi kullanir; dogrudan kaynak baglantisi yasak"
            in description
        )

    def test_semada_musteri_disi_kaynak_url_yok(self):
        spec = build_openapi()
        text = json.dumps(spec, ensure_ascii=False)
        urls = re.findall(r"https?://[^\"'\s]+", text)
        assert urls, "placeholder server URL bekleniyor"
        for url in urls:
            lowered = url.lower()
            assert "yahoo" not in lowered
            assert "yfinance" not in lowered
            assert "kap.gov.tr" not in lowered
            assert "tradingview" not in lowered
            assert "placeholder" in lowered  # yalnizca VPS placeholder

    def test_musteri_cevaplari_publishable_temiz(self):
        router, _, _ = make_router()
        for path in CUSTOMER_PATHS:
            resp = router.dispatch(Request("GET", path))
            assert resp.status == 200
            leaks = find_admin_fields(resp.body)
            assert leaks == [], f"{path} admin alani sizdirdi: {leaks}"
        # kaynak veri bozulmadi mi?
        ds_stock = make_data_source()["stocks"]["THYAO"]
        assert "internal_notes" in ds_stock and "admin_flag" in ds_stock

    def test_musteri_handler_dis_kaynak_importu_yok_ve_zarf_ref(self):
        source = inspect.getsource(customer_mod)
        import_lines = [
            line.strip()
            for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))
        ]
        yasakli = ("yfinance", "requests", "urllib", "http.client", "socket", "sqlite3")
        for line in import_lines:
            for modul in yasakli:
                assert modul not in line, f"yasakli import: {line}"
        spec = build_openapi()
        for path, methods in spec["paths"].items():
            for method, op in methods.items():
                ref = op["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
                assert ref == "#/components/schemas/ApiEnvelope", f"{method} {path}"
