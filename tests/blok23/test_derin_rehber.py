"""BLOK 23 - blok-serisi-derin-rehber mega bolumu: TAM 22 pytest testi.

Kapsam (SPEC-BLOK23 dagilimi):
1.     Mega bolum id'si var (1)
2-19.  BLOK 5..22'nin TAMAMI rehberde gecer (18)
20.    Genel mimari akis tablosu (1)
21-22. Her blok alt kartinda "Is akisi" + "Yapay zeka" satiri (2)

Dosya yolu test icinde goreli cozumlenir (tests/blok18 cift-aday deseni).
"""
from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CANDIDATES = [
    _REPO_ROOT.parent / "telegram-sender" / "docs.html",  # yerel calisma dizini
    _REPO_ROOT / "docs.html",                             # GitHub repo koku
]
DOCS_HTML = next((p for p in _CANDIDATES if p.is_file()), _CANDIDATES[-1])

REHBER_ID = 'id="blok-serisi-derin-rehber"'
REHBER_SONU = "<!-- 4. HISSE SKORLAMA -->"


@pytest.fixture(scope="module")
def html() -> str:
    assert DOCS_HTML.is_file(), f"docs.html bulunamadi: {DOCS_HTML}"
    return DOCS_HTML.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def rehber(html: str) -> str:
    s = html.find(REHBER_ID)
    assert s != -1, "blok-serisi-derin-rehber bolumu yok"
    e = html.find(REHBER_SONU, s)
    assert e != -1, "rehber sonu (BOLUM 4) bulunamadi"
    return html[s:e]


# --- 1: mega bolum id'si var --------------------------------------------------
def test_mega_bolum_id_var(html: str) -> None:
    assert REHBER_ID in html


# --- 2-19: BLOK 5..22'nin TAMAMI rehberde gecer -------------------------------
@pytest.mark.parametrize("blok_no", list(range(5, 23)))
def test_blok_rehberde_gecer(rehber: str, blok_no: int) -> None:
    assert f"BLOK {blok_no} " in rehber, f"BLOK {blok_no} derin rehberde eksik"


# --- 20: genel mimari akis tablosu --------------------------------------------
def test_genel_mimari_akis_tablosu(rehber: str) -> None:
    assert "GENEL MIMARI AKIS" in rehber
    # akis halkalari + gercek modul yollari ayni tabloda
    for halka in ["Evren", "Kimlik", "OHLCV Dogrulama", "KAP", "Haber",
                  "Zamanlama", "Veri guveni", "Veri tabani", "API", "Zarf", "Web + Mobil"]:
        assert halka in rehber, f"mimari akis halkasi eksik: {halka}"
    for modul in ["symbol_identity.py", "price_collection/", "validation/",
                  "kap_collection/", "news/", "corporate_actions/",
                  "orchestration/", "confidence/", "db/", "envelope.py", "index.html"]:
        assert modul in rehber, f"mimari akis modulu eksik: {modul}"


# --- 21-22: her blok alt kartinda Is akisi + Yapay zeka satiri ----------------
def test_her_blok_kartinda_is_akisi_satiri(rehber: str) -> None:
    adet = rehber.count("Is akisi adimlari")
    assert adet >= 18, f"Is akisi adimlari satiri {adet}/18 (BLOK 5-22 eksik)"


def test_her_blok_kartinda_yapay_zeka_satiri(rehber: str) -> None:
    adet = rehber.count("Yapay zeka kullanimi")
    assert adet >= 18, f"Yapay zeka kullanimi satiri {adet}/18 (BLOK 5-22 eksik)"
