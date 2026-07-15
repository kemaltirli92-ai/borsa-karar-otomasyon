"""BLOK 24 - sistem yukluluk envanteri tablosu: TAM 16 pytest testi.

Kapsam (SPEC-BLOK24 dagilimi):
- bolum id var (1) · legend ✓/✗ aciklamasi (2) · tabloda 53 satir (1)
- her satirda data-kod+data-durum (2) · yuklu=21 / bos-yazi=32 sayaci (2)
- sayac ozeti metni (1) · tablo-rozet kod kumesi tutarliligi (2)
- AKIS kodlari tabloda YOK (1) · aria-label'lar (2) · tek id (2)
"""
from __future__ import annotations

import re

import pytest

try:
    from tests.blok24.envanter_data import (
        AKIS_KODLAR, BADGE_RE, DOCS_HTML, DURUM, KODLAR, TIK, X,
        envanter_bolumu, tablo_satirlari,
    )
except ImportError:  # pragma: no cover
    from .envanter_data import (
        AKIS_KODLAR, BADGE_RE, DOCS_HTML, DURUM, KODLAR, TIK, X,
        envanter_bolumu, tablo_satirlari,
    )


@pytest.fixture(scope="module")
def html() -> str:
    assert DOCS_HTML.is_file(), f"docs.html bulunamadi: {DOCS_HTML}"
    return DOCS_HTML.read_text(encoding="utf-8")


# ======================================================================
# 1. KART + LEGEND (3)
# ======================================================================
class TestKartVeLegend:
    def test_bolum_id_var(self, html):
        assert 'id="sistem-yukluluk-envanteri"' in html

    def test_legend_tik_aciklamasi(self, html):
        bolum = envanter_bolumu(html)
        assert f"{TIK} SISTEMDE YUKLU" in bolum
        assert "kod + test bu repoda, is akisi calisiyor" in bolum

    def test_legend_carpi_aciklamasi(self, html):
        bolum = envanter_bolumu(html)
        assert f"{X} BOS YAZI" in bolum
        assert "sisteme yuklenmedi" in bolum
        assert "YAZIDA KALANLAR" in bolum


# ======================================================================
# 2. TABLO SATIRLARI (5)
# ======================================================================
class TestTabloSatirlari:
    def test_tabloda_53_satir(self, html):
        satirlar = tablo_satirlari(html)
        assert len(satirlar) == 53, f"53 satir bekleniyor, {len(satirlar)} bulundu"

    def test_her_satirda_data_kod(self, html):
        for kod, _, _ in tablo_satirlari(html):
            assert kod in KODLAR, f"bilinmeyen kod: {kod}"

    def test_her_satirda_data_durum(self, html):
        for kod, durum, _ in tablo_satirlari(html):
            assert durum in ("yuklu", "bos-yazi"), f"{kod}: gecersiz durum {durum}"
            assert durum == DURUM[kod], f"{kod}: SPEC durumu {DURUM[kod]} != {durum}"

    def test_yuklu_sayisi_21(self, html):
        assert sum(1 for _, d, _ in tablo_satirlari(html) if d == "yuklu") == 21

    def test_bos_yazi_sayisi_32(self, html):
        assert sum(1 for _, d, _ in tablo_satirlari(html) if d == "bos-yazi") == 32


# ======================================================================
# 3. SAYAC OZETI + KOD KUMESI TUTARLILIGI (4)
# ======================================================================
class TestSayacVeKodKumesi:
    def test_sayac_ozeti_metni(self, html):
        assert "53 ogeden 21'i YUKLU, 32'si BOS YAZI (2026-07-15, 1700/1700 test)" in html

    def test_tablo_kod_kumesi_spec_ile_esit(self, html):
        tablo_kodlari = [k for k, _, _ in tablo_satirlari(html)]
        assert sorted(tablo_kodlari) == sorted(KODLAR)
        assert len(set(tablo_kodlari)) == 53

    def test_baslik_rozetleri_tabloyla_tutarli(self, html):
        # baslik rozetlerinin kod kumesi (AKIS haric) tablo kodlarinin alt kumesi
        tablo_kodlari = {k for k, _, _ in tablo_satirlari(html)}
        baslik_kodlari = {m.group(2) for m in BADGE_RE.finditer(html)}
        assert baslik_kodlari - set(AKIS_KODLAR) <= tablo_kodlari
        # 52 baslik rozeti: 9 AKIS + 43 tablo kodu (9 BOLUM + 13 B + 13 C + 8 BLOK)
        assert len(baslik_kodlari) == 52
        assert len(baslik_kodlari & tablo_kodlari) == 43

    def test_akis_kodlari_tabloda_yok(self, html):
        satir_kodlari = {k for k, _, _ in tablo_satirlari(html)}
        for kod in AKIS_KODLAR:
            assert kod not in satir_kodlari, f"{kod} tabloya girmis"
        assert "AKIS kodlari bu tabloya girmez" in envanter_bolumu(html)  # aciklandi


# ======================================================================
# 4. ARIA-LABEL + TEK ID (4)
# ======================================================================
class TestAriaVeId:
    def test_aria_label_baslik_rozetlerinde(self, html):
        for m in BADGE_RE.finditer(html):
            assert m.group(5), f"aria-label bos: {m.group(2)}"
            if m.group(3) == "yuklu":
                assert m.group(5) == "SISTEMDE YUKLU"
            else:
                assert "BOS YAZI" in m.group(5)

    def test_aria_label_tablo_durum_hucrelerinde(self, html):
        for kod, durum, govde in tablo_satirlari(html):
            m = re.search(r'<span class="yd yd-(?:ok|no)" aria-label="([^"]+)">', govde)
            assert m, f"{kod}: tablo durum hucresinde aria-label yok"
            if durum == "yuklu":
                assert m.group(1) == "SISTEMDE YUKLU"
            else:
                assert "BOS YAZI" in m.group(1)

    def test_envanter_id_tek(self, html):
        assert html.count('id="sistem-yukluluk-envanteri"') == 1

    def test_json_id_tek(self, html):
        assert html.count('id="sistem-envanteri-json"') == 1
