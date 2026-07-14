"""BLOK 23 - BOSTA / BEKLEMEDE envanteri: TAM 10 pytest testi.

Kapsam (SPEC-BLOK23 dagilimi):
1-6. BOSTA/BOSTA-BEKLEMEDE isaretli ogeler: gauge, scan-card, hisse ozeti,
     sd-btn-adj, source_health ekrani, haber AI (6)
7.   offline-banner "gizli varsayilan" notu (1)
8-10. Hicbir BOSTA ogeye "canli" denmez (3 yasakli ifade) (3)

Dosya yolu test icinde goreli cozumlenir (tests/blok18 cift-aday deseni).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CANDIDATES = [
    _REPO_ROOT.parent / "telegram-sender" / "docs.html",  # yerel calisma dizini
    _REPO_ROOT / "docs.html",                             # GitHub repo koku
]
DOCS_HTML = next((p for p in _CANDIDATES if p.is_file()), _CANDIDATES[-1])

BOSTA_BASI = "f) BOSTA / BEKLEMEDE"
BOSTA_SONU = "<!-- 4. HISSE SKORLAMA -->"

# (oge ibaresi, ayni satirda beklenen durum etiketi)
OGELER = [
    ("gauge", "DEMO"),
    ("xk100-scan-card", "BOSTA-BEKLEMEDE"),
    ("stk-table", "BOSTA-BEKLEMEDE"),
    ("sd-btn-adj", "BOSTA"),
    ("source_health", "BOSTA"),
    ("ai_adapter", "BOSTA"),
]


@pytest.fixture(scope="module")
def bosta() -> str:
    assert DOCS_HTML.is_file(), f"docs.html bulunamadi: {DOCS_HTML}"
    html = DOCS_HTML.read_text(encoding="utf-8")
    s = html.find(BOSTA_BASI)
    assert s != -1, "BOSTA / BEKLEMEDE bolumu yok"
    e = html.find(BOSTA_SONU, s)
    assert e != -1, "BOSTA bolumu sonu bulunamadi"
    return html[s:e]


def _satir(dilim: str, oge: str) -> str:
    m = re.search(r"<tr>(?:(?!</tr>).)*?" + re.escape(oge) + r"(?:(?!</tr>).)*</tr>", dilim, re.DOTALL)
    assert m, f"oge satiri bulunamadi: {oge}"
    return m.group(0)


# --- 1-6: BOSTA/BOSTA-BEKLEMEDE isaretli ogeler -------------------------------
@pytest.mark.parametrize("oge,etiket", OGELER, ids=[o[0] for o in OGELER])
def test_bosta_oge_isaretli(bosta: str, oge: str, etiket: str) -> None:
    satir = _satir(bosta, oge)
    assert etiket in satir, f"{oge} satirinda {etiket} etiketi yok"


# --- 7: offline-banner gizli varsayilan notu ----------------------------------
def test_offline_banner_gizli_varsayilan(bosta: str) -> None:
    satir = _satir(bosta, "offline-banner")
    assert "gizli varsayilan" in satir
    assert "BOSTA" in satir


# --- 8-10: hicbir BOSTA ogeye "canli" denmez (3 yasakli ifade, bosta dilimi) ---
@pytest.mark.parametrize(
    "yasakli", ["CANLI-API'YE BAGLI", "CANLI (PUBLISHED)", "canli veri"]
)
def test_bosta_ogeye_canli_denmez(bosta: str, yasakli: str) -> None:
    assert yasakli.lower() not in bosta.lower(), \
        f"BOSTA bolumunde yasakli canli ibaresi: {yasakli}"
