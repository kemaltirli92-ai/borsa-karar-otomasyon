# SPEC — BLOK 8: Fiyat Verisi Toplama Modulu

Proje: borsa-karar-otomasyon (VPS uzerinde Python servis, stdlib)
Bolum 3: Hisse Taramasi — BLOK 8
Onceki durum: Bolum 1-2 (268) + BLOK 5 (100) + BLOK 6 (100) + BLOK 7 (100) tamam.
Konvansiyon: stdlib only, ASCII identifier, Turkce docstring, gercek ag YASAK (tum kaynaklar enjekte).

## 1. Amac
Fiyat/hacim verisini tek kaynaga bagli kalmadan toplayan modul:
- Coklu kaynak mimarisi: ana (resmi/lisansli), yedek (yfinance), dogrulama (Google Finance)
- Kaynak onceligi yonetici ayarindan degistirilebilir (config)
- Ilk kurulum 260+ gun; her sabah artimli guncelleme + son 10 gun tekrar kontrol
- Kopya olusturma yok; kaynak gecisi loglanir; toleransli kaynaklar arasi dogrulama

## 2. Dosya Yapisi
```
app/services/stock_scanning/
  price_collection/
    __init__.py
    sources.py       # PriceSource arayuzu + resmi/lisansli stub + yfinance/Google adapterlari (enjekte fetcher)
    config.py        # fiyat kaynak konfigi: kaynak onceligi, toleranslar (yonetici ayari)
    collector.py     # PriceCollector: bootstrap(260+ gun), incremental_update, recheck_last_10
    storage.py       # BLOK 7 stock_prices_daily tablosuna yazim (repo uzerinden), kopya engeli
    validator.py     # kaynaklar arasi kapanis farki tolerans kontrolu, para birimi, eski veri
tests/blok8/
    __init__.py
    test_price_collection.py  # TAM 100 test
```

## 3. Veri Modeli
PriceBar dataclass (sources.py):
- stock_id, trade_date (ISO), open, high, low, close, adjusted_close (None olabilir), volume (int),
  currency (ISO kodu, or. TRY), source (kaynak adi), source_timestamp (kaynagin damgasi),
  collected_timestamp (toplama damgasi, saat enjekte)
- Zorunlu alan dogrulamasi: open/high/low/close pozitif float, volume >= 0, high >= low,
  high >= max(open,close) ise esneklik yok (bozuk bar REDDEDILIR), currency 3 harf ISO

## 4. Kaynak Arayuzu (sources.py)
- `PriceSource` sinifi: name, fetch_history(stock_id, days) -> list[PriceBar], fetch_latest(stock_id) -> PriceBar|None,
  fetch_date(stock_id, date) -> PriceBar|None
- fetcher enjekte edilir (callable); fetcher None ise kaynak "baglanamadi" davranisi: SourceUnavailableError
- `LicensedSource` (ana kaynak stub — resmi/lisansli API ileride baglanacak, fetcher zorunlu)
- `YFinanceSource` (yedek stub — gercek yfinance paketi YOK; fetcher enjekte edilir)
- `GoogleFinanceSource` (dogrulama stub)
- Kaynak yanitlari normalize edilir: ham kayit PriceBar'a cevrilirken eksik/bozuk alanlar elenir (loglanir)

## 5. Config (config.py)
- `PriceCollectionConfig` dataclass:
  - source_priority: list[str] — or. ["licensed","yfinance"] — YONETICI AYARINDAN degistirilebilir (set_priority)
  - validation_source: str — or. "google"
  - close_tolerance_pct: float — kaynaklar arasi kapanis farki toleransi (or. 0.5 yuzde)
  - bootstrap_days: int — min 260
  - recheck_days: int — 10
  - allowed_currencies: set — {"TRY"} varsayilan
  - stale_days_limit: int — eski veri esigi (kaynaktan gelen son bar bu sinirdan eskiyse STALE)
- Config kaydi JSON'a/yonetici paneline yazilabilir: to_dict/from_dict; gecersiz oncelik (bilinmeyen kaynak adi) reddedilir

## 6. Collector (collector.py)
- `PriceCollector(sources: dict[str, PriceSource], config, storage, logger=None, clock=None)`
- `bootstrap(stock_id)`:
  - Oncelik sirasina gore kaynaklari dene; ilk basarili kaynaktan 260+ gun cek
  - Hepsi bos/basarisiz ise: hicbir sey yazma, sonuc = PRICE_DATA_MISSING + NULL paket (logla)
  - Bir kaynak basarisiz olunca digerine gec ve gecisi LOGLA (SOURCE_SWITCHED: eski->yeni, neden)
- `incremental_update(stock_id)`:
  - DB'deki son trade_date'i oku; ondan sonraki gunleri cek ve yaz
  - Son 10 gunu TEKRAR cek ve karsilastir: degisen bar varsa guncelle (yeni data_version), aynisi ise DOKUNMA
  - Ayni veri tekrar gelirse KOPYA OLUSTURMA (unique anahtar: stock_id+trade_date+source+data_version)
- `validate_against(stock_id, date, primary_bar)`:
  - Dogrulama kaynagi (google) ile kapanis karsilastir
  - fark_yuzde > close_tolerance_pct ise -> PRICE_SOURCE_DIVERGENCE uyarisi (logla, isaretle); tolerans icinde -> OK
  - Dogrulama kaynagi ulasilamiyorsa dogrulama atlanir (VALIDATION_SOURCE_UNAVAILABLE, isaret)
- Eski veri: bootstrap/update sirasinda en yeni bar stale_days_limit'ten eskiyse -> STALE_PRICE_DATA uyarisi
- Para birimi: bar currency allowed_currencies disinda ise bar REDDEDILIR + WRONG_CURRENCY (or. USD gelen THYAO)
- Sonuc nesnesi: CollectionResult(stock_id, status, bars_written, source_used, warnings, errors)
  status: OK | PRICE_DATA_MISSING | PARTIAL | FAILED

## 7. Storage (storage.py)
- BLOK 7 repo ile uyumlu: `PriceStorage(conn, repo=None, clock=None)`
  - write_bars(stock_id, bars, data_layer="raw") — INSERT OR IGNORE benzeri: unique cakismada kopya YAZILMAZ, skipped sayisi doner
  - update_bar(stock_id, trade_date, source, new_bar, new_version) — son 10 gun recheck icin surum artirimi
  - get_last_trade_date(stock_id), get_bars(stock_id, days)
  - DB yoksa (conn=None) bellek ici depolama (test icin)
- Yazilan her bar data_layer="raw" baslar (BLOK 7 katmanlari ile uyumlu)

## 8. Testler (tests/blok8/test_price_collection.py) — TAM 100 test, pytest
Hepsi mock fetcher ile; gercek ag YOK; bos gecici DB veya bellek ici storage.
Kategoriler:
1. Coklu kaynak + kaynak gecisi: ana basarisiz -> yedek; gecis logu; yedek de basarisiz -> sonraki (~16)
2. Iki kaynak da bos: PRICE_DATA_MISSING + NULL, hic yazim yok (~10)
3. Bootstrap 260+ gun: dogru sayida bar, tarih sirasi, eksik gun eleme (~12)
4. Artimli guncelleme: son tarihten sonrasini cek, zaten var olanlara dokunma (~14)
5. Son 10 gun tekrar kontrol: degisen bar guncellenir, ayni bar atlanir (~12)
6. Kopya engeli: ayni veri tekrar gelirse unique anahtarla yazilmaz (~12)
7. Kaynaklar arasi fark: tolerans icinde/disinda, VALIDATION_SOURCE_UNAVAILABLE (~12)
8. Eski veri + yanlis para birimi + bozuk bar reddi + config/yonetici onceligi (~12)
Toplam = 100; `pytest tests/blok8 -v`

## 9. Kisitlar
- Sadece BLOK 8 dosyalari; BLOK 6/7 ve diger modullere DOKUNULMAZ (storage BLOK 7 tablosunu kullanir ama sema degistirmez)
- stdlib only; yfinance paketi KURULMAZ — kaynaklar fetcher injection ile test edilir
- Deterministik; saat enjekte; ag erisimi yok
