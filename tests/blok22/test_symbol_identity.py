"""BLOK 22 - test_symbol_identity: sembol kimligi kabul testleri (6 test).

Kapsam: kod degisikligi: eski->yeni resolve + tarihce (2); sembol
eslestirme: normalize + yanlis sembol reddi/queue (2); KAP kimligi:
set_kap_link + KapVerifier enjekte probe (2). GERCEK BLOK 6 modulleri
kullanilir; sahte yalniz http probe seviyesindedir.
"""
from __future__ import annotations

from datetime import date

from app.models.stock_identity import KapLinkStatus
from app.services.stock_scanning.identity_adapter import IdentityAdapter
from app.services.stock_scanning.kap_verifier import KapVerifier
from app.services.stock_scanning.symbol_identity import (
    REASON_KAP_LINK_BROKEN,
    REASON_UNRESOLVED_UNIVERSE_SYMBOL,
)
from tests.blok22.conftest import FIXED_NOW


class _ProbeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class _ProbeClient:
    """Enjekte HTTP probe (gercek ag YOK): url -> status/hata."""

    def __init__(self, routes=None, errors=None):
        self.routes = routes or {}
        self.errors = errors or {}

    def head(self, url):
        if url in self.errors:
            raise self.errors[url]
        return _ProbeResponse(self.routes.get(url, 404))


def _register(identity, name, symbol):
    sid = identity.register_stock(name)
    identity.add_symbol(sid, "bist", symbol)
    return sid


# 1) kod degisikligi: eski -> yeni resolve -------------------------------------
def test_code_change_old_code_resolves_to_new_stock(identity):
    sid = _register(identity, "Kod Degisen Sirket", "ESKI")
    # kayit valid_from = enjekte saat gunu (2025-06-03); kod degisikligi
    # kayit tarihinden SONRA olmali (gercek kural: eff >= valid_from)
    identity.change_symbol(sid, "bist", "YENI", date(2025, 6, 10))
    assert identity.resolve("ESKI", platform="bist") is None  # aktifte yok
    old = identity.resolve_old_code("ESKI", "bist")
    assert old is not None and old.stock_id == sid and old.historical is True
    new = identity.resolve("YENI", platform="bist")
    assert new is not None and new.stock_id == sid and new.historical is False


def test_code_change_history_keeps_both_records(identity):
    sid = _register(identity, "Kod Degisen Sirket", "ESKI")
    # kayit valid_from = 2025-06-03 (enjekte saat); degisiklik sonrasinda
    identity.change_symbol(sid, "bist", "YENI", date(2025, 6, 10))
    history = identity.get_symbol_history(sid, "bist")
    assert [r.symbol for r in history] == ["ESKI", "YENI"]
    assert history[0].is_active is False
    assert history[0].valid_to == date(2025, 6, 10)
    assert history[1].is_active is True


# 2) sembol eslestirme: normalize + yanlis reddi/queue -------------------------
def test_symbol_matching_normalized_case_and_turkish(identity):
    sid = _register(identity, "Turkiye Is Bankasi C", "ISCTR")
    assert identity.resolve("isctr", platform="bist").stock_id == sid
    # Turkce noktali I normalize edilir
    assert identity.resolve("İSCTR", platform="bist").stock_id == sid


def test_unknown_symbol_rejected_and_queued(identity):
    _register(identity, "Turk Hava Yollari", "THYAO")
    adapter = IdentityAdapter(identity)
    result = adapter.resolve_universe_symbols(["THYAO", "HAYAL"])
    assert result["HAYAL"] is None
    pending = identity.get_pending_queue()
    assert len(pending) == 1
    assert pending[0].query == "HAYAL"
    assert pending[0].reason == REASON_UNRESOLVED_UNIVERSE_SYMBOL


# 3) KAP kimligi: set_kap_link + KapVerifier enjekte probe ---------------------
def test_kap_link_verify_valid_with_injected_probe(identity):
    sid = identity.register_stock("Kap Sirketi")
    identity.set_kap_link(sid, "https://kap.example.tr/ok")
    verifier = KapVerifier(identity, http_client=_ProbeClient(
        routes={"https://kap.example.tr/ok": 200}
    ))
    assert verifier.verify(sid) == KapLinkStatus.KAP_LINK_VALID
    assert identity.get_kap_link(sid).last_checked_at == FIXED_NOW


def test_kap_link_broken_three_failures_pending(identity):
    sid = identity.register_stock("Kap Sirketi")
    identity.set_kap_link(sid, "https://kap.example.tr/broken")
    verifier = KapVerifier(identity, http_client=_ProbeClient(
        routes={"https://kap.example.tr/broken": 404}
    ))
    for _ in range(3):
        assert verifier.verify(sid) == KapLinkStatus.KAP_LINK_BROKEN
    pending = [i for i in identity.get_pending_queue() if i.stock_id == sid]
    assert len(pending) == 1
    assert pending[0].reason == REASON_KAP_LINK_BROKEN
