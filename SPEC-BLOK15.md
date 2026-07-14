# SPEC — BLOK 15: Veri Guveni ve Hazirlik Durumu

Proje: borsa-karar-otomasyon (VPS uzerinde Python servis, stdlib)
Bolum 3: Hisse Taramasi — BLOK 15
Onceki durum: Bolum 1-2 (268) + BLOK 5-14 (10x100) tamam. Toplam test havuzu: 900 (blok6-14).
Konvansiyon: stdlib only, ASCII identifier, Turkce docstring, gercek ag YASAK, saat enjekte.

## 1. Amac
Her hisse icin 0-100 Tarama Veri Guveni (data_confidence) ve hazirlik durumlarini hesaplayan modul.
BU DEGER HISSE SKORU DEGILDIR, yukselme ihtimali DEGILDIR, alim tavsiyesi DEGILDIR — verinin
tamlik ve dogrulama seviyesidir (kapsam kilidi).

## 2. Dosya Yapisi
```
app/services/stock_scanning/
  confidence/
    __init__.py
    models.py         # ComponentInput, ConfidenceResult, ReadyFlags, ConfidenceConfig
    components.py     # 12 bilesen degerlendirici (her biri ayri fonksiyon)
    readiness.py      # 11 tam-hazirlik sarti + ReadinessVerdict
    calculator.py     # ConfidenceCalculator: agirlikli toplam + cikti paketi
    display.py        # ana sayfa aciklama metni (sabit kural)
tests/blok15/
    __init__.py
    test_confidence.py  # TAM 100 test
```

## 3. Veri Modeli (models.py)
- `ComponentInput` dataclass: her bilesen icin status (OK|MISSING|STALE|UNVERIFIED|FAILED|NOT_APPLICABLE)
  + detail (str) — bilesen degerlendiricilerinin ciktisi
- `ConfidenceResult` dataclass: stock_id, data_confidence (0-100 int), technical_ready (bool),
  scoring_ready (bool), favorite_eligible (bool), missing_fields (list[str]),
  component_scores (dict), warnings (list[str]), disclaimer (str)
- `ReadyFlags`: technical_ready, scoring_ready, favorite_eligible
- KAPSAM KILIDI: modulde hisse_skoru/stock_score/signal/puan/buy_sell alani veya fonksiyonu YOK

## 4. 12 Bilesen (components.py) — her biri ComponentInput dondurur
1. `price_availability` — gecerli son fiyat var mi (BLOK 8 storage; enjekte input)
2. `price_source_validation` — ana/yedek kaynak kapanisi tolerans icinde mi (BLOK 8 validator sonucu)
3. `volume_availability` — gecerli hacim var mi (BLOK 10; eksik hacim MISSING, gercek sifir OK degil)
4. `history_sufficiency` — veri yeterlilik etiketi (BLOK 9 sufficiency: SUFFICIENT/LIMITED/NEW_LISTING/...)
5. `kap_check` — KAP kontrol tamam mi (BLOK 11: kritik bildirim body durumu)
6. `news_check` — haber kontrol tamam mi (BLOK 12: eslestirme/dedupe tamamlandi mi)
7. `corporate_check` — kurumsal islem kontrol tamam mi (BLOK 13)
8. `restriction_check` — tedbir kontrol tamam mi + aktif TRADING_HALT bayragi (BLOK 13)
9. `symbol_verification` — stock_id dogrulanmis mi (BLOK 6: VERIFIED; SYMBOL_VERIFICATION_PENDING ise UNVERIFIED)
10. `data_freshness` — son veri taze mi (enjekte saat; stale_days_limit; eski ise STALE)
11. `anomaly_count` — anomali sayisi (0: OK, 1-2: INFO, 3+: FAILED)
12. `critical_fields` — kritik eksik alan var mi (varsa FAILED + alan adlari)

## 5. Agirliklar (models.py ConfidenceConfig)
- Varsayilan agirliklar (toplam = 100):
  price_availability 15, price_source_validation 10, volume_availability 10,
  history_sufficiency 8, kap_check 8, news_check 6, corporate_check 7, restriction_check 7,
  symbol_verification 8, data_freshness 8, anomaly_count 8, critical_fields 5
- Yonetici paneli: `set_weights(weights: dict)` — bilinmeyen bilesen adi reddedilir;
  toplam 100'e normalize edilir VEYA toplam dogrulamasi (config validate_weights: toplam!=100 ise hata
  ya da bayrak; ikisi desteklenir, testle)
- Agirlik degisikligi audit notu birakir (config_version artar)

## 6. Skor Hesaplama (calculator.py)
- Bilesen katsayilari: OK=1.0, NOT_APPLICABLE=1.0 (agirlik dagitim disi — kalan agirliklar orantili
  yeniden dagitilir), UNVERIFIED=0.5, STALE=0.5, MISSING=0.0, FAILED=0.0
- EKSIK ALAN SIFIR VERI GIBI KABUL EDILMEZ: MISSING bilesen 0 katsayi ile girer, ama
  var gibi sayilmaz; missing_fields listesine yazilir ve confidence otomatik 100 OLAMAZ
- data_confidence = round(sum(agirlik_i * katsayi_i) / aktif_agirlik_toplami * 100/100 olcek)
  — pratikte 0-100 int, yeniden dagitim sonrasi
- Kritik eksik varsa: confidence ustu siniri (config, vars. max 60) + KRITIK VERI EKSIK uyarisi
  + favorite_eligible=False (kati)
- STALE bilesen(ler) varsa: ESKI VERI uyarisi + favorite_eligible=False

## 7. Hazirlik Sartlari (readiness.py)
Tam hazirlik (technical_ready=True) icin TAM 11 sart:
1. stock_id VERIFIED 2. aktif XK100 uyeligi 3. gecerli son fiyat 4. gecerli hacim
5. son islem tarihi mevcut 6. KAP kontrol OK 7. haber kontrol OK 8. kurumsal islem kontrol OK
9. tedbir kontrol OK 10. fiyat kaynak dogrulamasi OK 11. veri yeterlilik etiketi mevcut
- ReadinessVerdict: technical_ready, failing_conditions (list), notes
- scoring_ready = technical_ready AND aktif TRADING_HALT YOK (BLOK 13) AND critical eksik yok
- favorite_eligible = scoring_ready AND STALE yok AND kritik eksik yok
  (nihai favori SECIMI Bolum 4'te — bu blok sadece uygunluk etiketi uretir)

## 8. Ana Sayfa Metni (display.py)
Sabit kural — degistirilemez:
"Bu oran verinin tamlik ve dogrulama seviyesidir, hissenin yukselme ihtimali degil."
- `DISCLAIMER_TEXT` sabiti; ConfidenceResult.disclaimer alani bu metni tasir; degistirme girisimi hata verir

## 9. Ozel Senaryolar
- Yeni halka arz (NEW_LISTING): history_sufficiency NOT_APPLICABLE degil, LIMITED olarak sayilir;
  eksik gecmis "sifir veri" yapilmaz; favorite_eligible=False + "Yeni halka arz — sinirli gecmis" notu
- Aktif tedbir: restriction_check FAILED ise scoring_ready=False (technical_ready etkilenmez)
- Eski veri: data_freshness STALE -> uyari + favorite_eligible=False

## 10. Testler (tests/blok15/test_confidence.py) — TAM 100 test
Kategoriler:
1. Tam veri: 12 bilesen OK -> confidence 100, tum ready'ler True (~14)
2. Kismi veri: bazi bilesenler MISSING/UNVERIFIED -> confidence araligi, missing_fields (~16)
3. Kritik eksik: critical FAILED -> ust sinir + uyari + favorite_eligible False (~14)
4. Eski veri: STALE -> uyari + favorite False, technical_ready etkilenmez kurali (~12)
5. Aktif tedbir: TRADING_HALT -> scoring_ready False, technical_ready True kalabilir (~12)
6. Yeni halka arz: NEW_LISTING -> sinirli gecmis, favorite False, not (~10)
7. Agirlik yonetimi: set_weights, toplam dogrulama, bilinmeyen bilesen reddi, NOT_APPLICABLE dagitimi (~12)
8. Kapsam kilidi + disclaimer: yasakli alan yok, metin sabit (~10)
Toplam = 100; `pytest tests/blok15 -v`

## 11. Kisitlar
- Sadece BLOK 15 dosyalari; BLOK 6-14'e DOKUNULMAZ (entegrasyonlar enjeksiyonla)
- stdlib only; deterministik; saat enjekte; gercek ag YOK
- Hisse skoru/sinyal/puan YOK — kapsam kilidi testle kanitlanmali
