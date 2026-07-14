"""BLOK 23 - ana-sayfa-is-akisi-rehberi bolumu: TAM 16 pytest testi.

Kapsam (SPEC-BLOK23 dagilimi):
1-2.  Bolum id'si + ftr'den once konum (2)
3.    index.html'deki 17 canvas id'sinin TAMAMI rehberde gecer (DINAMIK cikarim) (1)
4.    xk100-* 8 alan id'si (1)
5.    8 filtre id'si (1)
6.    siralama + sayfalama id'leri (1)
7.    sd-* buton id'leri (1)
8-9.  API uclari rehberde (2)
10-11. Durum etiketleri CANLI-API/DEMO/BOSTA her satirda (2)
12-13. Demo ogeler DEMO etiketli (2)
14.   Eski envanter kartina guncelleme notu eklendi (1)
15-16. Rehberde "Is akisi" aciklamalari (2)

Dosya yolu test icinde goreli cozumlenir (tests/blok18 cift-aday deseni).
"""
from __future__ import annotations

import re
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

REHBER_ID = 'id="ana-sayfa-is-akisi-rehberi"'
CANVAS_DESENI = re.compile(r'canvas[^>]*id="([^"]+)"')


@pytest.fixture(scope="module")
def docs() -> str:
    assert DOCS_HTML.is_file(), f"docs.html bulunamadi: {DOCS_HTML}"
    return DOCS_HTML.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def index() -> str:
    assert INDEX_HTML.is_file(), f"index.html bulunamadi: {INDEX_HTML}"
    return INDEX_HTML.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def rehber(docs: str) -> str:
    s = docs.find(REHBER_ID)
    assert s != -1, "ana-sayfa-is-akisi-rehberi bolumu yok"
    e = docs.find('class="ftr"', s)
    assert e != -1, "ftr bulunamadi"
    return docs[s:e]


def _satir(dilim: str, oge: str) -> str:
    m = re.search(r"<tr>(?:(?!</tr>).)*?" + re.escape(oge) + r"(?:(?!</tr>).)*</tr>", dilim, re.DOTALL)
    assert m, f"oge satiri bulunamadi: {oge}"
    return m.group(0)


# --- 1-2: bolum id'si + ftr'den once konum ------------------------------------
def test_bolum_id_var(docs: str) -> None:
    assert REHBER_ID in docs


def test_bolum_ftrden_once(docs: str) -> None:
    assert docs.find(REHBER_ID) < docs.find('class="ftr"'), \
        "rehber ftr'den once olmali (sayfanin en alt bolumu)"


# --- 3: 17 canvas id'si DINAMIK cikarimla rehberde -----------------------------
def test_17_canvas_dinamik(index: str, rehber: str) -> None:
    canvas_ids = CANVAS_DESENI.findall(index)
    assert len(canvas_ids) == 17, f"index.html'de 17 canvas bekleniyor, bulunan: {len(canvas_ids)}"
    for cid in canvas_ids:
        assert cid in rehber, f"canvas id rehberde eksik: {cid}"


# --- 4: xk100-* 8 alan id'si ---------------------------------------------------
def test_xk100_8_alan(index: str, rehber: str) -> None:
    alan_ids = sorted(set(re.findall(
        r'id="(xk100-(?:scan-status|scanned-count|full-count|partial-count|'
        r'failed-count|avg-confidence|last-updated|scan-run-id))"', index)))
    assert len(alan_ids) == 8, f"index.html'de 8 xk100 alani bekleniyor: {alan_ids}"
    for aid in alan_ids:
        assert aid in rehber, f"xk100 alani rehberde eksik: {aid}"


# --- 5: 8 filtre id'si ----------------------------------------------------------
def test_8_filtre(index: str, rehber: str) -> None:
    filtre_ids = sorted(set(re.findall(r'id="(flt-[^"]+)"', index)))
    assert len(filtre_ids) == 8, f"index.html'de 8 filtre bekleniyor: {filtre_ids}"
    for fid in filtre_ids:
        assert fid in rehber, f"filtre rehberde eksik: {fid}"


# --- 6: siralama + sayfalama id'leri --------------------------------------------
def test_siralama_sayfalama(index: str, rehber: str) -> None:
    beklenen = ["sort-by", "sort-dir", "page-size", "page-prev", "page-next", "page-info"]
    for bid in beklenen:
        assert f'id="{bid}"' in index, f"index.html'de eksik: {bid}"
        assert bid in rehber, f"rehberde eksik: {bid}"


# --- 7: sd-* buton id'leri -------------------------------------------------------
def test_sd_butonlari(index: str, rehber: str) -> None:
    for bid in ["sd-close", "sd-btn-raw", "sd-btn-adj", "sd-range-buttons"]:
        assert f'id="{bid}"' in index, f"index.html'de eksik: {bid}"
        assert bid in rehber, f"rehberde eksik: {bid}"
    assert "sdOpen(sym)" in rehber


# --- 8-9: API uclari rehberde ----------------------------------------------------
def test_api_uclari_xk100(rehber: str) -> None:
    assert "/api/xk100/scan/latest" in rehber
    assert "/api/xk100/stocks" in rehber


def test_api_uclari_stocks(rehber: str) -> None:
    assert "/api/stocks/" in rehber
    for alt in ["/kap", "/news", "/corporate-actions", "/restrictions", "/prices"]:
        assert alt in rehber, f"alt uc eksik: {alt}"


# --- 10-11: durum etiketleri her satirda ------------------------------------------
def test_canli_api_etiketi_yaygin(rehber: str) -> None:
    adet = rehber.count("CANLI-API'YE BAGLI")
    assert adet >= 20, f"CANLI-API'YE BAGLI etiketi {adet} satirda (beklenen >= 20)"


def test_durum_etiketleri_cesitliligi(rehber: str) -> None:
    for etiket in ["CANLI-API'YE BAGLI", "DEMO", "BOSTA-BEKLEMEDE", "BOSTA"]:
        assert etiket in rehber, f"durum etiketi eksik: {etiket}"


# --- 12-13: demo ogeler DEMO etiketli ----------------------------------------------
def test_gauge_demo_etiketli(rehber: str) -> None:
    satir = _satir(rehber, ">gauge<")
    assert "DEMO" in satir


def test_demo_canvaslar_demo_etiketli(rehber: str) -> None:
    for cid in ["c1", "mumASELS", "sevALFAS", "c8"]:
        satir = _satir(rehber, f">{cid}<")
        assert "DEMO" in satir, f"{cid} satirinda DEMO etiketi yok"


# --- 14: eski envanter kartina guncelleme notu --------------------------------------
def test_eski_karta_guncelleme_notu(docs: str) -> None:
    kart = docs.find("MUSTERI SAYFASI TAM ENVANTERI")
    not_metni = "Bu kart BLOK 18 oncesi durumu anlatir"
    n = docs.find(not_metni)
    assert kart != -1 and n != -1, "guncelleme notu eklenmedi"
    assert kart < n, "not eski envanter kartindan sonra olmali"
    assert "ana-sayfa-is-akisi-rehberi" in docs[n:n + 300]


# --- 15-16: rehberde "Is akisi" aciklamalari -----------------------------------------
def test_is_akisi_sutun_basliklari(rehber: str) -> None:
    adet = rehber.count("Is akisi")
    assert adet >= 6, f"Is akisi ibaresi {adet} (A-F tablo basliklari + satirlar eksik)"


def test_is_akisi_aciklamalari_dolu(rehber: str) -> None:
    # her tablo satirinda is akisi aciklamasi var: ornek akis fiilleri
    for ibare in ["cagrilir", "cizilir", "yeniden cekilir", "dolar"]:
        assert ibare in rehber, f"is akisi aciklamasi eksik: {ibare}"
