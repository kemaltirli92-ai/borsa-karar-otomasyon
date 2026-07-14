"""BLOK 22 - Deployment artefakt dogrulayici + dry-run (deployment.py).

Bu modul VPS'e cikis artefaktlarinin VARLIGINI ve ICERIGINI dogrular; hicbir
seyi CALISTIRMAZ (gercek ag/subprocess YOK). Uc islev:

- validate_artifacts(deploy_dir, repo_root): 5 artefakt dosyasinin (deploy.sh,
  nginx-xk100.conf, certbot-https.sh, logrotate-xk100, DEPLOYMENT.md) varligi
  + icerik kontrolleri (nginx proxy_pass/listen 443/ssl_certificate;
  logrotate rotate N/missingok/copytruncate|create; deploy.sh migrator
  komutu + systemctl enable --now xk100-api.service + timer'lar + curl
  /health smoke satiri). systemd autostart icin BLOK 21 verify_autostart
  YENIDEN kullanilir. Sonuc: DEPLOY_STEPS (TAM 10) ile hizali DeploymentReport
  (mode="dry-run").
- dry_run_migration(repo_root, work_dir): BLOK 7 MigrationRunner ile GECICI
  dizinde gercek bir sqlite DB kurar, migration'lari uygular ve repo
  tablolarini dogrular. Gercek DB'ye ASLA DOKUNMAZ.
- health_wiring_check(repo_root): app/api/health.py import edilebilir mi +
  register(router) deseni BLOK 16 ile uyumlu mu.

stdlib only; deterministik; gercek ag/subprocess YOK.
"""
from __future__ import annotations

import importlib
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

from app.ops.recovery import verify_autostart

# TAM 10 deployment adimi (sira KESIN)
DEPLOY_STEPS = (
    "migration",
    "backend_service",
    "api_service",
    "systemd_service",
    "systemd_timer",
    "reverse_proxy",
    "https",
    "health_endpoint",
    "log_rotation",
    "backup",
)

REPO_TABLES = (
    "stock_universe",
    "stock_universe_memberships",
    "stock_symbol_mappings",
    "stock_scan_runs",
    "stock_scan_results",
    "stock_prices_daily",
    "stock_corporate_actions",
    "stock_trading_restrictions",
    "stock_news_matches",
    "stock_scan_errors",
    "source_health",
    "data_layer_promotions",
)

ARTIFACT_FILES = (
    "deploy.sh",
    "nginx-xk100.conf",
    "certbot-https.sh",
    "logrotate-xk100",
    "DEPLOYMENT.md",
)

TIMER_UNITS = (
    "xk100-index-scoring.timer",
    "xk100-hisse-tarama.timer",
    "xk100-backup.timer",
)


@dataclass(frozen=True)
class DeployStep:
    """Tek deployment adiminin dogrulama sonucu."""

    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class DeploymentReport:
    """Tum adimlarin ozeti (mode her zaman 'dry-run' — calistirma YOK)."""

    ok: bool
    steps: Tuple[DeployStep, ...]
    mode: str = "dry-run"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def validate_artifacts(deploy_dir: str, repo_root: str) -> DeploymentReport:
    """5 artefakt + repo systemd dosyalarinin icerik dogrulamasi (10 adim)."""
    deploy = Path(str(deploy_dir))
    root = Path(str(repo_root))
    texts = {name: _read(deploy / name) for name in ARTIFACT_FILES}
    sh = texts["deploy.sh"]
    nginx = texts["nginx-xk100.conf"]
    certbot = texts["certbot-https.sh"]
    logrotate = texts["logrotate-xk100"]
    doc = texts["DEPLOYMENT.md"]
    steps = []

    # 1) migration: deploy.sh migrator komutu icerir
    has_migrator = ("db.migrator" in sh) or ("schema.sql" in sh)
    steps.append(
        DeployStep(
            "migration",
            has_migrator,
            "deploy.sh migrator komutu iceriyor"
            if has_migrator
            else "deploy.sh icinde migrator/schema uygulama komutu YOK",
        )
    )

    # 2) backend_service: tarama backend servisi kurulumu (pip install + tarama servisi)
    has_backend = ("install -r requirements.txt" in sh) and (
        "xk100-hisse-tarama" in sh
    )
    steps.append(
        DeployStep(
            "backend_service",
            has_backend,
            "pip install + xk100-hisse-tarama kurulumu mevcut"
            if has_backend
            else "backend kurulum adimi eksik",
        )
    )

    # 3) api_service: systemctl enable --now xk100-api.service
    has_api = "systemctl enable --now xk100-api.service" in sh
    steps.append(
        DeployStep(
            "api_service",
            has_api,
            "xk100-api.service enable --now satiri mevcut"
            if has_api
            else "xk100-api.service enable satiri YOK",
        )
    )

    # 4) systemd_service: repo systemd .service dosyalarinda autostart (BLOK 21)
    autostart = verify_autostart(str(root / "systemd"))
    services = [u for u in autostart["units"] if u["file"].endswith(".service")]
    svc_ok = bool(services) and all(u["autostart"] for u in services)
    steps.append(
        DeployStep(
            "systemd_service",
            svc_ok,
            f"{len(services)} .service dosyasinda [Install]/WantedBy dogrulandi"
            if svc_ok
            else "systemd .service autostart eksik",
        )
    )

    # 5) systemd_timer: timer dosyalari + deploy.sh enable satirlari
    timers = [u for u in autostart["units"] if u["file"].endswith(".timer")]
    timers_ok = (
        all(u["autostart"] for u in timers)
        and all(t in sh for t in TIMER_UNITS)
        and len(timers) >= 3
    )
    steps.append(
        DeployStep(
            "systemd_timer",
            timers_ok,
            f"{len(timers)} timer autostart + enable satirlari mevcut"
            if timers_ok
            else "timer autostart/enable eksik",
        )
    )

    # 6) reverse_proxy: nginx proxy_pass + listen 443 + ssl_certificate
    nginx_ok = (
        "proxy_pass" in nginx
        and re.search(r"listen\s+[^;]*443", nginx) is not None
        and "ssl_certificate" in nginx
    )
    steps.append(
        DeployStep(
            "reverse_proxy",
            nginx_ok,
            "nginx proxy_pass + listen 443 + ssl_certificate mevcut"
            if nginx_ok
            else "nginx icerik eksigi (proxy_pass/443/ssl_certificate)",
        )
    )

    # 7) https: certbot betigi certbot --nginx icerir
    https_ok = "certbot" in certbot and "--nginx" in certbot
    steps.append(
        DeployStep(
            "https",
            https_ok,
            "certbot --nginx adimlari mevcut"
            if https_ok
            else "certbot-https.sh icerik eksigi",
        )
    )

    # 8) health_endpoint: app/api/health.py + curl /health smoke satiri
    health_file = (root / "app" / "api" / "health.py").is_file()
    curl_health = re.search(r"curl[^\n]*/health", sh) is not None
    steps.append(
        DeployStep(
            "health_endpoint",
            health_file and curl_health,
            "app/api/health.py + deploy.sh curl /health smoke satiri mevcut"
            if (health_file and curl_health)
            else "health endpoint veya curl smoke satiri eksik",
        )
    )

    # 9) log_rotation: rotate N + missingok + (copytruncate|create)
    log_ok = (
        re.search(r"rotate\s+\d+", logrotate) is not None
        and "missingok" in logrotate
        and ("copytruncate" in logrotate or "create" in logrotate)
    )
    steps.append(
        DeployStep(
            "log_rotation",
            log_ok,
            "logrotate rotate/missingok/copytruncate|create mevcut"
            if log_ok
            else "logrotate icerik eksigi",
        )
    )

    # 10) backup: xk100-backup.timer + DEPLOYMENT.md yedek/geri-alma notu
    backup_ok = (
        "xk100-backup.timer" in sh
        and ("yedek" in doc.lower() or "backup" in doc.lower())
    )
    steps.append(
        DeployStep(
            "backup",
            backup_ok,
            "backup timer + DEPLOYMENT.md yedek notu mevcut"
            if backup_ok
            else "backup adimi eksik",
        )
    )

    return DeploymentReport(
        ok=all(step.ok for step in steps), steps=tuple(steps)
    )


def dry_run_migration(repo_root: str, work_dir: str) -> DeployStep:
    """BLOK 7 MigrationRunner ile GECICI dizinde gercek sqlite DB kurar.

    Migration'lar work_dir'deki TAZE bir veritabanina uygulanir ve repo
    tablolari (REPO_TABLES) sqlite_master uzerinden dogrulanir.
    Gercek DB'ye ASLA DOKUNMAZ.
    """
    from app.services.stock_scanning.db import MigrationRunner

    root = Path(str(repo_root))
    migrations_dir = root / "app" / "services" / "stock_scanning" / "db" / "migrations"
    if not migrations_dir.is_dir():
        return DeployStep(
            "migration", False, f"migration klasoru yok: {migrations_dir}"
        )
    work = Path(str(work_dir))
    work.mkdir(parents=True, exist_ok=True)
    db_path = str(work / "xk100-dryrun.db")
    try:
        MigrationRunner(db_path).apply_all()
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        finally:
            conn.close()
    except Exception as exc:  # migration hatasi -> ok=False (kanitla)
        return DeployStep("migration", False, f"dry-run migration hatasi: {exc}")
    existing = {str(r[0]) for r in rows}
    missing = [t for t in REPO_TABLES if t not in existing]
    if missing:
        return DeployStep(
            "migration", False, f"dry-run DB'de eksik tablolar: {missing}"
        )
    return DeployStep(
        "migration",
        True,
        f"dry-run DB kuruldu: {len(REPO_TABLES)} repo tablosu dogrulandi ({db_path})",
    )


def health_wiring_check(repo_root: str) -> DeployStep:
    """app/api/health.py import edilebilir + register(router) deseni uyumlu."""
    root = Path(str(repo_root))
    if not (root / "app" / "api" / "health.py").is_file():
        return DeployStep(
            "health_endpoint", False, "app/api/health.py dosyasi yok"
        )
    try:
        module = importlib.import_module("app.api.health")
    except Exception as exc:
        return DeployStep(
            "health_endpoint", False, f"health modulu import edilemedi: {exc}"
        )
    handlers = getattr(module, "HealthHandlers", None)
    register = getattr(handlers, "register", None) if handlers else None
    health = getattr(handlers, "health", None) if handlers else None
    if not (handlers and callable(register) and callable(health)):
        return DeployStep(
            "health_endpoint",
            False,
            "HealthHandlers.register/health deseni bulunamadi",
        )
    return DeployStep(
        "health_endpoint",
        True,
        "app.api.health.HealthHandlers register(router) deseni dogrulandi",
    )
