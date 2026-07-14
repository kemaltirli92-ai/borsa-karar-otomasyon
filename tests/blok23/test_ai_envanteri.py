"""BLOK 23 - YAPAY ZEKA ENVANTERI (durust tablo): TAM 8 pytest testi.

Kapsam (SPEC-BLOK23 dagilimi):
1-2. ai_adapter KAPALI ibaresi (2)
3.   "bunun disinda yapay zeka cagrisi YOKTUR" ibaresi (1)
4.   Jeopolitik AI notu (1)
5.   .env'de AI anahtar alani olmadigi ibaresi + .env.example dogrulamasi (1)
6-8. Sahte "AI aktif" iddiasi YOK (3 yasakli ifade taramasi) (3)

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

AI_BASI = "d) YAPAY ZEKA ENVANTERI"
AI_SONU = "e) YAZIDA KALANLAR"
_AI_ANAHTAR_DESENI = re.compile(
    r"(GEMINI|OPENAI|CHATGPT|KIMI|ANTHROPIC|CLAUDE|AI_API_KEY|AI_KEY)", re.IGNORECASE
)


@pytest.fixture(scope="module")
def html() -> str:
    assert DOCS_HTML.is_file(), f"docs.html bulunamadi: {DOCS_HTML}"
    return DOCS_HTML.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def ai(html: str) -> str:
    s = html.find(AI_BASI)
    assert s != -1, "YAPAY ZEKA ENVANTERI bolumu yok"
    e = html.find(AI_SONU, s)
    assert e != -1, "AI envanteri sonu (YAZIDA KALANLAR) bulunamadi"
    return html[s:e]


# --- 1-2: ai_adapter KAPALI ----------------------------------------------------
def test_ai_adapter_kapali_ibaresi(ai: str) -> None:
    assert "ai_adapter.py" in ai
    assert "OPSIYONEL, KAPALI" in ai


def test_ai_adapter_detaylari(ai: str) -> None:
    assert "ai_client=None" in ai
    assert "DURDURMAZ" in ai  # AI hatasi taramayi DURDURMAZ
    assert "belirsiz" in ai   # yalnizca belirsiz eslesmeleri oylar


# --- 3: bunun disinda yapay zeka cagrisi yoktur --------------------------------
def test_bunun_disinda_yoktur_ibaresi(ai: str) -> None:
    assert "bunun disinda hicbir blokta yapay zeka cagrisi yoktur" in ai.lower()


# --- 4: jeopolitik AI notu ------------------------------------------------------
def test_jeopolitik_ai_notu(ai: str) -> None:
    assert "Jeopolitik hibrit AI" in ai
    assert "bu repoda yapay zeka cagrisi YOKTUR" in ai


# --- 5: .env'de AI anahtar alani yok (ibare + gercek dosya dogrulamasi) ---------
def test_env_ai_anahtari_yok(ai: str) -> None:
    assert ".env dosyasinda yapay zeka API anahtar alani YOK" in ai
    env_example = _REPO_ROOT / ".env.example"
    assert env_example.is_file(), ".env.example repoda yok"
    icerik = env_example.read_text(encoding="utf-8")
    assert not _AI_ANAHTAR_DESENI.search(icerik), \
        ".env.example icinde yapay zeka API anahtar alani bulundu (ibare yanlis olur)"


# --- 6-8: sahte "AI aktif" iddiasi YOK (3 yasakli ifade, tum sayfa) -------------
@pytest.mark.parametrize("yasakli", ["AI aktif", "yapay zeka aktif", "AI calisiyor"])
def test_sahte_ai_iddiasi_yok(html: str, yasakli: str) -> None:
    assert yasakli.lower() not in html.lower(), \
        f"sahte AI iddiasi bulundu: {yasakli}"
