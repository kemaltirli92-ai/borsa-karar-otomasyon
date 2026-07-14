"""BLOK 21 - test_oplog_redaction: log redaksiyonu iki katmanli (10 test).

Kapsam: message'da token, extra'da api_key degeri, anahtar adi password,
ic ice extra, log sonrasi records'ta sizinti yok, bilinen tum degerler
taranir, bilinmeyen metin korunur, kisa deger, json ciktisinda sizinti yok,
sink'e giden kayit redakte. Tum degerler SAHTE (test verisi).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.ops.oplog import LogEvent, OpsLogger
from app.ops.secrets import SecretProvider

FAKE_TOKEN = "test-token-12345"
FAKE_API_KEY = "test-apikey-67890"
FIXED = datetime(2025, 3, 10, 9, 30, 0, tzinfo=timezone.utc)


def _logger(secrets_env=None, **kwargs):
    kwargs.setdefault("clock", lambda: FIXED)
    kwargs.setdefault(
        "secret_provider", SecretProvider(secrets_env or {"ADMIN_TOKEN": FAKE_TOKEN})
    )
    return OpsLogger(**kwargs)


def test_message_icinde_token_redakte_edilir():
    record = _logger().log(LogEvent.SOURCE_REQUEST, "istek token=%s ile" % FAKE_TOKEN)
    assert FAKE_TOKEN not in record["message"]
    assert "***" in record["message"]


def test_extrada_hassas_anahtar_degeri_maskeli():
    record = _logger(secrets_env={}).log(
        LogEvent.SOURCE_REQUEST, api_key=FAKE_API_KEY, url="/fiyat"
    )
    assert record["extra"]["api_key"] == "***"
    assert record["extra"]["url"] == "/fiyat"


def test_anahtar_adi_password_olan_deger_maskeli():
    record = _logger(secrets_env={}).log(
        LogEvent.ADMIN_SETTING_CHANGE, db_password="ne-olursa-olsun"
    )
    assert record["extra"]["db_password"] == "***"


def test_ic_ice_extra_redakte_edilir():
    record = _logger().log(
        LogEvent.SOURCE_FALLBACK,
        detay={"auth": {"authorization": "Bearer %s" % FAKE_TOKEN}, "not": "ok"},
    )
    assert record["extra"]["detay"]["auth"]["authorization"] == "***"
    assert record["extra"]["detay"]["not"] == "ok"


def test_records_uzerinde_sizinti_yok():
    logger = _logger(
        secrets_env={"ADMIN_TOKEN": FAKE_TOKEN, "LICENSED_PRICE_API_KEY": FAKE_API_KEY}
    )
    logger.log(LogEvent.SOURCE_REQUEST, "token=%s key=%s" % (FAKE_TOKEN, FAKE_API_KEY))
    logger.log(LogEvent.SOURCE_RETRY, "deneme", source="is", api_key=FAKE_API_KEY)
    tum = json.dumps(logger.records, ensure_ascii=True)
    assert FAKE_TOKEN not in tum
    assert FAKE_API_KEY not in tum


def test_bilinen_tum_degerler_taranir():
    logger = _logger(
        secrets_env={"A": FAKE_TOKEN, "B": FAKE_API_KEY, "C": "zararsiz"}
    )
    record = logger.log(
        LogEvent.SCAN_STARTED, "%s ve %s gecti" % (FAKE_TOKEN, FAKE_API_KEY)
    )
    assert FAKE_TOKEN not in record["message"]
    assert FAKE_API_KEY not in record["message"]
    assert record["message"].count("***") == 2


def test_bilinmeyen_metin_korunur():
    record = _logger().log(LogEvent.KAP_COUNT, "kap sayisi 42 olarak kaydedildi")
    assert record["message"] == "kap sayisi 42 olarak kaydedildi"


def test_kisa_deger_redakte_edilmez():
    logger = _logger(secrets_env={"KISA": "abc"})
    record = logger.log(LogEvent.NEWS_COUNT, "abc harfleri serbest kalmali")
    assert record["message"] == "abc harfleri serbest kalmali"


def test_json_ciktisinda_sizinti_yok():
    logger = _logger(
        secrets_env={"ADMIN_TOKEN": FAKE_TOKEN, "SECRET_X": FAKE_API_KEY}
    )
    logger.log(LogEvent.MANUAL_RESCAN, "neden: %s" % FAKE_TOKEN, token=FAKE_API_KEY)
    cikti = logger.to_json_lines()
    assert FAKE_TOKEN not in cikti
    assert FAKE_API_KEY not in cikti
    parsed = json.loads(cikti.splitlines()[0])
    assert parsed["extra"]["token"] == "***"


def test_sinke_giden_kayit_redakte():
    gelen = []
    logger = _logger(sink=gelen.append)
    logger.log(LogEvent.ADMIN_SETTING_CHANGE, "ayar %s" % FAKE_TOKEN, secret="x")
    assert len(gelen) == 1
    assert FAKE_TOKEN not in gelen[0]["message"]
    assert gelen[0]["extra"]["secret"] == "***"
    assert gelen[0] is logger.records[0]
