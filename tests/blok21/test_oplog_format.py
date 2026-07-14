"""BLOK 21 - test_oplog_format: yapilandirilmis olay gunlugu sema/format (12 test).

Kapsam: sema alanlari, ts format, 19 enum, her kolaylik metodu dogru event
(toplu), json lines parse, ascii, extra serbest alan, level, clock enjekte,
puan-kilidi alan adlari.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.ops.oplog import LogEvent, OpsLogger

FIXED = datetime(2025, 3, 10, 9, 30, 0, tzinfo=timezone.utc)


def _logger(**kwargs):
    kwargs.setdefault("clock", lambda: FIXED)
    return OpsLogger(**kwargs)


def test_sema_alanlari_ve_sirasi():
    record = _logger().log(LogEvent.SCAN_STARTED, "basladi", run_id="r1")
    assert list(record.keys()) == [
        "ts", "level", "event", "run_id", "symbol", "source", "message", "extra",
    ]


def test_ts_iso8601_z_formati():
    record = _logger().log(LogEvent.SCAN_STARTED)
    assert record["ts"].endswith("Z")
    parsed = datetime.fromisoformat(record["ts"][:-1])
    assert (parsed.year, parsed.month, parsed.day) == (2025, 3, 10)


def test_enum_tam_19_uye():
    assert len(LogEvent) == 19
    assert len({e.value for e in LogEvent}) == 19


def test_varsayilan_alanlar_none_ve_bos():
    record = _logger().log(LogEvent.KAP_COUNT)
    assert record["run_id"] is None
    assert record["symbol"] is None
    assert record["source"] is None
    assert record["message"] == ""
    assert record["extra"] == {}
    assert record["level"] == "INFO"


def test_kolaylik_metodlari_dogru_event_uretir():
    logger = _logger()
    beklenen = [
        (logger.scan_started("r1"), LogEvent.SCAN_STARTED),
        (logger.scan_finished("r1", "COMPLETED"), LogEvent.SCAN_FINISHED),
        (logger.stock_task("r1", "AKBNK", "OK"), LogEvent.STOCK_TASK_STATUS),
        (logger.source_request("is", "/fiyat"), LogEvent.SOURCE_REQUEST),
        (logger.http_status("is", 200), LogEvent.SOURCE_HTTP_STATUS),
        (logger.response_time("is", 123.4), LogEvent.SOURCE_RESPONSE_TIME),
        (logger.retry("is", 2, 5), LogEvent.SOURCE_RETRY),
        (logger.fallback("is", "ana", "yedek"), LogEvent.SOURCE_FALLBACK),
        (logger.price_rows("is", "AKBNK", 250), LogEvent.PRICE_ROWS_FETCHED),
        (logger.kap_count("r1", 7), LogEvent.KAP_COUNT),
        (logger.news_count("r1", 12), LogEvent.NEWS_COUNT),
        (logger.duplicates_eliminated("r1", 3), LogEvent.DUPLICATES_ELIMINATED),
        (logger.wrong_match("AKBNK", "Akbank", "Baska"), LogEvent.WRONG_MATCH),
        (logger.missing_data("AKBNK", "kapanis"), LogEvent.MISSING_DATA),
        (logger.abnormal_data("AKBNK", "hacim", -5), LogEvent.ABNORMAL_DATA),
        (logger.manual_rescan("r1", "admin", "veri suphe"), LogEvent.MANUAL_RESCAN),
        (logger.universe_change(["YKBNK"], ["ESKI"]), LogEvent.UNIVERSE_CHANGE),
        (logger.symbol_change("ESKI", "YENI"), LogEvent.SYMBOL_CHANGE),
        (logger.admin_setting("esik", "admin"), LogEvent.ADMIN_SETTING_CHANGE),
    ]
    assert len(beklenen) == 19
    for record, event in beklenen:
        assert record["event"] == event.value


def test_kolaylik_metodlari_alanlari_dogru_yazar():
    logger = _logger()
    rec = logger.price_rows("is", "AKBNK", 250)
    assert rec["source"] == "is"
    assert rec["symbol"] == "AKBNK"
    assert rec["extra"] == {"rows": 250}
    rec2 = logger.scan_finished("r9", "COMPLETED")
    assert rec2["run_id"] == "r9"
    assert rec2["extra"] == {"status": "COMPLETED"}


def test_json_lines_her_satir_parse_edilir():
    logger = _logger()
    logger.scan_started("r1")
    logger.kap_count("r1", 5)
    satirlar = logger.to_json_lines().splitlines()
    assert len(satirlar) == 2
    parsed = [json.loads(s) for s in satirlar]
    assert parsed[0]["event"] == "SCAN_STARTED"
    assert parsed[1]["extra"]["count"] == 5


def test_json_ciktisi_ascii_guvenli():
    logger = _logger()
    logger.log(LogEvent.SCAN_STARTED, "Türkçe karakterli mesaj: çğıöşü")
    cikti = logger.to_json_lines()
    assert all(ord(ch) < 128 for ch in cikti)
    assert json.loads(cikti)["message"].startswith("Türkçe")


def test_extra_serbest_alan_korunur():
    record = _logger().log(
        LogEvent.SOURCE_RETRY, "deneme", source="is", attempt=2, detay={"a": 1}
    )
    assert record["extra"] == {"attempt": 2, "detay": {"a": 1}}


def test_level_parametresi_ve_donus_kayitla_ayni():
    logger = _logger()
    record = logger.log(LogEvent.MISSING_DATA, "eksik", level="WARN")
    assert record["level"] == "WARN"
    assert logger.records[-1] is record


def test_clock_enjekte_deterministik():
    logger = _logger(clock=lambda: datetime(2030, 1, 2, 3, 4, 5))
    record = logger.scan_started("r1")
    assert record["ts"] == "2030-01-02T03:04:05Z"


def test_puan_kilidi_alan_adlari_ve_enum_temiz():
    yasak = ("puan", "score", "sinyal")
    for member in LogEvent:
        for kelime in yasak:
            assert kelime not in member.name.lower()
            assert kelime not in member.value.lower()
    logger = _logger()
    record = logger.log(LogEvent.SCAN_FINISHED, "bitti", run_id="r1")
    for key in list(record.keys()) + list(record["extra"].keys()):
        for kelime in yasak:
            assert kelime not in str(key).lower()
