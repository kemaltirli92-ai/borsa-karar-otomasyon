"""BLOK 24 - rozet sayilari: TAM 22 pytest testi.

Kapsam (SPEC-BLOK24 dagilimi):
- 9 AKIS adimi rozeti (kod+durum dogru; durum BOLUM-N ile ayni) (9)
- 9 BOLUM rozeti (kod+durum dogru: BOLUM-3 yuklu, digerleri bos-yazi) (9)
- BOLUM-3 rozeti data-test="1700/1700" (1)
- rozetler h3/ttl icinde (1)
- ✓=U+2713 / ✗=U+2717 karakterleri dogru (2)

Yol cozumu: blok18 cift-aday deseni (telegram-sender / repo koku).
"""
from __future__ import annotations

import re

import pytest

try:
    from tests.blok24.envanter_data import (
        AKIS_TTL, BADGE_RE, DOCS_HTML, DURUM, TIK, X, h3_icinde_kod,
    )
except ImportError:  # pragma: no cover
    from .envanter_data import (
        AKIS_TTL, BADGE_RE, DOCS_HTML, DURUM, TIK, X, h3_icinde_kod,
    )


@pytest.fixture(scope="module")
def html() -> str:
    assert DOCS_HTML.is_file(), f"docs.html bulunamadi: {DOCS_HTML}"
    return DOCS_HTML.read_text(encoding="utf-8")


# ======================================================================
# 1. AKIS ADIMLARI — 9 rozet (kod + durum; durum BOLUM-N ile ayni)
# ======================================================================
class TestAkisRozetleri:
    @pytest.mark.parametrize("n,ttl", AKIS_TTL)
    def test_akis_adim_rozeti(self, html, n, ttl):
        kod = f"AKIS-{n}"
        beklenen = DURUM[f"BOLUM-{n}"]  # SPEC: AKIS durumu BOLUM-N ile ayni
        anchor = f'<span class="ttl">{ttl}</span>'
        assert html.count(anchor) == 1, f"akis adim basligi tek degil: {ttl}"
        # rozet, ttl span'inin hemen yanina eklenir
        m = re.search(re.escape(anchor) + r"(" + BADGE_RE.pattern + r")", html)
        assert m, f"{kod} rozeti ttl yaninda yok"
        sinif, rkod, durum, _, _, metin = m.groups()[1:]
        assert rkod == kod, f"rozet kodu yanlis: {rkod} != {kod}"
        assert durum == beklenen, f"{kod} durumu yanlis: {durum} != {beklenen}"
        if beklenen == "yuklu":
            assert sinif == "yd-ok" and f"{TIK} SISTEMDE YUKLU" in metin
        else:
            assert sinif == "yd-no" and f"{X} BOS YAZI" in metin


# ======================================================================
# 2. BOLUM BASLIKLARI — 9 rozet (BOLUM-3 yuklu, digerleri bos-yazi)
# ======================================================================
class TestBolumRozetleri:
    @pytest.mark.parametrize("kod", [f"BOLUM-{i}" for i in range(1, 10)])
    def test_bolum_rozeti(self, html, kod):
        beklenen = DURUM[kod]
        h3 = h3_icinde_kod(html, kod)
        assert h3, f"{kod} rozeti hicbir h3 icinde yok"
        m = BADGE_RE.search(h3)
        assert m and m.group(2) == kod
        assert m.group(3) == beklenen, f"{kod} durumu yanlis: {m.group(3)} != {beklenen}"
        if beklenen == "yuklu":
            assert m.group(1) == "yd-ok"
        else:
            assert m.group(1) == "yd-no"


# ======================================================================
# 3. ROZET DETAYLARI (4)
# ======================================================================
class TestRozetDetay:
    def test_bolum3_data_test_1700(self, html):
        h3 = h3_icinde_kod(html, "BOLUM-3")
        m = BADGE_RE.search(h3)
        assert m and m.group(4) == "1700/1700", "BOLUM-3 data-test 1700/1700 olmali"

    def test_rozetler_h3_ve_ttl_icinde(self, html):
        # her data-kod tasiyan rozet bir h3 govdesinde veya bir ttl satirinda olmali
        for m in BADGE_RE.finditer(html):
            satir = html[html.rfind("\n", 0, m.start()) + 1: html.find("\n", m.end())]
            assert "<h3>" in satir or 'class="ttl"' in satir, \
                f"rozet h3/ttl disinda: {m.group(2)}"

    def test_tik_karakteri_u2713(self, html):
        # yuklu rozetlerinde tam U+2713 + ASCII kelime
        for m in BADGE_RE.finditer(html):
            if m.group(1) == "yd-ok":
                assert m.group(6).startswith(TIK + " SISTEMDE YUKLU"), \
                    f"U+2713 eksik: {m.group(2)}"

    def test_carpi_karakteri_u2717(self, html):
        # bos-yazi rozetlerinde tam U+2717 + ASCII kelime
        for m in BADGE_RE.finditer(html):
            if m.group(1) == "yd-no":
                assert m.group(6).startswith(X + " BOS YAZI"), \
                    f"U+2717 eksik: {m.group(2)}"
