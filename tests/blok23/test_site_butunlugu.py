"""BLOK 23 - site butunlugu (koruma kilidi): TAM 8 pytest testi.

Kapsam (SPEC-BLOK23 dagilimi):
1-4. index.html korundu: BLOK18/19/20 markerlari + demo rozetler +
     HISSE SKORLAMA bandi (4)
5-7. docs.html mevcut bolumleri silinmedi: BOLUM 1-9 basliklari +
     C1-C13 + BLOK5/6 kartlari (3)
8.   docs.html'de yeni id'ler benzersiz (1)

Dosya yolu test icinde goreli cozumlenir (tests/blok18 cift-aday deseni).
"""
from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCS_CANDIDATES = [
    _REPO_ROOT.parent / "telegram-sender" / "docs.html",  # yerel calisma dizini
    _REPO_ROOT / "docs.html",                             # GitHub repo koku
]
_INDEX_CANDIDATES = [
    _REPO_ROOT.parent / "telegram-sender" / "index.html",  # yerel calisma dizini
    _REPO_ROOT / "index.html",                             # GitHub repo koku
]
DOCS_HTML = next((p for p in _DOCS_CANDIDATES if p.is_file()), _DOCS_CANDIDATES[-1])
INDEX_HTML = next((p for p in _INDEX_CANDIDATES if p.is_file()), _INDEX_CANDIDATES[-1])

YENI_IDLER = ["blok-serisi-derin-rehber", "ana-sayfa-is-akisi-rehberi"]


@pytest.fixture(scope="module")
def docs() -> str:
    assert DOCS_HTML.is_file(), f"docs.html bulunamadi: {DOCS_HTML}"
    return DOCS_HTML.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def index() -> str:
    assert INDEX_HTML.is_file(), f"index.html bulunamadi: {INDEX_HTML}"
    return INDEX_HTML.read_text(encoding="utf-8")


# --- 1-4: index.html korundu ----------------------------------------------------
def test_index_blok18_markerlari(index: str) -> None:
    assert 'id="xk100-scan-card"' in index
    assert 'id="stk-table"' in index
    assert 'id="flt-symbol"' in index


def test_index_blok19_markerlari(index: str) -> None:
    assert 'id="stk-detail"' in index
    assert 'id="sd-candles"' in index
    assert 'id="sd-volume"' in index
    assert 'id="sd-btn-adj"' in index


def test_index_demo_rozetleri(index: str) -> None:
    assert 'id="demo-badge-tarih"' in index
    assert 'id="demo-band-favori"' in index
    assert 'id="demo-band-asels"' in index
    assert 'id="demo-band-portfoy"' in index


def test_index_hisse_skorlama_bandi(index: str) -> None:
    assert "HISSE SKORLAMA MODULU HENUZ CANLI DEGIL" in index
    assert "HAZIR BEKLIYOR" in index  # b20-footer native durumu


# --- 5-7: docs.html mevcut bolumleri silinmedi -------------------------------------
def test_docs_bolum_basliklari_korundu(docs: str) -> None:
    for baslik in ["VERI TOPLAMA", "HISSE TARAMASI", "HISSE SKORLAMA",
                   "TEKNIK GOSTERGE ANALIZI", "SEVIYE HARITASI",
                   "HABER ANALIZI SISTEMI", "PORTFOY DAGILIMI", "RAPOR YAYINI",
                   "ENDEKS SKOR"]:
        assert baslik in docs, f"bolum basligi silinmis: {baslik}"


def test_docs_c1_c13_kartlari_korundu(docs: str) -> None:
    for n in range(1, 14):
        assert f"C{n} — " in docs, f"C{n} karti silinmis"


def test_docs_blok5_blok6_kartlari_korundu(docs: str) -> None:
    assert "BLOK 5/22 TAMAMLANDI" in docs
    assert "BLOK 6/22 TAMAMLANDI" in docs
    assert "MUSTERI SAYFASI TAM ENVANTERI" in docs


# --- 8: yeni id'ler benzersiz -------------------------------------------------------
def test_yeni_idler_benzersiz(docs: str) -> None:
    for yeni_id in YENI_IDLER:
        assert docs.count(f'id="{yeni_id}"') == 1, f"id tekil degil: {yeni_id}"
