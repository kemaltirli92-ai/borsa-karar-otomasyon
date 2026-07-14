"""BLOK 21 - test_retention: arsiv + saklama suresi (10 test).

Kapsam: put/list, kind ValueError, path traversal temizligi, raw eski
silinir, raw yeni kalir, structured ASLA silinmez, rapor alanlari,
retention_days=0, now enjekte, klasor olusumu. Fixture'lar tmp_path
kullanir; gercek saate bagli test YOK (now enjekte).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from app.ops.retention import (
    ALL_KINDS,
    RAW_KINDS,
    STRUCTURED_KINDS,
    ArchiveStore,
)

NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _store(tmp_path, **kwargs):
    return ArchiveStore(tmp_path / "arsiv", **kwargs)


def _dosyayi_eskit(path, gun):
    """Dosya mtime'ini deterministik olarak 'gun' gun geriye alir."""
    eski = NOW.timestamp() - gun * 86400
    os.utime(str(path), (eski, eski))


def test_put_ve_list_doner(tmp_path):
    store = _store(tmp_path)
    p1 = store.put("raw_html", "a.html", b"<html>a</html>")
    p2 = store.put("raw_html", "b.html", b"<html>b</html>")
    assert p1.read_bytes() == b"<html>a</html>"
    assert store.list("raw_html") == sorted([p1, p2])


def test_bilinmeyen_kind_value_error(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.put("gizli_tur", "x.bin", b"veri")
    with pytest.raises(ValueError):
        store.list("gizli_tur")


def test_path_traversal_temizligi(tmp_path):
    store = _store(tmp_path)
    path = store.put("raw_api", "../../etc/passwd", b"x")
    assert path.parent == store.root / "raw_api"
    assert ".." not in path.name and "/" not in path.name and "\\" not in path.name
    assert path.is_file()


def test_raw_eski_dosya_silinir(tmp_path):
    store = _store(tmp_path, raw_retention_days=14)
    eski = store.put("raw_html", "eski.html", b"eski")
    _dosyayi_eskit(eski, 30)
    rapor = store.apply_retention(now=NOW)
    assert str(eski) in rapor["deleted"]
    assert not eski.exists()


def test_raw_yeni_dosya_kalir(tmp_path):
    store = _store(tmp_path, raw_retention_days=14)
    yeni = store.put("raw_api", "yeni.json", b"{}")
    _dosyayi_eskit(yeni, 2)
    rapor = store.apply_retention(now=NOW)
    assert rapor["deleted"] == []
    assert yeni.exists()
    assert rapor["kept_raw"] == 1


def test_structured_kinds_asla_silinmez(tmp_path):
    store = _store(tmp_path, raw_retention_days=1)
    for kind in STRUCTURED_KINDS:
        p = store.put(kind, "cok-eski.dat", b"kalici")
        _dosyayi_eskit(p, 365)
    rapor = store.apply_retention(now=NOW)
    assert rapor["deleted"] == []
    assert rapor["kept_structured"] == len(STRUCTURED_KINDS)
    for kind in STRUCTURED_KINDS:
        assert len(store.list(kind)) == 1


def test_rapor_alanlari(tmp_path):
    store = _store(tmp_path)
    eski = store.put("raw_html", "e.html", b"e")
    _dosyayi_eskit(eski, 100)
    store.put("price", "p.parquet", b"p")
    rapor = store.apply_retention(now=NOW)
    assert set(rapor.keys()) == {"deleted", "kept_raw", "kept_structured"}
    assert isinstance(rapor["deleted"], list)
    assert rapor["kept_structured"] == 1


def test_retention_days_sifir_tum_raw_silinir(tmp_path):
    store = _store(tmp_path, raw_retention_days=0)
    p = store.put("raw_api", "bir.json", b"1")
    _dosyayi_eskit(p, 0.001)
    rapor = store.apply_retention(now=NOW)
    assert str(p) in rapor["deleted"]


def test_now_enjekte_deterministik(tmp_path):
    store = _store(tmp_path, raw_retention_days=14)
    p = store.put("raw_html", "s.html", b"s")
    _dosyayi_eskit(p, 20)  # NOW'dan 20 gun eski
    gelecek = datetime(2025, 6, 10, 0, 0, 0, tzinfo=timezone.utc)
    gecmis = datetime(2025, 5, 20, 0, 0, 0, tzinfo=timezone.utc)
    assert store.apply_retention(now=gecmis)["deleted"] == []  # henuz genc
    assert str(p) in store.apply_retention(now=gelecek)["deleted"]  # artik eski


def test_klasorler_olusturulur(tmp_path):
    kok = tmp_path / "yeni-arsiv"
    store = ArchiveStore(kok)
    assert kok.is_dir()
    for kind in ALL_KINDS:
        assert (kok / kind).is_dir()
    assert set(RAW_KINDS).isdisjoint(STRUCTURED_KINDS)
