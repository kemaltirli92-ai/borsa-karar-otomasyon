"""BLOK 24 - harf serisi rozetleri (B1-B13 / C1-C13): TAM 26 pytest testi.

Kapsam (SPEC-BLOK24 dagilimi — KESIN toplam 26):
- B1..B13 rozetleri tek tek var + hepsi bos-yazi (13)
- B serisi toplu bos-yazi + B3 ozel (unit var motor yok) (1)
- C1..C11 rozetleri tek tek yuklu (11)
- C serisi toplu yuklu — C12 + C13 dahil tamami (1)

Her rozette data-kod + data-durum zorunlu (tek-tek testlerde dogrulanir).
"""
from __future__ import annotations

import pytest

try:
    from tests.blok24.envanter_data import (
        BADGE_RE, B_KODLAR, C_KODLAR, DOCS_HTML, TIK, X, h3_icinde_kod,
    )
except ImportError:  # pragma: no cover
    from .envanter_data import (
        BADGE_RE, B_KODLAR, C_KODLAR, DOCS_HTML, TIK, X, h3_icinde_kod,
    )


@pytest.fixture(scope="module")
def html() -> str:
    assert DOCS_HTML.is_file(), f"docs.html bulunamadi: {DOCS_HTML}"
    return DOCS_HTML.read_text(encoding="utf-8")


# ======================================================================
# 1. B1..B13 TEK TEK — 13 test (hepsi bos-yazi)
# ======================================================================
class TestBRozetiTekTek:
    @pytest.mark.parametrize("kod", B_KODLAR)
    def test_b_rozeti_bos_yazi(self, html, kod):
        h3 = h3_icinde_kod(html, kod)
        assert h3, f"{kod} rozeti hicbir h3 icinde yok"
        assert f'<span class="bolum-no"' in h3, f"{kod} bolum-no span'i korunmamis"
        m = BADGE_RE.search(h3)
        assert m and m.group(2) == kod, f"{kod} data-kod yanlis"
        assert m.group(3) == "bos-yazi", f"{kod} bos-yazi olmali"
        assert m.group(1) == "yd-no"
        assert m.group(4) == "yok"
        assert m.group(6).startswith(X + " BOS YAZI")


# ======================================================================
# 2. B SERISI TOPLU + B3 OZEL — 1 test
# ======================================================================
class TestBToplu:
    def test_b_serisi_hepsi_bos_yazi_b3_ozel(self, html):
        for kod in B_KODLAR:
            m = BADGE_RE.search(h3_icinde_kod(html, kod))
            assert m.group(1) == "yd-no" and m.group(3) == "bos-yazi", \
                f"{kod} bos-yazi degil"
        # B3: zamanlayici unitler repoda VAR ama tetiklenen motor yok
        m3 = BADGE_RE.search(h3_icinde_kod(html, "B3"))
        assert m3.group(3) == "bos-yazi"
        assert "Zamanlayici unitler repoda VAR ama tetiklenen motor yok" in html


# ======================================================================
# 3. C1..C11 TEK TEK — 11 test (hepsi yuklu)
# ======================================================================
class TestCRozetiTekTek:
    @pytest.mark.parametrize("kod", C_KODLAR[:11])  # C1..C11
    def test_c_rozeti_yuklu(self, html, kod):
        h3 = h3_icinde_kod(html, kod)
        assert h3, f"{kod} rozeti hicbir h3 icinde yok"
        assert "TEST_GECTI" in h3, f"{kod} mevcut TEST_GECTI pill'i korunmamis"
        m = BADGE_RE.search(h3)
        assert m and m.group(2) == kod, f"{kod} data-kod yanlis"
        assert m.group(3) == "yuklu", f"{kod} yuklu olmali"
        assert m.group(1) == "yd-ok"
        assert m.group(4) == "100/100"
        assert m.group(6).startswith(TIK + " SISTEMDE YUKLU")


# ======================================================================
# 4. C SERISI TOPLU — C12 + C13 DAHIL TAMAMI — 1 test
# ======================================================================
class TestCToplu:
    def test_c_serisi_tamami_yuklu_c12_c13_dahil(self, html):
        assert len(C_KODLAR) == 13
        for kod in C_KODLAR:  # C1..C13 — C12 ve C13 burada tek tek dogrulanir
            h3 = h3_icinde_kod(html, kod)
            assert h3, f"{kod} rozeti hicbir h3 icinde yok"
            m = BADGE_RE.search(h3)
            assert m.group(1) == "yd-ok" and m.group(3) == "yuklu", \
                f"{kod} yuklu degil"
            assert m.group(4) == "100/100"
