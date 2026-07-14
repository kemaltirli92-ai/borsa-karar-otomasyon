"""BLOK 22 - test_deployment: deployment artefakt kabul testleri (10 test).

Kapsam: 5 artefakt dosyasi var; nginx icerik (proxy_pass+443+ssl);
logrotate icerik; deploy.sh adimlari (migrate+enable+health satiri);
dry_run_migration gecici DB'de OK; DEPLOY_STEPS==10; systemd autostart
(BLOK 21 ile tutarli); DeploymentReport.ok; certbot betigi icerik;
systemd unit'lerinde [Install]/WantedBy.
Gercek ag/subprocess YOK — betikler CALISTIRILMAZ, dogrulanir.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.acceptance.deployment import (
    ARTIFACT_FILES,
    DEPLOY_STEPS,
    dry_run_migration,
    health_wiring_check,
    validate_artifacts,
)
from app.ops.recovery import verify_autostart

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEPLOY_DIR = _REPO_ROOT / "deploy"


def _read(name):
    return (_DEPLOY_DIR / name).read_text(encoding="utf-8")


# 1) 5 artefakt dosyasi var -------------------------------------------------------
def test_five_artifact_files_exist():
    for name in ARTIFACT_FILES:
        assert (_DEPLOY_DIR / name).is_file(), f"artefakt yok: {name}"
    assert len(ARTIFACT_FILES) == 5


# 2) nginx icerik -------------------------------------------------------------------
def test_nginx_content_proxy_443_ssl():
    conf = _read("nginx-xk100.conf")
    assert "proxy_pass" in conf
    assert re.search(r"listen\s+[^;]*443", conf) is not None
    assert "ssl_certificate" in conf
    assert "/health" in conf and "/api/" in conf


# 3) logrotate icerik ------------------------------------------------------------------
def test_logrotate_content_rotation_rules():
    conf = _read("logrotate-xk100")
    assert re.search(r"rotate\s+\d+", conf) is not None
    assert "missingok" in conf
    assert "copytruncate" in conf or "create" in conf


# 4) deploy.sh adimlari ------------------------------------------------------------------
def test_deploy_sh_migrate_enable_health_lines():
    sh = _read("deploy.sh")
    assert "set -euo pipefail" in sh
    assert "db.migrator" in sh  # migration komutu
    assert "systemctl enable --now xk100-api.service" in sh
    assert "xk100-hisse-tarama.timer" in sh
    assert "xk100-backup.timer" in sh
    assert re.search(r"curl[^\n]*/health", sh) is not None  # smoke satiri
    assert "CALISTIRILMAZ" in sh  # gelistirme ortami uyarisi


# 5) dry_run_migration gecici DB'de OK ------------------------------------------------------
def test_dry_run_migration_temp_db_ok(tmp_path):
    step = dry_run_migration(str(_REPO_ROOT), str(tmp_path))
    assert step.name == "migration"
    assert step.ok is True, step.detail
    # gercek DB'ye DOKUNULMAZ: gecici dizinde kaldi
    assert (tmp_path / "xk100-dryrun.db").is_file()


# 6) DEPLOY_STEPS == 10 ----------------------------------------------------------------------
def test_deploy_steps_exactly_10():
    assert len(DEPLOY_STEPS) == 10
    assert DEPLOY_STEPS[0] == "migration"
    assert DEPLOY_STEPS[-1] == "backup"


# 7) systemd autostart (BLOK 21 ile tutarli) ------------------------------------------------------
def test_systemd_autostart_consistent_with_blok21():
    report = verify_autostart(str(_REPO_ROOT / "systemd"))
    assert report["all_ok"] is True
    files = {u["file"] for u in report["units"]}
    assert "xk100-api.service" in files
    assert "xk100-hisse-tarama.timer" in files
    assert "xk100-backup.timer" in files
    # health wiring: app/api/health.py register deseni
    assert health_wiring_check(str(_REPO_ROOT)).ok is True


# 8) DeploymentReport.ok ----------------------------------------------------------------------
def test_deployment_report_ok_all_steps():
    report = validate_artifacts(str(_DEPLOY_DIR), str(_REPO_ROOT))
    assert report.mode == "dry-run"
    assert len(report.steps) == 10
    assert [s.name for s in report.steps] == list(DEPLOY_STEPS)
    assert report.ok is True, [s.detail for s in report.steps if not s.ok]


# 9) certbot betigi icerik -------------------------------------------------------------------
def test_certbot_script_https_content():
    sh = _read("certbot-https.sh")
    assert "set -euo pipefail" in sh
    assert "certbot --nginx" in sh            # sertifika uretim komutu
    assert "certbot renew --dry-run" in sh    # yenileme kontrolu
    assert "CALISTIRILMAZ" in sh              # gelistirme ortami uyarisi


# 10) systemd unit'lerinde [Install] / WantedBy ------------------------------------------------
def test_systemd_units_have_install_section():
    units = sorted((_REPO_ROOT / "systemd").glob("xk100-*.*"))
    names = {u.name for u in units}
    assert "xk100-api.service" in names
    assert "xk100-backup.timer" in names
    checked = 0
    for unit in units:
        if unit.suffix not in (".service", ".timer"):
            continue  # xk100.cron unit degildir
        text = unit.read_text(encoding="utf-8")
        assert "[Install]" in text, unit.name
        assert "WantedBy=" in text, unit.name
        checked += 1
    assert checked == 7  # 4 service + 3 timer
