# XK100 Borsa — VPS Deployment Kontrol Listesi (BLOK 22)

Bu dokuman 10 adimlik kesin kurulum sirasini ve her adimin dogrulama
komutunu icerir. Tum komutlar VPS uzerinde `sudo` ile calistirilir;
gelistirme ortaminda CALISTIRILMAZ.

## On kosullar
- Ubuntu 22.04+ VPS, Python 3.12, nginx, certbot
- Repo `/opt/xk100` altinda, sanal ortam `/opt/xk100/.venv`
- Alan adi DNS kaydi VPS IP'sine isaret ediyor

## 10 adim
| # | Adim | Komut | Dogrulama |
|---|------|-------|-----------|
| 1 | migration | `python -m app.services.stock_scanning.db.migrator` | `sqlite3 db/xk100.db ".tables"` — 12 repo tablosu |
| 2 | backend_service | `pip install -r requirements.txt` + tarama servisi dosyalari | `systemctl cat xk100-hisse-tarama.service` |
| 3 | api_service | `systemctl enable --now xk100-api.service` | `systemctl is-active xk100-api.service` -> active |
| 4 | systemd_service | unit dosyalari `/etc/systemd/system`'e kopyalanir | `systemctl daemon-reload && systemctl is-enabled xk100-api.service` |
| 5 | systemd_timer | `systemctl enable --now xk100-index-scoring.timer xk100-hisse-tarama.timer xk100-backup.timer` | `systemctl list-timers 'xk100-*'` — 3 timer |
| 6 | reverse_proxy | `cp deploy/nginx-xk100.conf /etc/nginx/sites-available/xk100.conf` | `nginx -t` -> syntax ok |
| 7 | https | `bash deploy/certbot-https.sh <domain> <email>` | `curl -fsS https://<domain>/health` |
| 8 | health_endpoint | deploy.sh icindeki `curl -fsS https://<domain>/health` smoke satiri | govdede `"status": "ok"` |
| 9 | log_rotation | `cp deploy/logrotate-xk100 /etc/logrotate.d/xk100` | `logrotate -d /etc/logrotate.d/xk100` |
| 10 | backup | `systemctl enable --now xk100-backup.timer` | `systemctl list-timers xk100-backup.timer`; yedek dosyasi `backups/` altinda gunluk olusur |

## Smoke (deployment sonrasi)
```bash
python -m app.acceptance.smoke  # veya test disi istemciyle:
curl -fsS https://<domain>/health
curl -fsS https://<domain>/api/xk100/stocks?page=1\&page_size=25 | head
```

## Geri alma (rollback) notu
1. `systemctl stop xk100-api.service xk100-hisse-tarama.timer xk100-index-scoring.timer`
2. Bir onceki yedekten geri yukle: `python -m app.ops.restore --from backups/<gun>/` (BLOK 21 restore)
3. nginx eski conf'u geri kopyala + `nginx -t && systemctl reload nginx`
4. `curl -fsS https://<domain>/health` ile servisin ayakta oldugunu dogrula.
Yedekler `xk100-backup.timer` ile gunluk alinir; geri alma her zaman once
yedegin dogrulanmasini gerektirir (BLOK 21 backup dogrulama adimi).
