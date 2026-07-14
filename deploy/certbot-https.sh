#!/usr/bin/env bash
# ============================================================================
# XK100 Borsa — HTTPS sertifika kurulumu (BLOK 22)
#
# UYARI: Bu betik VPS uzerinde root/sudo ile calistirilir; gelistirme
# ortaminda CALISTIRILMAZ.
#
# Kullanim (VPS'te):  sudo bash deploy/certbot-https.sh <domain> <email>
# ============================================================================
set -euo pipefail

DOMAIN="${1:?kullanim: certbot-https.sh <domain> <email>}"
EMAIL="${2:?kullanim: certbot-https.sh <domain> <email>}"

echo "==> certbot ile sertifika uretiliyor: ${DOMAIN}"
certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos -m "${EMAIL}"

echo "==> Yenileme kontrolu"
certbot renew --dry-run

# NOT: certbot systemd timer'i (certbot.timer) sertifikalari otomatik
# yeniler; `systemctl list-timers certbot.timer` ile dogrulanabilir.
echo "HTTPS TAMAM — https://${DOMAIN}"
