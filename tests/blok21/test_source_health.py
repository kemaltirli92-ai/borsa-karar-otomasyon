"""BLOK 21 - test_source_health: kaynak saglik ekrani + 3-hata uyarisi (14 test).

Kapsam: register, basari sifirlar, hata sayaci, 3. hatada TEK uyari,
4./5. uyari yok, basari sonrasi yeni esik, ekran alanlari, aktif/pasif,
bilinmeyen kaynak oto-register, last_response_ms, uyari semasi, mesaj
redaksiyonu, screen sirasi, clock determinizm.
"""
from __future__ import annotations

import itertools
from dataclasses import fields
from datetime import datetime, timedelta, timezone

from app.ops.secrets import SecretProvider
from app.ops.source_health import SourceHealth, SourceHealthRegistry

BASE = datetime(2025, 5, 20, 12, 0, 0, tzinfo=timezone.utc)
FAKE_TOKEN = "test-token-12345"


def _clock_seq(start=BASE):
    """Cagri basina 1 dakika ilerleyen deterministik clock."""
    sayac = itertools.count()
    return lambda: start + timedelta(minutes=next(sayac))


def _registry(**kwargs):
    kwargs.setdefault("clock", _clock_seq())
    return SourceHealthRegistry(**kwargs)


def test_register_varsayilan_durum():
    reg = _registry()
    reg.register("is_yatirim")
    health = reg.get("is_yatirim")
    assert health.active is True
    assert health.consecutive_errors == 0
    assert health.last_success_at is None
    assert health.last_error_at is None


def test_basari_hata_sayacini_sifirlar():
    reg = _registry()
    reg.record_error("kaynak", "hata-1")
    reg.record_error("kaynak", "hata-2")
    health = reg.record_success("kaynak")
    assert health.consecutive_errors == 0
    assert health.last_success_at is not None


def test_hata_sayaci_artar():
    reg = _registry()
    reg.record_error("kaynak", "hata-1")
    health = reg.record_error("kaynak", "hata-2")
    assert health.consecutive_errors == 2
    assert health.last_error_message == "hata-2"


def test_ucuncu_hatada_tek_uyari():
    reg = _registry(warn_threshold=3)
    for i in range(3):
        reg.record_error("kaynak", "hata-%d" % i)
    assert len(reg.warnings) == 1
    assert reg.warnings[0]["consecutive_errors"] == 3


def test_dorduncu_besinci_hata_uyari_uretmez():
    reg = _registry(warn_threshold=3)
    for i in range(5):
        reg.record_error("kaynak", "hata-%d" % i)
    assert len(reg.warnings) == 1


def test_basari_sonrasi_yeni_esikte_uyari_tekrar():
    reg = _registry(warn_threshold=3)
    for i in range(3):
        reg.record_error("kaynak", "tur-1-%d" % i)
    reg.record_success("kaynak")
    for i in range(3):
        reg.record_error("kaynak", "tur-2-%d" % i)
    assert len(reg.warnings) == 2


def test_ekran_alanlari_sourcehealth_ile_birebir():
    reg = _registry()
    reg.record_success("kaynak", response_ms=42.0)
    satir = reg.screen()[0]
    beklenen = {f.name for f in fields(SourceHealth)}
    assert set(satir.keys()) == beklenen


def test_aktif_pasif_isaretleme():
    reg = _registry()
    reg.register("kaynak")
    reg.set_active("kaynak", False)
    assert reg.get("kaynak").active is False
    reg.set_active("kaynak", True)
    assert reg.get("kaynak").active is True


def test_bilinmeyen_kaynak_oto_register():
    reg = _registry()
    health = reg.record_success("yeni-kaynak")
    assert health.name == "yeni-kaynak"
    assert [s["name"] for s in reg.screen()] == ["yeni-kaynak"]


def test_last_response_ms_kaydedilir():
    reg = _registry()
    health = reg.record_success("kaynak", response_ms=123.5)
    assert health.last_response_ms == 123.5
    health2 = reg.record_error("kaynak", "zaman-asimi", response_ms=980.0)
    assert health2.last_response_ms == 980.0


def test_uyari_semasi():
    reg = _registry(warn_threshold=2)
    reg.record_error("kaynak-x", "h1")
    reg.record_error("kaynak-x", "h2")
    uyari = reg.warnings[0]
    assert set(uyari.keys()) == {"type", "source", "consecutive_errors", "at"}
    assert uyari["type"] == "SOURCE_UNHEALTHY"
    assert uyari["source"] == "kaynak-x"
    assert uyari["consecutive_errors"] == 2
    assert uyari["at"].endswith("Z")


def test_hata_mesaji_redakte_edilir():
    provider = SecretProvider({"ADMIN_TOKEN": FAKE_TOKEN})
    reg = _registry(secret_provider=provider)
    health = reg.record_error("kaynak", "baglanti token=%s reddedildi" % FAKE_TOKEN)
    assert FAKE_TOKEN not in health.last_error_message
    assert "***" in health.last_error_message


def test_screen_kayit_sirasini_korur():
    reg = _registry()
    for isim in ("alfa", "beta", "gamma"):
        reg.register(isim)
    reg.record_error("beta", "hata")
    assert [s["name"] for s in reg.screen()] == ["alfa", "beta", "gamma"]


def test_clock_determinizm_zaman_damgalari():
    reg = _registry()
    reg.record_success("kaynak")
    reg.record_error("kaynak", "hata")
    health = reg.get("kaynak")
    assert health.last_success_at == "2025-05-20T12:00:00Z"
    assert health.last_error_at == "2025-05-20T12:01:00Z"
