"""BLOK 23 - KOMUT KATALOGU: TAM 12 pytest testi.

Kapsam (SPEC-BLOK23 dagilimi):
1.    Katalog tablosu var + "anlasilmayan komut YOK" ibaresi (1)
2-5.  7 systemd unit/timer adi gecer + dosyalari repoda var (4)
6-7.  CLI komutlari (run_scan, backup_run) modulleri repoda var (2)
8-9.  health/nginx/certbot/logrotate satirlari (2)
10-12. Her komutun durum etiketi (HAZIR / VPS'TE CALISACAK / GELISTIRME) (3)

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

KATALOG_BASI = "c) KOMUT KATALOGU"
KATALOG_SONU = "d) YAPAY ZEKA ENVANTERI"


@pytest.fixture(scope="module")
def html() -> str:
    assert DOCS_HTML.is_file(), f"docs.html bulunamadi: {DOCS_HTML}"
    return DOCS_HTML.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def katalog(html: str) -> str:
    s = html.find(KATALOG_BASI)
    assert s != -1, "KOMUT KATALOGU bolumu yok"
    e = html.find(KATALOG_SONU, s)
    assert e != -1, "katalog sonu (AI ENVANTERI) bulunamadi"
    return html[s:e]


# --- 1: katalog tablosu + anlasilmayan komut YOK ------------------------------
def test_katalog_tablosu_var(katalog: str) -> None:
    assert "<table>" in katalog and "Komut" in katalog
    assert "anlasilmayan komut YOK" in katalog


# --- 2-5: 7 systemd unit/timer adi + repo dosyalari ---------------------------
def test_systemd_api_service(katalog: str) -> None:
    assert "systemctl enable --now xk100-api.service" in katalog
    assert (_REPO_ROOT / "systemd" / "xk100-api.service").is_file()


def test_systemd_index_scoring(katalog: str) -> None:
    assert "xk100-index-scoring.service" in katalog
    assert "xk100-index-scoring.timer" in katalog
    assert (_REPO_ROOT / "systemd" / "xk100-index-scoring.service").is_file()
    assert (_REPO_ROOT / "systemd" / "xk100-index-scoring.timer").is_file()


def test_systemd_hisse_tarama(katalog: str) -> None:
    assert "xk100-hisse-tarama.service" in katalog
    assert "xk100-hisse-tarama.timer" in katalog
    assert (_REPO_ROOT / "systemd" / "xk100-hisse-tarama.service").is_file()
    assert (_REPO_ROOT / "systemd" / "xk100-hisse-tarama.timer").is_file()


def test_systemd_backup(katalog: str) -> None:
    assert "xk100-backup.service" in katalog
    assert "xk100-backup.timer" in katalog
    assert (_REPO_ROOT / "systemd" / "xk100-backup.service").is_file()
    assert (_REPO_ROOT / "systemd" / "xk100-backup.timer").is_file()


# --- 6-7: CLI komutlari + modulleri repoda var --------------------------------
def test_cli_run_scan(katalog: str) -> None:
    assert "python -m app.services.stock_scanning.orchestration.run_scan" in katalog
    assert (_REPO_ROOT / "app" / "services" / "stock_scanning" / "orchestration" / "run_scan.py").is_file()
    # systemd unit'i de bu komutu icerir (tutarlilik)
    unit = (_REPO_ROOT / "systemd" / "xk100-hisse-tarama.service").read_text(encoding="utf-8")
    assert "app.services.stock_scanning.orchestration.run_scan" in unit


def test_cli_backup_run(katalog: str) -> None:
    assert "python -m app.ops.backup_run" in katalog
    assert (_REPO_ROOT / "app" / "ops" / "backup_run.py").is_file()
    unit = (_REPO_ROOT / "systemd" / "xk100-backup.service").read_text(encoding="utf-8")
    assert "app.ops.backup_run" in unit


# --- 8-9: health/nginx/certbot/logrotate satirlari ----------------------------
def test_health_satiri(katalog: str) -> None:
    assert "curl -fsS https://&lt;domain&gt;/health" in katalog or "/health" in katalog
    assert (_REPO_ROOT / "app" / "api" / "health.py").is_file()


def test_nginx_certbot_logrotate_satirlari(katalog: str) -> None:
    assert "nginx -t" in katalog
    assert "certbot --nginx" in katalog
    assert "logrotate /etc/logrotate.d/xk100" in katalog
    assert "bash deploy/deploy.sh" in katalog
    assert (_REPO_ROOT / "deploy" / "nginx-xk100.conf").is_file()
    assert (_REPO_ROOT / "deploy" / "certbot-https.sh").is_file()
    assert (_REPO_ROOT / "deploy" / "logrotate-xk100").is_file()
    assert (_REPO_ROOT / "deploy" / "deploy.sh").is_file()


# --- 10-12: durum etiketleri ---------------------------------------------------
def test_durum_etiketi_hazir(katalog: str) -> None:
    assert "HAZIR" in katalog


def test_durum_etiketi_vps(katalog: str) -> None:
    assert "VPS'TE CALISACAK" in katalog


def test_durum_etiketi_gelistirme(katalog: str) -> None:
    assert "GELISTIRME ORTAMINDA CALISTIRILMAZ" in katalog
