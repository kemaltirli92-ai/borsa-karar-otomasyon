# SPEC — BLOK 10: Hacim ve TL Islem Hacmi Modulu

Proje: borsa-karar-otomasyon (VPS uzerinde Python servis, stdlib)
Bolum 3: Hisse Taramasi — BLOK 10
Onceki durum: Bolum 1-2 (268) + BLOK 5-9 (5x100) tamam. Toplam test havuzu: 400 (blok6-9).
Konvansiyon: stdlib only, ASCII identifier, Turkce docstring, gercek ag YASAK, saat enjekte.

## 1. Amac
Gunluk islem verisinde iki farkli buyuklugu katiyen ayristiran modul:
- volume_units: el degisen pay ADEDI (adet)
- TL islem hacmi: turnover_try (kaynaktan gercek) veya estimated_turnover_try (tahmin)
- 20 gunluk hacim orani ve hacim durum siniflandirmasi
- Anormal hacim asla tek basina AL/SAT sinyali uretmez

## 2. Dosya Yapisi
```
app/services/stock_scanning/
  volume/
    __init__.py
    models.py        # VolumeBar, VolumeMetrics, TurnoverType, VolumeStatus enum'lari
    turnover.py      # TL hacim ayrimi: resmi/saglayici/tahmin; tahmin formulu
    ratio.py         # 20 gunluk hacim orani (son gun ortalamaya dahil degil)
    classifier.py    # hacim durum siniflandirici (6 durum) + sinyal kilidi
    analyzer.py      # VolumeAnalyzer: seri analizi, eksik gun, gercek sifir ayrimi
tests/blok10/
    __init__.py
    test_volume.py   # TAM 100 test
```

## 3. Veri Modeli (models.py)
- `TurnoverType` enum: OFFICIAL (borsa resmi TL hacim), PROVIDER (veri saglayicinin TL hacim alani),
  ESTIMATED (formulle hesaplanan), MISSING (hacim yok)
- `VolumeStatus` enum: NORMAL, INCREASING, HIGH, ANOMALOUS, MISSING, REVIEW_REQUIRED
- `VolumeBar` dataclass: stock_id, trade_date, volume_units (int|None), turnover_try (float|None),
  estimated_turnover_try (float|None), turnover_type, source, is_estimated (bool),
  is_trading_day (bool|None), missing_reason (None|NO_DATA|SOURCE_ERROR|HOLIDAY)
- `VolumeMetrics` dataclass: stock_id, as_of_date, last_volume_units, avg20_volume_units (None olabilir),
  volume_ratio_20 (None olabilir), status, status_reason, signal=None (HER ZAMAN None — sinyal kilidi)

## 4. TL Hacim Ayrimi (turnover.py)
- `resolve_turnover(raw_record, ohlc) -> (turnover_try, estimated_turnover_try, turnover_type)`
  * Kaynakta resmi/saglayici TL hacim alani varsa -> turnover_try dolar, turnover_type = OFFICIAL veya PROVIDER
    (kaynak turu config/kaynak adiyla belirlenir)
  * Yoksa -> estimated_turnover_try = ((open+high+low+close)/4) * volume_units, turnover_type = ESTIMATED,
    turnover_try = None (KARIŞTIRILMAZ)
  * Hacim yoksa -> MISSING, ikisi de None
- `is_estimated` bayragi ESTIMATED'de True; tahmin degeri hicbir ciktida "gercek hacim" etiketi
  tasiyamaz: VolumeBar uzerinde turnover_try=None kalir; serilestirmede alan adi estimated_ oneklidir
- Config: `estimated_label_required=True` — tahmin uretilen her cikti nesnesinde kaynak etiketi zorunlu

## 5. 20 Gunluk Hacim Orani (ratio.py)
- `avg_volume(bars, window=20, exclude_last=True)`:
  * Son gun KENDI ORTALAMASINA DAHIL EDILMEZ: ortalama = son gun HARIC onceki `window` islem gunun ortalamasi
  * Eksik gun (NO_DATA/SOURCE_ERROR/HOLIDAY) ortalamaya KATILMAZ ve pencereyi doldurmaz:
    pencere gecerli (hacmi bilinen) islem gunlerinden kayar
  * Tatil ve kaynak hatasi SIFIR hacim olarak EKLENMEZ (sifir yazilmaz, atlanir)
  * Gecerli sifir hacim (GERCEK sifir: islem gunu ama hacim 0 — islem durdurma degilse) ortalamaya 0 olarak katilir;
    gercek sifir ile eksik hacim AYRISTIRILIR (VolumeBar.volume_units=0 vs None)
- `volume_ratio(last_volume, avg20) -> float|None`: avg20 > 0 ise last/avg20; avg20 == 0 ise None (tanimsiz, sifira bolme yok)
- `compute_ratio_20(series) -> (ratio, avg20, used_days)`: pencerede 20'den az gecerli gun varsa
  eldekiyle hesaplar ama used_days raporlar; minimum esik (config, vars. 5) altindaysa ratio=None + INSUFFICIENT_WINDOW

## 6. Siniflandirici (classifier.py)
- `classify_volume(metrics_or_values, config) -> (VolumeStatus, reason)`
  Eşikler config'ten (varsayilanlar):
  * ratio >= anomalous_threshold (vars. 5.0) -> ANOMALOUS (neden: ratio)
  * ratio >= high_threshold (vars. 2.0) -> HIGH
  * ratio >= increasing_threshold (vars. 1.3) -> INCREASING
  * 0 < ratio < increasing_threshold -> NORMAL
  * son gun hacmi MISSING -> MISSING
  * gercek sifir hacim + aciklama yok -> REVIEW_REQUIRED (islem durdurma suphesi)
  * ANOMALOUS + tek gunluk izole ani sicrama ve onceki gunler de ANOMALOUS degil -> durum ANOMALOUS kalir
- SINYAL KILIDI: VolumeMetrics.signal alani HER ZAMAN None; modulde hicbir fonksiyon
  AL/SAT/FAVORI ciktisi uretemez; sinyal uretme cagrisi yapan kod yolu YOK (testle kanitlanir:
  metrics.signal is None her senaryoda)

## 7. Analyzer (analyzer.py)
- `VolumeAnalyzer(config=None, clock=None)`
- `build_volume_bar(raw_record) -> VolumeBar` — BLOK 8 kaydindan ayrimli bar uretir (turnover.resolve_turnover)
- `analyze_series(stock_id, volume_bars) -> VolumeMetrics` — son gun, avg20, ratio, status
- `classify_gaps(raw_records) -> dict` — eksik gunler: HOLIDAY / SOURCE_ERROR / NO_DATA ayrimi;
  gercek sifirlar ayri listelenir
- Seri siralamasi tarih sirali dogrulanir; ayni tarih tekrari reddedilir (BLOK 9 ile uyumlu)

## 8. Testler (tests/blok10/test_volume.py) — TAM 100 test
Kategoriler:
1. 20 gunluk ortalama dogrulugu (elle hesaplanan beklenen degerler) (~16)
2. Son gun ortalamaya dahil edilmeme (son gun devasa olsa bile ortalama degismez) (~14)
3. Eksik gun: tatil/kaynak hatasi pencereye sifir girmez, kayar pencere, gercek sifir ortalamaya katilir (~16)
4. Gercek sifir vs eksik hacim ayrimi + REVIEW_REQUIRED (~12)
5. Tahmini hacim: formül dogrulugu ((O+H+L+C)/4 x V), is_estimated bayragi, turnover_try=None kalmasi (~16)
6. Hacim turu: OFFICIAL/PROVIDER/ESTIMATED/MISSING dogru atama, tahmin gercek diye gosterilemez (~14)
7. Durum siniflandirma esikleri + sinyal kilidi (signal her zaman None, AL/SAT uretimi yok) (~12)
Toplam = 100; `pytest tests/blok10 -v`

## 9. Kisitlar
- Sadece BLOK 10 dosyalari; BLOK 6-9'a DOKUNULMAZ (BLOK 8 PriceBar duck-typing ile okunabilir)
- stdlib only; deterministik; saat enjekte; ag erisimi yok
- Tahmin/gercek ayrimi ve sinyal kilidi testlerle kanitlanmali
