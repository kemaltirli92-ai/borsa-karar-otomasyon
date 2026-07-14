#!/usr/bin/env bash
# ============================================================================
# XK100 Borsa Karar Otomasyonu — VPS deployment betigi (BLOK 22)
#
# UYARI: Bu betik VPS uzerinde root/sudo ile calistirilir; gelistirme
# ortaminda CALISTIRILMAZ. Testler yalnizca icerik dogrulamasi yapar.
#
# Kullanim (VPS'te):  sudo bash deploy/deploy.sh <domain>
# ============================================================================
set -euo pipefail

DOMAIN="${1:-example.com}"
APP_ROOT="/opt/xk100"
SITE_ROOT="/var/www/xk100"
LOG_DIR="/var/log/xk100"
VENV="${APP_ROOT}/.venv"

echo "==> [1/8] Bagimliliklar kuruluyor"
cd "${APP_ROOT}"
"${VENV}/bin/pip" install -r requirements.txt

echo "==> [2/8] Veritabani migration'lari uygulaniyor (BLOK 7 migrator)"
"${VENV}/bin/python" -m app.services.stock_scanning.db.migrator
# Alternatif (ilk kurulum): "${VENV}/bin/python" -c "import sqlite3; sqlite3.connect('db/xk100.db').executescript(open('db/schema.sql').read())"

echo "==> [3/8] systemd unit dosyalari kopyalaniyor"
cp systemd/xk100-api.service             /etc/systemd/system/
cp systemd/xk100-hisse-tarama.service    /etc/systemd/system/
cp systemd/xk100-hisse-tarama.timer      /etc/systemd/system/
cp systemd/xk100-index-scoring.service   /etc/systemd/system/
cp systemd/xk100-index-scoring.timer     /etc/systemd/system/
cp systemd/xk100-backup.service          /etc/systemd/system/
cp systemd/xk100-backup.timer            /etc/systemd/system/

echo "==> [4/8] systemd yeniden yukleme + servisler/timer'lar etkin"
systemctl daemon-reload
systemctl enable --now xk100-api.service
systemctl enable --now xk100-index-scoring.timer
systemctl enable --now xk100-hisse-tarama.timer
systemctl enable --now xk100-backup.timer

echo "==> [5/8] Statik site dosyalari guncelleniyor"
mkdir -p "${SITE_ROOT}" "${LOG_DIR}"
cp index.html docs.html favicon-xk100.png logo-aiborsam2.png "${SITE_ROOT}/"

echo "==> [6/8] logrotate yapilandirmasi"
cp deploy/logrotate-xk100 /etc/logrotate.d/xk100

echo "==> [7/8] nginx reverse proxy (HTTP->HTTPS yonlendirme + /api + /health)"
cp deploy/nginx-xk100.conf /etc/nginx/sites-available/xk100.conf
ln -sf /etc/nginx/sites-available/xk100.conf /etc/nginx/sites-enabled/xk100.conf
sed -i "s/<domain>/${DOMAIN}/g" /etc/nginx/sites-available/xk100.conf
nginx -t
systemctl reload nginx

echo "==> [8/8] Smoke: health endpoint kontrolu"
curl -fsS "https://${DOMAIN}/health" | grep '"status": *"ok"' > /dev/null
echo "health smoke OK"

echo "==> Yedek zamanlayicisi dogrulaniyor"
systemctl list-timers xk100-backup.timer --no-pager
echo "DEPLOY TAMAM — https://${DOMAIN}"
