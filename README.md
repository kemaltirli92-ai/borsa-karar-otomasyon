# XK100 Borsa Karar Otomasyonu

BIST Katilim 100 Endeksi (XK100) tarama ve karar destek sistemi.
VPS uzerinde Python servis olarak calisir; web sitesi ve mobil uygulama ortak API uzerinden beslenir.

## Mimari

- **Dil/Stack:** Python 3.12 (uygulama kodu stdlib only — dis bagimlilik yok), SQLite
- **Zamanlama:** systemd timer (Pzt-Cuma 08:00 TSi) + cron guvenlik agi (09:30)
- **API:** http.server tabanli (port 8099), yonetici uclari X-Admin-Token ile korunur

## Akis (her islem gunu)

1. Veri Toplama (08:00-08:45)
2. Endeks Skorlama (7 kategori, 0-100)
3. Hisse Taramasi (aktif XK100, 100 sirket)
4. Hisse Skorlama (6 kategori)
5. Teknik Gosterge Analizi
6. Seviye Haritasi (S1-S3 / R1-R3)
7. Haber Analizi
8. Portfoy Dagilimi
9. Rapor Yayini (09:45, web + mobil)

## Tamamlanan Moduller (test dogrulamali)

| Blok | Modul | Test |
|------|-------|------|
| Bolum 1-2 | Endeks Skorlama (7 kategori, engine, API, panel, backtest) | 268/268 |
| BLOK 5 | XK100 Evren Modulu (kaynak dogrulama, 100 kontrol) | 100/100 |
| BLOK 6 | Sirket Kimligi ve Sembol Eslestirme (merkezi stock_id, 5 platform) | 100/100 |
| BLOK 7 | Veri Tabani ve Migration (11 tablo, geri alma, yedek+kayıp kontrolu) | 100/100 |
| BLOK 8 | Fiyat Verisi Toplama (coklu kaynak, artimli guncelleme, tolerans) | 100/100 |
| BLOK 9 | OHLCV Dogrulama ve Kurumsal Islem Duzeltmesi (5 katman, 6 yeterlilik) | 100/100 |
| BLOK 10 | Hacim ve TL Islem Hacmi (tahmin/gercek ayrimi, sinyal kilidi) | 100/100 |
| BLOK 11 | KAP Bildirim Toplama (merkezi akis, revizyon zinciri, favori kilidi) | 100/100 |

**Toplam: 600/600 modul testi gecti** (`python -m pytest tests -q`)

## Dizin Yapisi

```
app/
  models/stock_identity.py                 # BLOK 6 veri modelleri
  services/stock_scanning/
    symbol_identity.py                     # BLOK 6 ana servis
    kap_verifier.py, identity_adapter.py   # BLOK 6 KAP dogrulama + evren adaptoru
    db/                                    # BLOK 7 (migrations/, migrator, backup, repo)
    price_collection/                      # BLOK 8 (sources, config, collector, storage, validator)
    validation/                            # BLOK 9 (rules, calendar, ohlcv_validator, corporate, sufficiency, gate)
    volume/                                # BLOK 10 (models, turnover, ratio, classifier, analyzer)
    kap_collection/                        # BLOK 11 (models, feed, matcher, collector, storage, readiness)
  admin/symbol_admin.py                    # BLOK 6 yonetici paneli servisi
tests/blok6-11/                            # blok bazli test paketleri (blok5: test_evren.py ayri oturum)
db/schema.sql                              # konsolide sema (migration 0001+0002)
systemd/                                   # servis + timer + cron dosyalari
docs.html                                  # XK100 Sistem Semasi (GIZLI - sadece yonetici)
index.html                                 # musteri rapor sayfasi
```

## Kurulum (VPS)

```bash
git clone <repo> /opt/borsa-karar-otomasyon
cd /opt/borsa-karar-otomasyon
cp .env.example .env   # degerleri doldurun (.env repoya EKLENMEZ)
pip install -r requirements.txt   # yalniz test icin
python -m pytest tests -q         # 600/600 beklenir
sudo cp systemd/xk100-*.service systemd/xk100-*.timer /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now xk100-index-scoring.timer xk100-api.service
```

## Kurallar

- Ham veri asla silinmez; gecersiz veri analiz modullerine gecmez
- Tahmin hicbir yerde gercek deger diye gosterilmez
- Anormal tek basina sinyal uretmez; puan hesaplamalari kendi modullerinde kalir (kapsam kilidi)
- Eski rapor verisi sessizce degistirilmez; duzeltmeler yeni data_version ile gelir
