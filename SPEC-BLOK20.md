# SPEC — BLOK 20: Mobil Uygulama Entegrasyonu

Proje: borsa-karar-otomasyon (statik frontend/PWA + VPS API)
Onceki durum: BLOK 19 (index.html + detay paneli + grafikler, 1300/1300 test).
Kurallar: mevcut tasarim SILINMEZ; sahte native uygulama OLUSTURMA (native "HAZIR BEKLIYOR");
musteriye her adimda bildirim GONDERMEZ; eski onbellek canli veri gibi SUNULMAZ.

## 1. Kapsam

### 1a. PWA (Progressive Web App) — telegram-sender/
- `manifest.webmanifest`: name "XK100 Borsa", short_name, start_url=index.html, display=standalone,
  theme_color (#07130b uyumlu), icons (logo-aiborsam2.png 192/512 referansi)
- `sw.js` (service worker):
  * Statik kabuk onbellegi (index.html, logo, favicon) — cache-first
  * API istekleri: network-first, basarisizsa cache (STALE-while-revalidate benzeri)
  * Cache'e yazilan her API yanitina `x-cached-at` damgasi eklenir
  * Eski onbellek sunulurken ACIK etiket: istemci "CEVRIMDISI VERI — SON GUNCELLEME: {tarih}" banti gosterir
    (eski onbellek canli gibi SUNULMAZ)
- index.html'e: manifest linki + sw kaydi + cevrimdisi banti elemani (id="offline-banner", gizli varsayilan)

### 1b. Mobil UI iyilestirmeleri (index.html — mevcut icerik korunur, sadece ekleme)
- viewport meta dogrulamasi (width=device-width, initial-scale=1)
- Dokunmatik hedefler: filtre butonlari, siralama, sayfalama, satir tiklama min 44px (touch-target)
- Mobil tablo: yatay scroll-wrap (tablo tasmaz) + kart listesi (BLOK 18'deki korunur)
- Detay paneli mobil: max-width:100vw, tam ekran alt-sheet benzeri
- Grafik performansi: canvas dpr sinirlamasi (max 2), resize debounce, veri noktasi >500 ise
  basit downsample (gruplama) — ham veri degistirilmez, sadece cizim katmaninda

### 1c. API Sozlesmesi (docs/api-contract.json + docs.html'e not)
- `borsa-karar-otomasyon/docs/api-contract.json`:
  * version: "1.0.0", base: "/api"
  * Zarf sozlesmesi: her cevapta scan_run_id, report_version, last_updated_at, data_cutoff_at, status
  * 13 ekran -> uclar eslemesi: her mobil ekranin kullandigi uclar (BLOK 16'daki 10 musteri ucu)
  * Web ve mobil AYNI zarf degerlerini kullanir (scan_run_id esleme kurali notu)
  * Hata formati: {"error": KOD, "error_id"} (BLOK 16 masking ile uyumlu)
  * Native mobil entegrasyon durumu: "HAZIR_BEKLIYOR" (sozlesme hazir, native proje henuz yok)

### 1d. Dahili Olay Modulu (borsa-karar-otomasyon/app/services/stock_scanning/events.py)
- `ScanEvent` enum (TAM 3): STOCK_SCAN_COMPLETED, STOCK_SCAN_PARTIAL, STOCK_SCAN_FAILED
- `EventBus(clock=None)`: emit(event, run_id, payload) -> olay kaydi (kuyruk/log); MUSTERIYE BILDIRIM GONDERMEZ
- BILDIRIM KILIDI: modulde musteri bildirimi fonksiyonu YOK (push/notification/telegram/send kelimeleri
  fonksiyon adinda yok); musteri bildirim kurali Bolum 9'da olusturulacak (not)
- Olay kaydi: event, run_id, at, payload; get_events(run_id=None)

### 1e. Native durum isareti (index.html)
- Footer'a kucuk not: "Native mobil uygulama: HAZIR BEKLIYOR (API sozlesmesi hazir)" — sahte uygulama butonu/indirme linki YOK

## 2. Testler (tests/blok20/test_mobile_integration.py) — TAM 100 test
1. API sozlesmesi: docs/api-contract.json gecerli JSON, 13 ekran eslemesi, zarf alanlari,
   HAZIR_BEKLIYOR, hata formati (~16)
2. PWA: manifest alanlari, sw.js varligi, cache stratejileri, x-cached-at damgasi (~14)
3. Cevrimdisi: offline-banner elemani, CEVRIMDISI VERI + SON GUNCELLEME metni, eski onbellek
   canli gibi sunulmaz isareti (~14)
4. Responsive/mobil tasma: viewport, touch-target 44px, scroll-wrap, alt-sheet (~14)
5. Dokunmatik: tiklanabilir elemanlar min boyut, sayfalama/filtre dokunmatik dostu (~10)
6. Grafik performansi: dpr siniri, resize debounce, downsample mantigi (~10)
7. Bildirim kurallari: 3 dahili olay, musteri bildirim fonksiyonu YOK, EventBus emit/get (~12)
8. Native isareti + mevcut icerik korunur (BLOK 18/19 ogeleri hala mevcut) (~10)
Toplam = 100; `pytest tests/blok20 -v`

## 3. Dogrulama (orkestrator)
- Canli sayfa: manifest + sw yukleniyor, offline banner mantigi, mobil gorunum
- EventBus fonksiyonel test (emit/get, bildirim fonksiyonu yok)
- api-contract.json gecerli JSON
- Regresyon: 1300/1300 + 100 = 1400/1400

## 4. Kisitlar
- Sadece telegram-sender/manifest.webmanifest + sw.js + index.html ekleme + docs/api-contract.json +
  app/services/stock_scanning/events.py + tests/blok20/
- docs.html'e DOKUNULMAZ; blok6-19'a DOKUNULMAZ
- Sahte native uygulama YOK; musteri bildirimi YOK; eski onbellek canli gibi SUNULMAZ
