"""BLOK 22 - test_smoke: smoke suite kabul testleri (8 test).

Kapsam: health_200+alanlar; zarf anahtarlari; sayfalama 25/100; admin
401 + yanlis 403; grafik format; SmokeReport.ok + tum SmokeCheck
kayitlari; api_contract kontrolu; SmokeCheck kayit yapisi (name/ok/
detail). Tum kontroller ENJEKTE fetch_fn ile calisir — fetch_fn
in-process Router dispatch'ine baglanir (BLOK 16 Request/Response
deseni); gercek ag YOK.
"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import parse_qs, urlsplit

from app.acceptance.smoke import SmokeSuite
from app.api.admin import AdminHandlers
from app.api.auth import AdminAuth
from app.api.customer import CustomerHandlers
from app.api.envelope import ReportVersion
from app.api.health import HealthHandlers
from app.api.masking import ErrorIdGenerator
from app.api.router import ApiRouter, Request
from tests.blok22.test_confidence_api import _data_source

NOW = datetime(2025, 6, 3, 10, 0, 0)
GOOD_TOKEN = "blok22-smoke-token-q7w7"
BASE_URL = "https://xk100.example.tr"


def _build_router():
    """Musteri + admin + health uclari kayitli in-process router."""
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
    HealthHandlers(
        clock=lambda: NOW,
        disk_stat_provider=lambda path: (100, 40, 60),  # %40 dolu, OK
        version="1.0.0",
        started_at=datetime(2025, 6, 3, 8, 0, 0),
    ).register(router)
    return router


def _in_process_fetch(router):
    """fetch_fn(method, path, headers) -> (status, body) — Router dispatch."""

    def fetch(method, path, headers=None):
        split = urlsplit(path)
        query = {
            key: values[0]
            for key, values in parse_qs(split.query).items()
        }
        resp = router.dispatch(
            Request(method, split.path, query=query, headers=dict(headers or {}))
        )
        return resp.status, resp.body

    return fetch


def _suite():
    router = _build_router()
    return SmokeSuite(
        BASE_URL, fetch_fn=_in_process_fetch(router), admin_token=GOOD_TOKEN
    )


def _check(suite, name):
    report = suite.run_all()
    return next(c for c in report.checks if c.name == name), report


# 1) health_200 + alanlar ---------------------------------------------------------
def test_health_200_and_fields():
    suite = _suite()
    health_200, _ = _check(suite, "health_200")
    health_fields, _ = _check(suite, "health_fields")
    assert health_200.ok is True
    assert health_fields.ok is True


# 2) zarf anahtarlari ----------------------------------------------------------------
def test_summary_envelope_keys():
    check, _ = _check(_suite(), "summary_envelope_keys")
    assert check.ok is True, check.detail


# 3) sayfalama 25/100 -------------------------------------------------------------------
def test_pagination_25_of_100():
    check, _ = _check(_suite(), "pagination_25_of_100")
    assert check.ok is True, check.detail


# 4) admin 401 + yanlis 403 ----------------------------------------------------------------
def test_admin_401_missing_and_403_wrong_token():
    suite = _suite()
    missing, _ = _check(suite, "admin_missing_token_401")
    wrong, _ = _check(suite, "admin_wrong_token_403")
    assert missing.ok is True
    assert wrong.ok is True


# 5) grafik format ---------------------------------------------------------------------------
def test_chart_format_check():
    check, _ = _check(_suite(), "chart_format")
    assert check.ok is True, check.detail


# 6) SmokeReport.ok + tum kayitlar ----------------------------------------------------------------
def test_smoke_report_ok_all_checks_recorded():
    suite = _suite()
    report = suite.run_all()
    assert report.base_url == BASE_URL
    assert len(report.checks) == 8
    names = [c.name for c in report.checks]
    assert names == [
        "health_200",
        "health_fields",
        "summary_envelope_keys",
        "pagination_25_of_100",
        "admin_missing_token_401",
        "admin_wrong_token_403",
        "chart_format",
        "api_contract_ok",
    ]
    assert report.ok is True, [c.detail for c in report.checks if not c.ok]


# 7) api_contract kontrolu ----------------------------------------------------------------
def test_api_contract_check_ok():
    check, _ = _check(_suite(), "api_contract_ok")
    assert check.ok is True, check.detail


# 8) SmokeCheck kayit yapisi (name/ok/detail) ------------------------------------------------
def test_every_check_record_has_name_ok_detail():
    report = _suite().run_all()
    for check in report.checks:
        assert isinstance(check.name, str) and check.name
        assert isinstance(check.ok, bool)
        assert isinstance(check.detail, str)
