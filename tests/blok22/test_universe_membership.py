"""BLOK 22 - test_universe_membership: resmi XK100 evren uyeligi (10 test).

Kapsam: aktif sayi=100 (2); giris: aktif 101 + yeni sembol cozulur (2);
cikis: aktif 99 + kayit korunur (2); tarihsel uyelik: gecmis gun
uye/degil, araliklar, cikis oncesi/sonrasi (2); resmi liste yeniden
yuklemede sessiz dusme YOK + aktif sembol listesi deterministik (2).
"""
from __future__ import annotations

import pytest

from app.acceptance.universe import UniverseBook
from tests.blok22.conftest import FIXED_DAY, make_universe, universe_symbols

DAY = FIXED_DAY


@pytest.fixture
def book100(identity):
    return make_universe(identity, universe_symbols(100))


# 1) aktif sayi = 100 ----------------------------------------------------------
def test_active_count_is_100(book100):
    assert book100.active_count(DAY) == 100
    assert book100.validate_count(DAY, 100)["ok"] is True


def test_validate_count_report_fields(book100):
    report = book100.validate_count(DAY, 100)
    assert report == {
        "day": DAY,
        "expected": 100,
        "actual": 100,
        "ok": True,
        "extra": [],
        "missing": [],
    }


# 2) giris: aktif 101 + yeni sembol cozulur ------------------------------------
def test_enter_new_company_active_101(book100):
    book100.enter("YENIS", "Yeni Sirket A.S.", DAY)
    assert book100.active_count(DAY) == 101
    report = book100.validate_count(DAY, 100)
    assert report["ok"] is False
    assert report["actual"] == 101
    assert report["extra"] == ["YENIS"]


def test_entered_symbol_resolves(book100, identity):
    book100.enter("YENIS", "Yeni Sirket A.S.", DAY)
    res = identity.resolve("YENIS", platform="bist")
    assert res is not None
    assert identity.get_active_symbol(res.stock_id, "bist") == "YENIS"


# 3) cikis: aktif 99 + kayit korunur -------------------------------------------
def test_exit_company_active_99(book100):
    book100.exit("X050", DAY)
    assert book100.active_count(DAY) == 99
    report = book100.validate_count(DAY, 100)
    assert report["ok"] is False
    assert report["missing"] == ["X050"]


def test_exit_record_preserved_not_deleted(book100):
    book100.exit("X050", DAY)
    history = book100.history("X050")
    assert len(history) == 1
    assert history[0].entered == DAY
    assert history[0].exited == DAY  # kayit SILINMEZ, aralik kapanir
    # kimlik kaydi da korunur
    assert book100.is_member("X050", DAY) is False


# 4) tarihsel uyelik: gecmis gun uye/degil, araliklar, oncesi/sonrasi ----------
def test_historical_membership_before_and_after_exit(book100):
    book100.enter("GECMIS", "Gecmis Sirket", "2025-01-10")
    book100.exit("GECMIS", "2025-03-01")
    assert book100.is_member("GECMIS", "2025-01-09") is False  # giris oncesi
    assert book100.is_member("GECMIS", "2025-02-15") is True   # aralik icinde
    assert book100.is_member("GECMIS", "2025-03-01") is False  # cikis gunu
    assert book100.is_member("GECMIS", "2025-06-01") is False  # cikis sonrasi


def test_reenter_creates_new_interval_chain(book100):
    book100.enter("DONGU", "Dongu Sirket", "2025-01-10")
    book100.exit("DONGU", "2025-02-01")
    book100.enter("DONGU", "Dongu Sirket", "2025-04-01")
    history = book100.history("DONGU")
    assert len(history) == 2
    assert history[0].exited == "2025-02-01"
    assert history[1].entered == "2025-04-01"
    assert history[1].exited is None
    # iki aralik arasindaki boslukta uye degil
    assert book100.is_member("DONGU", "2025-03-01") is False
    assert book100.is_member("DONGU", "2025-04-01") is True


# 5) resmi liste yeniden yukleme + deterministik liste -----------------------------------
def test_reload_official_does_not_silently_drop(book100):
    # load_official listede OLMAYAN sirketi CIKARMAZ (cikis yalniz exit() ile)
    book100.load_official(universe_symbols(99), DAY)  # X100 listede yok
    assert book100.is_member("X100", DAY) is True      # sessiz dusme YOK
    assert book100.active_count(DAY) == 100


def test_active_symbols_sorted_deterministic(book100):
    symbols = book100.active_symbols(DAY)
    assert len(symbols) == 100
    assert symbols == sorted(symbols)        # alfabetik, deterministik
    assert symbols == universe_symbols(100)  # X001..X100 sirali
