"""BLOK 24 - BLOK karti rozetleri: TAM 18 pytest testi.

Kapsam (SPEC-BLOK24 dagilimi):
- BLOK 5 rozeti bos-yazi + "bu repoda yuklu degil" notu (2)
- BLOK 6 + 17-22 rozetleri yuklu (7)
- blok kartlarinda mevcut "TAMAMLANDI" metni korundu (7)
- rozetler kart h3'unde (2)
"""
from __future__ import annotations

import re

import pytest

try:
    from tests.blok24.envanter_data import (
        BADGE_RE, BLOK_KART_YUKLU, DOCS_HTML, TIK, X, h3_icinde_kod,
    )
except ImportError:  # pragma: no cover
    from .envanter_data import (
        BADGE_RE, BLOK_KART_YUKLU, DOCS_HTML, TIK, X, h3_icinde_kod,
    )


@pytest.fixture(scope="module")
def html() -> str:
    assert DOCS_HTML.is_file(), f"docs.html bulunamadi: {DOCS_HTML}"
    return DOCS_HTML.read_text(encoding="utf-8")


# ======================================================================
# 1. BLOK 5 — bos-yazi + ozel not (2)
# ======================================================================
class TestBlok5:
    def test_blok5_rozeti_bos_yazi(self, html):
        h3 = h3_icinde_kod(html, "BLOK-5")
        assert h3, "BLOK-5 rozeti kart h3'unde yok"
        m = BADGE_RE.search(h3)
        assert m and m.group(2) == "BLOK-5"
        assert m.group(1) == "yd-no" and m.group(3) == "bos-yazi"
        assert m.group(4) == "yok"

    def test_blok5_bu_repoda_yuklu_degil_notu(self, html):
        h3 = h3_icinde_kod(html, "BLOK-5")
        m = BADGE_RE.search(h3)
        assert m.group(6) == f"{X} BOS YAZI (bu repoda yuklu degil)"
        assert "bu repoda yuklu degil" in m.group(5)  # aria-label


# ======================================================================
# 2. BLOK 6 + 17-22 — yuklu (7)
# ======================================================================
class TestBlokYuklu:
    @pytest.mark.parametrize("kod", BLOK_KART_YUKLU)
    def test_blok_rozeti_yuklu(self, html, kod):
        h3 = h3_icinde_kod(html, kod)
        assert h3, f"{kod} rozeti kart h3'unde yok"
        m = BADGE_RE.search(h3)
        assert m and m.group(2) == kod
        assert m.group(1) == "yd-ok" and m.group(3) == "yuklu"
        assert m.group(4) == "100/100"
        assert m.group(6).startswith(TIK + " SISTEMDE YUKLU")


# ======================================================================
# 3. MEVCUT "TAMAMLANDI" METNI KORUNDU (7)
# ======================================================================
class TestTamamlandiKorundu:
    @pytest.mark.parametrize("kod", BLOK_KART_YUKLU)
    def test_tamamlandi_metni_korundu(self, html, kod):
        h3 = h3_icinde_kod(html, kod)
        assert "TAMAMLANDI" in h3, f"{kod} kartinda TAMAMLANDI metni bozulmus"
        # pill (TEST_GECTI) veya baslik ici "TEST GECTI" — ikisi de korunur
        assert re.search(r"TEST[_ ]GECTI", h3), \
            f"{kod} kartinda TEST_GECTI ifadesi bozulmus"


# ======================================================================
# 4. ROZETLER KART H3'UNDE (2)
# ======================================================================
class TestRozetKartH3:
    def test_yuklu_blok_rozetleri_h3_icinde(self, html):
        for kod in BLOK_KART_YUKLU:
            assert h3_icinde_kod(html, kod), f"{kod} rozeti h3 disinda"

    def test_blok5_rozeti_h3_icinde(self, html):
        h3 = h3_icinde_kod(html, "BLOK-5")
        assert h3 and "BLOK 5/22 TAMAMLANDI" in h3
