"""BLOK 22 - test_staging_fullday: tam gun staging tarama kabul testleri (10 test).

Kapsam: 100 sirket uretilir (universe provider enjekte); run() ->
total==100 (sessiz dusme yok); her sonucta state + data_confidence var;
eksik veri missing_fields'ta, 0'a cevrilmemis; fail_symbols izolasyonu;
finish_by_0935; zarf alanlari (scan_run_id STAGING- oneki,
report_version, data_cutoff_at); rapor JSON'a serilestirilebilir;
eksik kanal sayaci 0 AMA eksiklik aciklanir (sessiz sifir YOK);
FAILED sembol tum kanallari eksik isaretler.
GERCEK akis: fetch->dogrula->hacim->kanallar->ConfidenceCalculator.
"""
from __future__ import annotations

import json
from dataclasses import asdict

from app.acceptance.staging import (
    STATE_FAILED,
    STATE_PARTIAL,
    STATE_READY,
    StagingRunner,
)
from tests.blok22.conftest import (
    FIXED_DAY,
    make_universe,
    price_series,
    universe_symbols,
)

DAY = FIXED_DAY


def _fetchers():
    return {
        "price": lambda symbol: price_series(symbol, DAY),
        "volume": lambda symbol: [1000, 1100, 1200],
        "kap": lambda symbol: [{"id": f"kap-{symbol}"}],
        "news": lambda symbol: [{"id": f"news-{symbol}"}],
        "actions": lambda symbol: [],
        "restrictions": lambda symbol: [],
    }


def _runner(identity, **kwargs):
    book = make_universe(identity, universe_symbols(100))
    kwargs.setdefault("durations", {"per_symbol_seconds": 3.0})
    return StagingRunner(book, _fetchers(), **kwargs)


# 1) 100 sirket uretilir (provider enjekte) ---------------------------------------
def test_universe_100_companies_from_injected_provider(identity):
    book = make_universe(identity, universe_symbols(100))
    check = book.validate_count(DAY, 100)
    assert check["ok"] is True
    assert check["actual"] == 100


# 2) run() -> total==100, sessiz dusme yok -----------------------------------------
def test_run_total_100_no_silent_drop(identity):
    report = _runner(identity).run(DAY)
    assert report.total == 100
    assert len(report.results) == 100
    assert report.missing_total == 0


# 3) her sonucta state + data_confidence -------------------------------------------
def test_every_result_has_state_and_confidence(identity):
    report = _runner(identity).run(DAY)
    for result in report.results:
        assert result.state in (STATE_READY, STATE_PARTIAL, STATE_FAILED)
        assert 0 <= result.data_confidence <= 100
    assert report.ready == 100  # tam veri -> hepsi READY


# 4) eksik veri missing_fields'ta, 0'a CEVRILMEMIS ----------------------------------
def test_missing_price_stays_none_in_missing_fields(identity):
    fetchers = _fetchers()
    fetchers["price"] = (
        lambda symbol: None if symbol == "X050" else price_series(symbol, DAY)
    )
    fetchers["volume"] = (
        lambda symbol: None if symbol == "X050" else [1000, 1100, 1200]
    )
    book = make_universe(identity, universe_symbols(100))
    report = StagingRunner(book, fetchers).run(DAY)
    target = [r for r in report.results if r.symbol == "X050"][0]
    assert target.state == STATE_PARTIAL
    assert target.price_rows is None        # None KALIR — ASLA 0 degil
    assert target.volume_rows is None
    assert "price" in target.missing_fields
    assert "volume" in target.missing_fields
    assert target.price_rows != 0           # 0'a cevrilme kaniti
    assert report.partial >= 1


# 5) fail_symbols izolasyonu ---------------------------------------------------------
def test_fail_symbols_isolated_others_unaffected(identity):
    book = make_universe(identity, universe_symbols(100))
    runner = StagingRunner(book, _fetchers(), fail_symbols={"X042"})
    report = runner.run(DAY)
    assert report.failed == 1
    failed = [r for r in report.results if r.state == STATE_FAILED]
    assert [r.symbol for r in failed] == ["X042"]
    assert report.ready == 99               # diger 99 ETKILENMEDI
    assert report.missing_total == 0


# 6) finish_by_0935 --------------------------------------------------------------------
def test_finish_by_0935_true(identity):
    report = _runner(identity).run(DAY)
    assert report.finish_by_0935 is True
    assert report.finished_at <= f"{DAY}T09:35:00"
    assert report.started_at == f"{DAY}T08:00:00"


# 7) zarf alanlari -----------------------------------------------------------------------
def test_envelope_fields_staging_prefix(identity):
    report = _runner(identity).run(DAY)
    envelope = report.envelope
    assert envelope["scan_run_id"] == f"STAGING-{DAY}-TARAMA-R1"
    assert envelope["scan_run_id"].startswith("STAGING-")
    assert envelope["report_version"] == 1
    assert envelope["data_cutoff_at"] == f"{DAY}T09:40:00"
    assert envelope["status"] == "OK"
    assert envelope["last_updated_at"] == report.finished_at


# 8) rapor JSON'a serilestirilebilir -------------------------------------------------------
def test_report_json_serializable(identity):
    report = _runner(identity).run(DAY)
    text = json.dumps(asdict(report), ensure_ascii=False)
    parsed = json.loads(text)
    assert parsed["run_id"] == f"STAGING-{DAY}-TARAMA-R1"
    assert parsed["total"] == 100
    assert len(parsed["results"]) == 100


# 9) eksik kanal: sayac 0 AMA eksiklik aciklanir (sessiz sifir YOK) ----------------------
def test_missing_channels_zero_count_explained_in_missing_fields(identity):
    fetchers = _fetchers()
    fetchers["kap"] = (
        lambda symbol: None if symbol == "X050" else [{"id": f"kap-{symbol}"}]
    )
    fetchers["news"] = (
        lambda symbol: None if symbol == "X050" else [{"id": f"news-{symbol}"}]
    )
    book = make_universe(identity, universe_symbols(100))
    report = StagingRunner(book, fetchers).run(DAY)
    target = [r for r in report.results if r.symbol == "X050"][0]
    assert target.state == STATE_PARTIAL
    assert target.kap_count == 0 and target.news_count == 0  # int sayac kalir
    assert "kap" in target.missing_fields   # sessiz sifir YOK: eksiklik aciklanir
    assert "news" in target.missing_fields
    assert target.price_rows is not None    # fiyat kanali saglam
    assert report.envelope["status"] == "PARTIAL"


# 10) FAILED sembol tum kanallari eksik isaretler -------------------------------------------
def test_failed_symbol_marks_all_channels_missing(identity):
    book = make_universe(identity, universe_symbols(100))
    runner = StagingRunner(book, _fetchers(), fail_symbols={"X007"})
    report = runner.run(DAY)
    target = [r for r in report.results if r.symbol == "X007"][0]
    assert target.state == STATE_FAILED
    assert target.missing_fields == (
        "price", "volume", "kap", "news", "actions", "restrictions"
    )
    assert target.data_confidence == 0
