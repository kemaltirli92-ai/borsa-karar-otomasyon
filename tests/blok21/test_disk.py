"""BLOK 21 - test_disk: disk kullanim kontrolu (8 test).

Kapsam: OK/WARN/CRITICAL sinirlari, tam esik degerleri, total=0,
stat_provider enjekte, DiskStatus alanlari, pct hesabi, ozel esikler.
Gercek diske bagli test YOK (stat_provider enjekte).
"""
from __future__ import annotations

import pytest

from app.ops.disk import (
    DISK_CRITICAL,
    DISK_OK,
    DISK_WARN,
    DiskStatus,
    check_disk_usage,
)


def _provider(total, used, free):
    return lambda path: (total, used, free)


def test_ok_seviyesi():
    status = check_disk_usage("/x", stat_provider=_provider(1000, 500, 500))
    assert status.level == DISK_OK
    assert status.used_pct == pytest.approx(50.0)


def test_warn_seviyesi():
    status = check_disk_usage("/x", stat_provider=_provider(1000, 850, 150))
    assert status.level == DISK_WARN
    assert status.used_pct == pytest.approx(85.0)


def test_critical_seviyesi():
    status = check_disk_usage("/x", stat_provider=_provider(1000, 970, 30))
    assert status.level == DISK_CRITICAL
    assert status.used_pct == pytest.approx(97.0)


def test_tam_esik_degerleri_ust_seviyeye_dahil():
    warn = check_disk_usage("/x", stat_provider=_provider(1000, 800, 200))
    assert warn.used_pct == pytest.approx(80.0)
    assert warn.level == DISK_WARN
    critical = check_disk_usage("/x", stat_provider=_provider(1000, 950, 50))
    assert critical.used_pct == pytest.approx(95.0)
    assert critical.level == DISK_CRITICAL


def test_total_sifir_bolunme_hatasi_yok():
    status = check_disk_usage("/x", stat_provider=_provider(0, 0, 0))
    assert status.used_pct == 0.0
    assert status.level == DISK_OK


def test_stat_provider_path_dogru_iletir():
    gorulen = []

    def provider(path):
        gorulen.append(path)
        return (100, 10, 90)

    status = check_disk_usage("/var/lib/xk100", stat_provider=provider)
    assert gorulen == ["/var/lib/xk100"]
    assert status.path == "/var/lib/xk100"


def test_diskstatus_alanlari_ve_dondurulen_tur():
    status = check_disk_usage("/d", stat_provider=_provider(2000, 1000, 1000))
    assert isinstance(status, DiskStatus)
    assert status.total_bytes == 2000
    assert status.used_bytes == 1000
    assert status.free_bytes == 1000
    assert status.level in (DISK_OK, DISK_WARN, DISK_CRITICAL)
    with pytest.raises(AttributeError):
        status.level = DISK_CRITICAL  # frozen dataclass


def test_pct_hesabi_ve_ozel_esikler():
    status = check_disk_usage(
        "/x", warn_pct=50.0, critical_pct=60.0,
        stat_provider=_provider(1000, 550, 450),
    )
    assert status.used_pct == pytest.approx(55.0)
    assert status.level == DISK_WARN
    varsayilan = check_disk_usage("/x", stat_provider=_provider(1000, 550, 450))
    assert varsayilan.level == DISK_OK  # varsayilan esikler 80/95
