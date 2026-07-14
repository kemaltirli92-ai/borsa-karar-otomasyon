"""BLOK 23 - docs.html BLOK 17-22 kartlari: TAM 12 pytest testi.

Kapsam (SPEC-BLOK23 dagilimi):
1-6.   BLOK 17-22 kartlari docs.html'de var (6)
7-10.  Kartlardaki gercek dosya yollari repoda/site'de mevcut (4)
11-12. Kartlarda test sayilari dogru (100/100, 1600/1600) (2)

Statik analiz: docs.html okunur; gercek dosya yollari dosya sisteminde
dogrulanir (ag/soket erisimi YOK).

Dosya yolu test icinde goreli cozumlenir (tests/blok18 cift-aday deseni):
tests/blok23/test_blok_kartlari.py -> ../../.. -> telegram-sender/docs.html
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
_SITE_DIR = DOCS_HTML.parent


@pytest.fixture(scope="module")
def html() -> str:
    assert DOCS_HTML.is_file(), f"docs.html bulunamadi: {DOCS_HTML}"
    return DOCS_HTML.read_text(encoding="utf-8")


def _blok_karti_dilimi(html: str, blok_no: int) -> str:
    """BLOK N kartinin basligindan bir sonraki karta kadar olan dilim."""
    marker = f"BLOK {blok_no}/22 TAMAMLANDI"
    s = html.find(marker)
    assert s != -1, f"BLOK {blok_no} karti bulunamadi"
    return html[s : s + 4000]


# --- 1-6: BLOK 17-22 kartlari var -------------------------------------------
@pytest.mark.parametrize("blok_no", [17, 18, 19, 20, 21, 22])
def test_blok_karti_var(html: str, blok_no: int) -> None:
    assert f"BLOK {blok_no}/22 TAMAMLANDI" in html


# --- 7-10: kartlardaki gercek dosya yollari mevcut ---------------------------
def test_blok20_karti_dosya_yollari_gercek(html: str) -> None:
    dilim = _blok_karti_dilimi(html, 20)
    assert "manifest.webmanifest" in dilim and "sw.js" in dilim
    assert "docs/api-contract.json" in dilim and "events.py" in dilim
    assert (_SITE_DIR / "manifest.webmanifest").is_file()
    assert (_SITE_DIR / "sw.js").is_file()
    assert (_REPO_ROOT / "docs" / "api-contract.json").is_file()
    assert (_REPO_ROOT / "app" / "services" / "stock_scanning" / "events.py").is_file()


def test_blok21_karti_dosya_yollari_gercek(html: str) -> None:
    dilim = _blok_karti_dilimi(html, 21)
    for yol in ["backup_run.py", "source_health.py", "xk100-backup.service", "xk100-backup.timer"]:
        assert yol in dilim, f"blok21 kartinda eksik: {yol}"
    assert (_REPO_ROOT / "app" / "ops" / "backup_run.py").is_file()
    assert (_REPO_ROOT / "app" / "ops" / "source_health.py").is_file()
    assert (_REPO_ROOT / "systemd" / "xk100-backup.service").is_file()
    assert (_REPO_ROOT / "systemd" / "xk100-backup.timer").is_file()


def test_blok22_karti_dosya_yollari_gercek(html: str) -> None:
    dilim = _blok_karti_dilimi(html, 22)
    for yol in ["completion.py", "health.py", "deploy.sh", "nginx-xk100.conf", "certbot-https.sh", "logrotate-xk100"]:
        assert yol in dilim, f"blok22 kartinda eksik: {yol}"
    assert (_REPO_ROOT / "app" / "acceptance" / "completion.py").is_file()
    assert (_REPO_ROOT / "app" / "api" / "health.py").is_file()
    for art in ["deploy.sh", "nginx-xk100.conf", "certbot-https.sh", "logrotate-xk100"]:
        assert (_REPO_ROOT / "deploy" / art).is_file(), art


def test_blok17_18_19_karti_dosya_yollari_gercek(html: str) -> None:
    for blok_no in (17, 18, 19):
        dilim = _blok_karti_dilimi(html, blok_no)
        assert "telegram-sender/" in dilim, f"blok{blok_no} kartinda site dosya yolu eksik"
    assert DOCS_HTML.is_file()
    assert (_SITE_DIR / "index.html").is_file()
    assert (_REPO_ROOT / "tests" / "blok18" / "test_index_page.py").is_file()
    assert (_REPO_ROOT / "tests" / "blok19").is_dir()


# --- 11-12: kartlarda test sayilari dogru ------------------------------------
def test_kartlarda_100_100_sayilari(html: str) -> None:
    for blok_no in (18, 19, 20, 21, 22):
        dilim = _blok_karti_dilimi(html, blok_no)
        assert "100/100" in dilim, f"blok{blok_no} kartinda 100/100 eksik"
    # BLOK 17 durust notu: ayri test dizini yok
    dilim17 = _blok_karti_dilimi(html, 17)
    assert "tests/blok17" in dilim17 and "YOK" in dilim17
    assert not (_REPO_ROOT / "tests" / "blok17").exists()


def test_blok22_karti_toplam_1600(html: str) -> None:
    dilim = _blok_karti_dilimi(html, 22)
    assert "1600/1600" in dilim
