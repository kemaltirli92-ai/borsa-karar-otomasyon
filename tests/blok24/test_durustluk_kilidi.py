"""BLOK 24 - durustluk kilidi (repo gercegiyle birebir): TAM 8 pytest testi.

Kapsam (SPEC-BLOK24 dagilimi):
- BOLUM-3 yuklu ise app/services/stock_scanning repoda VAR (1)
- BOLUM-4/5/6/8 bos-yazi: repoda skorlama/gosterge/seviye/portfoy modulu YOK (4)
- BLOK-5 bos-yazi: evren modulu kaynaklari repoda yok (1)
- yasakli sahte iddia: "B2 yuklu", "endeks motoru calisiyor" ifadeleri YOK (2)
"""
from __future__ import annotations

import pytest

try:
    from tests.blok24.envanter_data import DOCS_HTML, REPO_ROOT
except ImportError:  # pragma: no cover
    from .envanter_data import DOCS_HTML, REPO_ROOT


@pytest.fixture(scope="module")
def html() -> str:
    assert DOCS_HTML.is_file(), f"docs.html bulunamadi: {DOCS_HTML}"
    return DOCS_HTML.read_text(encoding="utf-8")


def _modul_adlari():
    """app/ ve tests/ altindaki dosya+dizin adlari (kucuk harf, pycache haric)."""
    adlar = []
    for kok in (REPO_ROOT / "app", REPO_ROOT / "tests"):
        for p in kok.rglob("*"):
            if "__pycache__" not in p.parts:
                adlar.append(p.name.lower())
    return adlar


class TestDurustlukKilidi:
    def test_bolum3_yuklu_stock_scanning_var(self):
        assert (REPO_ROOT / "app" / "services" / "stock_scanning").is_dir(), \
            "BOLUM-3 yuklu iddiasinin kaniti app/services/stock_scanning YOK"

    def test_bolum4_skorlama_modulu_yok(self):
        for ad in _modul_adlari():
            assert "skorlama" not in ad and "scoring" not in ad, \
                f"skorlama modulu bulundu: {ad}"

    def test_bolum5_gosterge_modulu_yok(self):
        for ad in _modul_adlari():
            for anahtar in ("gosterge", "indicator", "rsi", "macd"):
                assert anahtar not in ad, f"gosterge modulu bulundu: {ad}"

    def test_bolum6_seviye_modulu_yok(self):
        for ad in _modul_adlari():
            assert "seviye" not in ad and "level" not in ad, \
                f"seviye modulu bulundu: {ad}"

    def test_bolum8_portfoy_modulu_yok(self):
        for ad in _modul_adlari():
            assert "portfoy" not in ad and "portfolio" not in ad, \
                f"portfoy modulu bulundu: {ad}"

    def test_blok5_evren_kaynaklari_yok(self):
        assert not (REPO_ROOT / "tests" / "test_evren.py").exists(), \
            "test_evren.py var — BLOK-5 bos-yazi iddiasiyla celisir"
        assert not (REPO_ROOT / "app" / "services" / "hisse_tarama").exists(), \
            "hisse_tarama modulu var — BLOK-5 bos-yazi iddiasiyla celisir"
        # kabul katmani evren dogrulamasi (blok22) VAR ama evren modulu DEGIL:
        assert (REPO_ROOT / "app" / "acceptance" / "universe.py").is_file()

    def test_yasakli_iddia_b2_yuklu_yok(self, html):
        assert "b2 yuklu" not in html.lower(), \
            "yasakli sahte iddia: 'B2 yuklu'"

    def test_yasakli_iddia_endeks_motoru_calisiyor_yok(self, html):
        assert "endeks motoru calisiyor" not in html.lower(), \
            "yasakli sahte iddia: 'endeks motoru calisiyor'"
