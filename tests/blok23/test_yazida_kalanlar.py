"""BLOK 23 - YAZIDA KALANLAR (durust liste, 12 madde): TAM 12 pytest testi.

Kapsam (SPEC-BLOK23 dagilimi): 12 maddenin TAMAMI listede (12).
Her madde icin ayirt edici ibare(ler) e) YAZIDA KALANLAR diliminde aranir.

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

YK_BASI = "e) YAZIDA KALANLAR"
YK_SONU = "f) BOSTA / BEKLEMEDE"

# (madde_adi, zorunlu ibareler) — her madde icin 1 test
MADDELER = [
    ("madde01_blok5_repo_yok", ["1. BLOK 5 evren modulu kaynaklari", "YAZIDA KALDI", "Bu repoda YOK"]),
    ("madde02_endeks_motoru_repo_yok", ["2. Endeks Skorlama motoru", "268 test", "YAZIDA KALDI"]),
    ("madde03_vps_deployment", ["3. Gercek VPS deployment", "YAZIDA KALDI", "deploy/deploy.sh"]),
    ("madde04_lisansli_api_bos", ["4. Lisansli fiyat API baglantisi", "YAZIDA KALDI", "LICENSED_PRICE_API"]),
    ("madde05_resmi_liste_provider", ["5. Resmi XK100 listesi provider", "YAZIDA KALDI", "RETMEZ"]),
    ("madde06_mobil_hazir_bekliyor", ["6. Native mobil uygulama", "HAZIR_BEKLIYOR", "api-contract.json"]),
    ("madde07_bildirim_kurallari", ["7. Musteri bildirim kurallari", "YAZIDA KALDI", "events.py"]),
    ("madde08_telegram_pasif", ["8. Telegram entegrasyonu", "PASIF", "TELEGRAM_BOT_TOKEN"]),
    ("madde09_postgres_secenek", ["9. PostgreSQL yedek motoru", "YAZIDA KALDI", "BACKUP_ENGINE"]),
    ("madde10_hisse_skorlama_canli_degil", ["10. Hisse Skorlama modulu", "YAZIDA KALDI", "HENUZ CANLI DEGIL"]),
    ("madde11_bolum_5_8_motorlari", ["11. Teknik gosterge/seviye/portfoy analiz motorlari", "YAZIDA KALDI", "DEMO"]),
    ("madde12_0945_yayin", ["12. 09:45 rapor yayini", "YAZIDA KALDI"]),
]


@pytest.fixture(scope="module")
def yk() -> str:
    assert DOCS_HTML.is_file(), f"docs.html bulunamadi: {DOCS_HTML}"
    html = DOCS_HTML.read_text(encoding="utf-8")
    s = html.find(YK_BASI)
    assert s != -1, "YAZIDA KALANLAR bolumu yok"
    e = html.find(YK_SONU, s)
    assert e != -1, "YAZIDA KALANLAR sonu (BOSTA) bulunamadi"
    return html[s:e]


@pytest.mark.parametrize(
    "madde_adi,ibareler", MADDELER, ids=[m[0] for m in MADDELER]
)
def test_yazida_kalan_madde(yk: str, madde_adi: str, ibareler: list) -> None:
    for ibare in ibareler:
        assert ibare in yk, f"{madde_adi}: eksik ibare -> {ibare}"
