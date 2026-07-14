# SPEC — BLOK 9: OHLCV Dogrulama ve Kurumsal Islem Duzeltmesi

Proje: borsa-karar-otomasyon (VPS uzerinde Python servis, stdlib)
Bolum 3: Hisse Taramasi — BLOK 9
Onceki durum: Bolum 1-2 (268) + BLOK 5/6/7/8 (4x100) tamam. Toplam test havuzu: 300 (blok6/7/8).
Konvansiyon: stdlib only, ASCII identifier, Turkce docstring, gercek ag YASAK, saat enjekte.

## 1. Amac
BLOK 8'den gelen gunluk fiyat kayitlarini (raw) analiz modullerine (teknik gostergeler, hisse
skorlama) gondermeden once dogrulayan ve kurumsal islem duzeltmesi uygulayan gecit katmani:
- 13 dogrulama kontrolu
- 5 durum katmani (RAW, CLEAN, VALIDATED, REJECTED, REVIEW_REQUIRED)
- Kurumsal islem duzeltmesi (ham korunur, duzeltilmis ayri, yeni data_version)
- 6 veri yeterlilik durumu
- Gecersiz veri asla analiz modulune gecmez; ham kayit asla silinmez; eski rapor verisi sessizce degismez

## 2. Dosya Yapisi
```
app/services/stock_scanning/
  validation/
    __init__.py
    rules.py          # 13 dogrulama kurali (her kural ayri fonksiyon, kural kodu doner)
    calendar.py       # islem gunu takvimi (hafta sonu + resmi tatil enjeksiyonu)
    ohlcv_validator.py# OhlcvValidator: bar/seri dogrulama, durum atama
    corporate.py      # CorporateActionAdjuster: bedelsiz/bedelli/temettu/bolunme/birlesme duzeltmesi
    sufficiency.py    # veri yeterlilik siniflandirici (6 durum)
    gate.py           # ReleaseGate: analiz modullerine sadece VALIDATED/CLEAN birakir
tests/blok9/
    __init__.py
    test_ohlcv_validation.py  # TAM 100 test
```

## 3. Durum Katmanlari (rules.py / ohlcv_validator.py)
Enum `LayerStatus`: RAW, CLEAN, VALIDATED, REJECTED, REVIEW_REQUIRED
- RAW: BLOK 8'den gelen ham kayit (degistirilmez)
- CLEAN: tum zorunlu kontrolleri gecmis, dogrulama bekleyen (kaynak karsilastirma/kurumsal kontrol tamamsa VALIDATED'a yukselir — BLOK 7 promote akisi ile uyumlu)
- VALIDATED: tum kontroller + kaynak karsilastirma + kurumsal islem kontrolu tamam
- REJECTED: kati ihlal (fiyat<=0, high<low, yanlis para birimi, yanlis sembol-sirket, tekrarlanan tarih) — analize gecmez, kayit korunur
- REVIEW_REQUIRED: supheli ama kati ihlal degil (olagan disi fark aciklanamadi, kaynak uyuşmazligi tolerans disi, islem durdurma belirtisi) — yonetici incelemesi bekler, analize gecmez

## 4. 13 Dogrulama Kurali (rules.py) — her biri ayri fonksiyon + kural kodu
1. `open_positive` — Open > 0 (OPEN_NOT_POSITIVE)
2. `high_positive` — High > 0 (HIGH_NOT_POSITIVE)
3. `low_positive` — Low > 0 (LOW_NOT_POSITIVE)
4. `close_positive` — Close > 0 (CLOSE_NOT_POSITIVE)
5. `volume_non_negative` — Volume >= 0 (NEGATIVE_VOLUME)
6. `high_covers_all` — High >= Open, High >= Low, High >= Close (HIGH_LT_PRICE)
7. `low_below_all` — Low <= Open, Low <= High, Low <= Close (LOW_GT_PRICE)
8. `valid_trading_day` — tarih gecerli islem gunu (hafta sonu + tatil listesi) (NON_TRADING_DAY)
9. `no_duplicate_date` — ayni stock_id+trade_date+source+dz katmaninda tekrar YOK (DUPLICATE_DATE)
10. `currency_ok` — para birimi izinli sette (CURRENCY_MISMATCH)
11. `symbol_owner_ok` — sembol dogru sirkete ait (BLOK 6 SymbolIdentityService ile kontrol; enjekte) (SYMBOL_OWNER_MISMATCH)
12. `outlier_explained` — onceki kapanisa gore fark > esik (config, vars. %20) ise aciklama gerekir: kurumsal islem, islem durdurma sonrasi, kaynak duzeltmesi; aciklama yoksa REVIEW_REQUIRED (UNEXPLAINED_OUTLIER)
13. `corporate_checked` — o gun icin kurumsal islem kaydi kontrol edildi mi (BLOK 7 stock_corporate_actions); aciklanmis islem varsa outlier istisnasi (CORPORATE_NOT_CHECKED)
Ayrica: `source_cross_check` — ana/yedek kaynak kapanislari karsilastirildi mi (tolerans disi -> REVIEW_REQUIRED, SOURCE_DIVERGENCE_REVIEW); VALIDATED icin zorunlu adim.

Kural sonuclari: `RuleResult(code, ok, severity)` severity: FATAL (REJECTED), WARN (REVIEW_REQUIRED), INFO.
Toplu degerlendirme: `evaluate_bar(bar, context) -> (status, [RuleResult])`.

## 5. Islem Gunu Takvimi (calendar.py)
- `TradingCalendar(holidays: set[str] | callable, weekend=(5,6))`
- `is_trading_day(date_str) -> bool`
- Tatiller enjekte edilir (set veya callable); varsayilan sadece hafta sonu
- Gelecek tarih islem gunu sayilmaz (FUTURE_DATE) — saat enjekte

## 6. OhlcvValidator (ohlcv_validator.py)
- `OhlcvValidator(calendar, identity_service=None, corporate_lookup=None, source_compare=None, config=None, clock=None)`
- `validate_bar(bar) -> BarVerdict(status, rule_results, notes)` — tek bar, 13 kural
- `validate_series(stock_id, bars) -> SeriesVerdict(bar_verdicts, status_counts)` — seri bazli (tekrar tarih, outlier zincirleme)
- Kati ihlal -> REJECTED; supheli -> REVIEW_REQUIRED; gecen -> CLEAN
- VALIDATED'a yukseltme: `promote_validated(bar_ids)` — kosullar: CLEAN + kaynak karsilastirma OK + kurumsal kontrol OK (BLOK 7 repo.promote_to_validated zincirine uyumlu)
- Ham kayit HICBIR ZAMAN silinmez; REJECTED bile kayitli kalir

## 7. Kurumsal Islem Duzeltmesi (corporate.py)
- `CorporateAction` dataclass: stock_id, action_type (dividend|bonus|split|capital_increase|rights|reverse_split|other),
  announcement_date, effective_date, ratio (or. "2:1" / 0.50), kap_notice_no, source
- `CorporateActionAdjuster(clock=None)`:
  - `register(action)` — olay kaydi (BLOK 7 stock_corporate_actions formatina uyumlu dict doner); ayni kap_notice_no tekrari reddedilir
  - `adjust_series(stock_id, raw_bars, actions) -> AdjustedSeries(bars=[AdjustedBar], data_version)`
    * Ham fiyatlar KORUNUR (raw_bars degismez)
    * Duzeltilmis fiyatlar AYRI: AdjustedBar(trade_date, raw_close, adj_close, adj_factor, action_refs)
    * Bolunme/birlesme/bedelsiz/bedelli: faktor = oran; temettu: nakit dusum (close - temettu)/close
    * Duzeltme effective_date ONCESI tum barlara kumulatif uygulanir
    * Her duzeltme calismasi YENI data_version uretir (or. "adj-v3"); eski surumler listede kalir
  - `explain_outlier(bar, prev_close, actions)` — outlier aciklanmis mi (kurumsal islemle uyumlu mu)
  - ESKI RAPOR VERISI SESSIZCE DEGISTIRILMEZ: gecmis rapor snapshot'lari (enjekte frozen store) degistirilemez; duzeltme yeni data_version ile gelir, eski version okununca eski degerler doner
- YENI HALKA ARZ: eksik gecmis URETILMEZ — sentetik/sifir bar olusturma fonksiyonu YOK; backfill cagrisi hata verir (NO_SYNTHETIC_HISTORY)

## 8. Veri Yeterlilik (sufficiency.py)
`classify_sufficiency(stock_id, bars, config, listing_date=None) -> str`
- SUFFICIENT_DATA: >= bootstrap_days (260) gecerli bar
- LIMITED_DATA: 60 <= gecerli bar < 260
- NEW_LISTING: listing_date yakin (config new_listing_days, vars. 60 gun) VE bar sayisi az — eksik gecmis uretilmez
- INSUFFICIENT_FOR_TECHNICAL: < 60 gecerli bar (gostergeler isinamaz) ama > 0
- PRICE_DATA_MISSING: 0 gecerli bar
- REVIEW_REQUIRED: seride REVIEW_REQUIRED durumlu bar var ve cozulmemis
Siniflandirma + gerekce + sayimlar doner: SufficiencyVerdict(status, valid_bars, total_bars, reason)

## 9. Gecit (gate.py)
- `ReleaseGate()`:
  - `release_for_analysis(series_verdict, sufficiency) -> ReleaseDecision(allowed, bars, reason)`
  - Sadece VALIDATED (ve izin verilen CLEAN) barlar analiz modullerine gecer
  - REJECTED / REVIEW_REQUIRED barlar CIKARILIR, sayisi raporlanir
  - INSUFFICIENT_FOR_TECHNICAL / PRICE_DATA_MISSING -> allowed=False (analiz modulu cagrilmaz)
  - Gecit karari loglanir (GATE_RELEASED / GATE_BLOCKED)

## 10. Testler (tests/blok9/test_ohlcv_validation.py) — TAM 100 test
Kategoriler:
1. OHLC mantigi (kural 1-7): pozitiflik, high/low kapsama, hacim (~18)
2. Tarih/tatil/tekrar (kural 8-9): hafta sonu, resmi tatil enjeksiyonu, gelecek tarih, cift tarih (~14)
3. Para birimi + sembol-sirket (kural 10-11): yanlis para birimi, yanlis sirket, BLOK 6 entegrasyonu mock (~10)
4. Outlier + kurumsal aciklama + kaynak karsilastirma (kural 12-13 + cross-check) (~16)
5. Kurumsal islem duzeltmesi: bedelsiz/bedelli/temettu/bolunme/birlesme faktorleri, ham korunur, duzeltilmis ayri, kumulatif (~16)
6. data_version + eski rapor korumasi: yeni surum, eski surum okunur, sessiz degisiklik yok (~10)
7. Yeni halka arz: sentetik gecmis uretilmez, NEW_LISTING, yeterlilik durumlari (6 durum) (~10)
8. Gecit: VALIDATED gecer, REJECTED/REVIEW_REQUIRED gecmez, GATE_BLOCKED (~6)
Toplam = 100; `pytest tests/blok9 -v`

## 11. Kisitlar
- Sadece BLOK 9 dosyalari; BLOK 6/7/8'e DOKUNULMAZ (entegrasyon enjeksiyonla)
- stdlib only; deterministik; saat enjekte; ag erisimi yok
- Gecersiz veri analize gecmez kurali testle kanitlanmali
