# SPEC — BLOK 14: Zamanlama, Paralellik ve Durum Makinesi

Proje: borsa-karar-otomasyon (VPS uzerinde Python servis, stdlib)
Bolum 3: Hisse Taramasi — BLOK 14
Onceki durum: Bolum 1-2 (268) + BLOK 5-13 (9x100) tamam. Toplam test havuzu: 800 (blok6-13).
Konvansiyon: stdlib only, ASCII identifier, Turkce docstring, gercek ag YASAK, saat enjekte.

## 1. Amac
Hisse taramasini VPS uzerinde kontrollu gorev akisi olarak kurmak:
- 8 zaman dilimli sabah plani (08:00 -> 09:45)
- Kontrollu paralellik (100 hisse tek senkron dongu YASAK)
- Kaynak bazli rate limit / timeout / retry / backoff
- 11 durumlu hisse durum makinesi
- Idempotent run yonetimi (ayni run_id iki kez baslatilamaz; bilincli yeniden tarama R2)

## 2. Dosya Yapisi
```
app/services/stock_scanning/
  orchestration/
    __init__.py
    schedule.py       # zaman plani (8 dilim) + islem gunu + Europe/Istanbul
    states.py         # ScanState enum (11) + gecis tablosu + StockScanStatus
    limits.py         # SourcePolicy: concurrency_limit, requests_per_minute, timeout, retry_count, backoff
    retry.py          # RetryPolicy: hemen/30sn/90sn + yedek kaynak gecis logu
    pool.py           # ControlledPool: sinirli paralellik (thread tabanli, max_workers sinirli)
    runs.py           # RunRegistry: run_id idempotency, R1/R2 surumleri, tek-run kilit
    orchestrator.py   # ScanOrchestrator: asamali akis + hisse bazli durum takibi + hata izolasyonu
tests/blok14/
    __init__.py
    test_orchestration.py  # TAM 100 test
systemd/ dosyalari: xk100-hisse-tarama.service + .timer (islem gunleri, Europe/Istanbul)
```

## 3. Zaman Plani (schedule.py)
- Europe/Istanbul saat dilimi sabit (zoneinfo; tz disa enjekte edilemez — sabit kural)
- `ScanSchedule` dataclass — 8 dilim (config'ten okunabilir, varsayilanlar SABIT):
  1. 08:00 PRECHECK — islem gunu/servis/kaynak/XK100 evren kontrolu
  2. 08:00-08:45 COLLECTION — fiyat/hacim/KAP/haber/kurumsal islem/tedbir toplama
  3. 08:45-09:00 CLEANING — temizleme/eslestirme/duplikasyon/kaynak dogrulama
  4. 09:00-09:30 RECOVERY — geciken kaynaklar/son KAP-haber kontrolu/veri yeterliligi
  5. 09:30-09:35 PACKAGING — 100 hisse ozeti/standart veri paketleri
  6. 09:35-09:40 ANOMALY_CHECK — eksik veri/anomali kontrolu
  7. 09:40 DATA_CUTOFF — normal veri kesim zamani (sabit nokta)
  8. 09:40-09:45 CRITICAL_RESCAN — kritik olay varsa ilgili hisseyi yeniden tarama
- `current_phase(now) -> Phase` ; `is_trading_day(now) -> bool` (hafta sonu + enjekte tatil)
- islem gunu degilse tarama baslatilamaz (NOT_TRADING_DAY)
- DATA_CUTOFF sabit nokta: 09:40 (degistirilemez sabit kural)

## 4. Durum Makinesi (states.py)
- `ScanState` enum (TAM 11): WAITING, COLLECTING_PRICE, COLLECTING_KAP, COLLECTING_NEWS,
  COLLECTING_ACTIONS, COLLECTING_RESTRICTIONS, VALIDATING, READY, PARTIAL_DATA, FAILED, INACTIVE
- Gecis tablosu (TRANSITIONS): izinli gecisler disindaki gecisler reddedilir (InvalidTransitionError)
  * WAITING -> COLLECTING_* (5 kaynak asamasi)
  * COLLECTING_* -> VALIDATING | PARTIAL_DATA | FAILED
  * VALIDATING -> READY | PARTIAL_DATA | FAILED
  * PARTIAL_DATA -> VALIDATING (recovery sonrasi) | READY
  * FAILED -> WAITING (bilincli yeniden tarama; yeni run surumu)
  * INACTIVE: pasif/arsiv hisse — hicbir toplama asamasina giremez
- `StockScanStatus`: stock_id, state, phase, updated_at, error, attempts, source_used

## 5. Kaynak Politikalari (limits.py)
- `SourcePolicy` dataclass: source_name, concurrency_limit (int), requests_per_minute (int),
  timeout (saniye), retry_count (int, vars. 3), backoff (RetryPolicy)
- Varsayilan politikalar (config'ten): price (5, 60, 10sn, 3), kap (2, 30, 15sn, 3),
  news (4, 40, 10sn, 3), actions (2, 20, 10sn, 3), restrictions (2, 20, 10sn, 3)
- `RateLimiter`: requests_per_minute kovasi (enjekte saatle); limit asiminda bekler/siralar (testte sayim)
- concurrency_limit pool'a uygulanir

## 6. Retry (retry.py)
- `RetryPolicy` sabit plan: 1. deneme HEMEN, 2. deneme +30sn, 3. deneme +90sn (enjekte saat; gercek bekleme YOK —
  planlanan deneme zamanlari dondurulur, testlerde uyku olmaz)
- Deneme sayisi asildiysa: yedek kaynaga gecis (fallback_source) + FALLBACK_SWITCHED logu
  (from_source -> to_source, neden, deneme sayisi)
- Yedek de basarisizsa -> FAILED/PARTIAL_DATA (kaynak kapsamina gore)

## 7. Paralellik (pool.py)
- `ControlledPool(max_workers)`:
  - 100 hisse TEK uzun senkron donguyle CALISTIRILMAZ — gorevler max_workers sinirli havuza dagitilir
  - her gorev try/except ile izole: bir hisse hata verirse diger 99 DEVAM EDER
    (sonuc: per-stock result; hata o hissenin status'una yazilir)
  - gercek thread kullanimi opsiyonel (use_threads=False ise sira ile ama AYNI izolasyonla; test deterministikligi icin)
  - max_workers asla SourcePolicy concurrency_limit'i asmaz (kaynak bazli havuz)
  - tum gorevler bitti mi: `wait_all(timeout)` -> (completed, failed, timed_out)

## 8. Run Yonetimi (runs.py)
- `RunRegistry(clock=None)`:
  - `start_run(run_date, trigger="scheduled") -> run_id` bicimi: {YYYY-MM-DD}-TARAMA-R1
  - AYNI run_id iki kez BASLATILAMAZ (RunAlreadyActiveError) — aktif run varken yeni start reddedilir
  - cift kayit uretme YOK: ayni run_id icin tekrar baslatma girisimi duplicate_attempt++ sayilir, kayit yazilmaz
  - BILINCLI yeniden tarama (admin/manual): onceki run tamamlanmis/basarisis olmali -> yeni run_id R2, R3...
    ({tarih}-TARAMA-R2) + parent_run_id baglantsi
  - run durumlari: ACTIVE, COMPLETED, FAILED, ABORTED
  - `complete_run(run_id)`, `get_run(run_id)`, `latest_run(run_date)`

## 9. Orchestrator (orchestrator.py)
- `ScanOrchestrator(schedule, registry, policies, pool_factory, collectors: dict, logger=None, clock=None)`:
  - `run_morning_flow(universe: list[stock_id]) -> FlowReport`
    * PRECHECK: islem gunu degilse -> NOT_TRADING_DAY + baslamaz
    * her hisse WAITING'den baslar; asama asama COLLECTING_* -> VALIDATING -> READY/PARTIAL_DATA/FAILED
    * collectors dict: {"price": fn, "kap": fn, "news": fn, "actions": fn, "restrictions": fn} enjekte
    * bir hisse bir asamada hata -> retry politikasi; asilirsa o hisse FAILED/PARTIAL_DATA,
      DIGER HISSELER DEVAM
    * kaynak toplayici yoksa o asama PARTIAL_DATA nedenine yazilir (collector_missing)
    * DATA_CUTOFF sonrasi kritik olay listesi varsa sadece ilgili hisseler icin CRITICAL_RESCAN dalgasi
  - `critical_rescan(stock_ids, reason) -> FlowReport` — bilincli yeniden tarama (R-surumu run ile)
  - FlowReport: run_id, per-stock durum ozeti, counts (READY/PARTIAL/FAILED/INACTIVE), errors, fallback_loglari, started_at, completed_at

## 10. Systemd (systemd/xk100-hisse-tarama.service + .timer)
- service: Type=oneshot, ExecStart run_scan, TZ=Europe/Istanbul
- timer: OnCalendar=Mon..Fri 08:00:00 Europe/Istanbul, Persistent=true
- (Blok 14 dosya agacinda systemd/ altina yazilir)

## 11. Testler (tests/blok14/test_orchestration.py) — TAM 100 test
Kategoriler:
1. Zamanlama: 8 dilim siralama/sinirlar, DATA_CUTOFF 09:40 sabit, Europe/Istanbul, islem gunu/tatil (~16)
2. Paralellik: max_workers sinirli, tek senkron dongu degil, concurrency_limit asilmaz, wait_all (~14)
3. Hata toleransi: 1 hisse patlar 99 devam, kaynak eksik -> PARTIAL, tumu patlarsa FAILED sayilari (~14)
4. Cift run_id: ayni run_id ikinci baslatma reddi, duplicate sayaci, kayit yazilmaz (~12)
5. R2 olusturma: bilincli yeniden tarama R2/R3, parent_run_id, tamamlanmamis run'a R2 yok (~12)
6. Durum gecisleri: 11 durum, izinli/izinsiz gecisler, INACTIVE kurallari (~16)
7. Retry/backoff: hemen/30/90 plani, yedek kaynak gecis logu, deneme asimi (~10)
8. Kaynak politikasi: rpm kovasi, timeout, varsayilan politikalar (~6)
Toplam = 100; `pytest tests/blok14 -v`

## 12. Kisitlar
- Sadece BLOK 14 dosyalari; BLOK 6-13'e DOKUNULMAZ (collector'lar enjekte)
- stdlib only (threading opsiyonel, zoneinfo); deterministik; saat enjekte; gercek ag YOK; gercek bekleme YOK
