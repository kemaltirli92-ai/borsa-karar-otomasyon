"""BLOK 24 - JSON manifest (id='sistem-envanteri-json'): TAM 10 pytest testi.

Kapsam (SPEC-BLOK24 dagilimi):
- script tag var (1) · json.loads parse (1) · 53 items (1)
- total/yuklu/bos_yazi alanlari dogru (3) · her itemda kod/ad/durum/kanit (1)
- kodlar benzersiz (1) · durum degerleri yalniz {yuklu,bos-yazi} (1)
- tablo ile ayni kod kumesi (1)
"""
from __future__ import annotations

import json
import re

import pytest

try:
    from tests.blok24.envanter_data import DOCS_HTML, tablo_satirlari
except ImportError:  # pragma: no cover
    from .envanter_data import DOCS_HTML, tablo_satirlari


@pytest.fixture(scope="module")
def html() -> str:
    assert DOCS_HTML.is_file(), f"docs.html bulunamadi: {DOCS_HTML}"
    return DOCS_HTML.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def manifest(html):
    m = re.search(
        r'<script type="application/json" id="sistem-envanteri-json">\s*(.*?)\s*</script>',
        html, re.S)
    assert m, "sistem-envanteri-json script tag'i yok"
    assert "</script>" not in m.group(1), "JSON govdesi </script> iceremez"
    return json.loads(m.group(1))


class TestJsonManifest:
    def test_script_tag_var(self, html):
        assert '<script type="application/json" id="sistem-envanteri-json">' in html

    def test_json_parse(self, manifest):
        assert isinstance(manifest, dict)

    def test_53_items(self, manifest):
        assert len(manifest["items"]) == 53

    def test_total_53(self, manifest):
        assert manifest["total"] == 53

    def test_yuklu_21(self, manifest):
        assert manifest["yuklu"] == 21

    def test_bos_yazi_32(self, manifest):
        assert manifest["bos_yazi"] == 32

    def test_item_alanlari(self, manifest):
        for it in manifest["items"]:
            for alan in ("kod", "ad", "durum", "kanit"):
                assert alan in it and str(it[alan]).strip(), \
                    f"eksik alan: {alan} -> {it}"

    def test_kodlar_benzersiz(self, manifest):
        kodlar = [it["kod"] for it in manifest["items"]]
        assert len(set(kodlar)) == 53

    def test_durum_degerleri(self, manifest):
        for it in manifest["items"]:
            assert it["durum"] in ("yuklu", "bos-yazi"), it
        assert sum(1 for it in manifest["items"] if it["durum"] == "yuklu") == 21

    def test_tablo_ile_ayni_kod_kumesi(self, html, manifest):
        json_kodlari = {it["kod"] for it in manifest["items"]}
        tablo_kodlari = {k for k, _, _ in tablo_satirlari(html)}
        assert json_kodlari == tablo_kodlari
