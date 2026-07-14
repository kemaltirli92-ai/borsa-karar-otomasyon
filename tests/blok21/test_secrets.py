"""BLOK 21 - test_secrets: gizli anahtar saglayici + redaksiyon (12 test).

Kapsam: get/require_all/eksik/bos string/default/known_values kopya/
redact_text kisa deger/coklu gecis/redact_mapping anahtar-esli/ic ice/
orijinal bozulmaz/SENSITIVE_KEY_RE. Tum degerler SAHTE (test verisi).
"""
from __future__ import annotations

import pytest

from app.ops.secrets import (
    SENSITIVE_KEY_RE,
    SecretMissingError,
    SecretProvider,
    redact_mapping,
    redact_text,
)

FAKE_TOKEN = "test-token-12345"
FAKE_PASSWORD = "test-sifre-98765"


def test_get_mevcut_degeri_dondurur():
    provider = SecretProvider({"ADMIN_TOKEN": FAKE_TOKEN})
    assert provider.get("ADMIN_TOKEN") == FAKE_TOKEN


def test_get_eksik_zorunlu_hata_firlatir():
    provider = SecretProvider({})
    with pytest.raises(SecretMissingError) as excinfo:
        provider.get("YOK_OLAN_KEY")
    assert excinfo.value.name == "YOK_OLAN_KEY"


def test_get_eksik_opsiyonel_default_dondurur():
    provider = SecretProvider({})
    assert provider.get("YOK", required=False) is None
    assert provider.get("YOK", required=False, default="varsayilan") == "varsayilan"


def test_bos_string_eksik_sayilir():
    provider = SecretProvider({"BOS_KEY": ""})
    with pytest.raises(SecretMissingError):
        provider.get("BOS_KEY")
    assert provider.get("BOS_KEY", required=False, default="d") == "d"


def test_require_all_donus_ve_eksikte_hata():
    provider = SecretProvider({"A": "deger-a", "B": "deger-b"})
    assert provider.require_all(["A", "B"]) == {"A": "deger-a", "B": "deger-b"}
    eksik = SecretProvider({"A": "deger-a"})
    with pytest.raises(SecretMissingError) as excinfo:
        eksik.require_all(["A", "B"])
    assert excinfo.value.name == "B"


def test_known_values_bos_olmayan_tum_degerler_ve_kopya():
    env = {"A": "deger-a", "B": "", "C": "deger-c"}
    provider = SecretProvider(env)
    values = provider.known_values()
    assert sorted(values) == ["deger-a", "deger-c"]
    values.append("disaridan-eklenen")
    assert "disaridan-eklenen" not in provider.known_values()


def test_redact_text_kisa_deger_uygulanmaz():
    text = "kisa abc degeri metinde kalir"
    assert redact_text(text, ["abc"], min_len=4) == text


def test_redact_text_coklu_gecis_hepsi_maskelenir():
    text = "giris %s cikis %s" % (FAKE_TOKEN, FAKE_TOKEN)
    sonuc = redact_text(text, [FAKE_TOKEN])
    assert FAKE_TOKEN not in sonuc
    assert sonuc.count("***") == 2


def test_redact_mapping_hassas_anahtar_degeri_her_zaman_maskeli():
    data = {"username": "ali", "password": "herhangi-bir-deger"}
    sonuc = redact_mapping(data, [])
    assert sonuc["password"] == "***"
    assert sonuc["username"] == "ali"


def test_redact_mapping_ic_ic_dict_ve_liste():
    data = {
        "dis": {"api_key": "gizli-deger-111", "metin": "token %s" % FAKE_TOKEN},
        "liste": [{"secret": "gizli-222"}, "duz %s" % FAKE_TOKEN],
    }
    sonuc = redact_mapping(data, [FAKE_TOKEN])
    assert sonuc["dis"]["api_key"] == "***"
    assert sonuc["dis"]["metin"] == "token ***"
    assert sonuc["liste"][0]["secret"] == "***"
    assert sonuc["liste"][1] == "duz ***"


def test_redact_mapping_orijinal_bozulmaz():
    data = {"token": "deger-123456", "metin": "icerik %s" % FAKE_TOKEN}
    kopya = {"token": "deger-123456", "metin": "icerik %s" % FAKE_TOKEN}
    redact_mapping(data, [FAKE_TOKEN])
    assert data == kopya


def test_sensitive_key_re_desenleri():
    for anahtar in ("password", "PASSWD", "db_secret", "X-Token", "api_key",
                    "APIKEY", "api-key", "Authorization", "sifre", "SIFRE_TEKRAR"):
        assert SENSITIVE_KEY_RE.search(anahtar), anahtar
    for anahtar in ("username", "symbol", "run_id", "kaynak"):
        assert not SENSITIVE_KEY_RE.search(anahtar), anahtar
