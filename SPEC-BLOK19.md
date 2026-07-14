# SPEC — BLOK 19: Hisse Detayi ve Ham Fiyat Grafikleri

Proje: borsa-karar-otomasyon (statik frontend + VPS API)
Onceki durum: BLOK 18 (index.html: XK100 karti + 100 Hisse Ozeti tablosu + DEMO bantlari, 100/100 test).
Kurallar: mevcut tasarim SILINMEZ; bu asamada Bolum 5/6 teknik gostergeleri YASAK; sahte veri canli gibi GOSTERILMEZ.

## 1. Kapsam (index.html'e EKLEME — mevcut icerik korunur)

### 1a. Hisse Detay Gorunumu (modal/panel)
- 100 Hisse Ozeti satirina tiklayinca acilan detay paneli: id="stk-detail"
- Kapat butonu + ESC; panel acilinca tablo arka planda kalir
- Bolumler (yalnizca Hisse Taramasi verileri):
  1. Sirket bilgisi: kod, kisa ad, sektor, XK100 uyelik durumu (aktif/arsiv)
  2. Fiyat ozeti: son dogrulanmis fiyat, gunluk degisim %, son islem tarihi
  3. Tarama ozeti: tarama durumu (11 durum), Veri Guveni (0-100), eksik veri uyarilari listesi
  4. KAP listesi: son N bildirim (tip, baslik, tarih, revizyon rozeti) — GET /api/stocks/{symbol}/kap
  5. Dogrulanmis ham haber listesi — GET /api/stocks/{symbol}/news (dedupe canonical)
  6. Kurumsal islemler — GET /api/stocks/{symbol}/corporate-actions (11 tip)
  7. Aktif tedbirler — GET /api/stocks/{symbol}/restrictions (7 tip, aktif/gecmis rozeti)
  8. Grafikler (1b)

### 1b. Grafikler (saf canvas, harici grafik kutuphanesi YOK — vanilla JS + <canvas>)
- Mum grafigi: Open/High/Low/Close, dogrulanmis (validated) OHLCV
- Hacim grafigi: AYNI tarih ekseni, mum grafiginin altinda paylasilan x-ekseni
- Aralik butonlari: 30, 60, 3AY (90 gun), 6AY (180 gun), 1YIL (260 gun), MAKSIMUM
  — GET /api/stocks/{symbol}/prices?range=30|60|90|180|260|max
- Eksik gun: sifir mum OLUSTURMA — o gun grafikte atlanir (bosluk), tarih ekseni islem gunlerinden olusur
- Tatil gunu: sahte mum OLUSTURMA (grafikte yer almaz)
- Kurumsal islem isareti: grafik altinda olay isaretleri (D temettu, B bedelsiz, S bolunme...) +
  tooltip benzeri baslik listesi (destekleniyorsa — API isaret gonderirse)
- Ham/Duzeltilmis secenegi: iki buton "HAM FIYAT" / "DUZELTILMIS FIYAT" — acik etiketli;
  secili olan vurgulu; duzeltilmis seri yoksa buton pasif + "duzeltilmis seri yok" notu
- YASAK LISTESI (Bolum 5/6): Bollinger, POC, RSI, MACD, Teknik AL/SAT, destek/direnc, hareketli ortalama,
  fibonacci, gosterge paneli — bu adimda EKLENMEZ; koda da eklenmez (testle taranir)
- Responsive: canvas genisligi container'a uyar; @media (max-width:640px) grafigi yeniden boyutlandir
  (resize listener); mobil tasmasin: detay paneli max-width:100vw, overflow-x:hidden, tablo scroll-wrap

### 1c. Veri Yok Durumlari (5 durum — grafik alaninda bos canvas yerine durum karti)
- FIYAT VERISI YOK (sufficiency=PRICE_DATA_MISSING)
- SINIRLI VERI (LIMITED_DATA)
- YENI HALKA ARZ (NEW_LISTING)
- DOGRULAMA BEKLIYOR (review/pending durumu)
- AKTIF ISLEM DURDURMA (active TRADING_HALT)
Durum karti: renkli rozet + aciklama + (halka arz icin) "eksik gecmis uretilmez" notu.

### 1d. API baglanti
- Detay: GET /api/stocks/{symbol}, /scan/latest, /kap, /news, /corporate-actions, /restrictions, /prices?range=
- fetch hatasi -> HENUZ_CALISMA_YOK / "veri alinamadi" durum karti (sahte veri YOK)
- Puan kilidi: detayda Hisse Skoru/hisse_skoru/stock_score gibi alanlar ekrana BASILMAZ

## 2. Testler (tests/blok19/test_stock_detail.py) — TAM 100 test
Statik analiz + JS kaynak testleri (index.html okunur):
1. Grafik veri formati: OHLC 4 alan + volume + tarih ekseni paylasimi + validated seri secimi (~14)
2. Aralik butonlari: 6 aralik + range parametreleri (30/60/90/180/260/max) (~12)
3. Eksik/tatil gunu: sifir mum uretimi kodda YOK; bosluk/atla mantigi var (~10)
4. Ham/Duzeltilmis etiketleri: 2 buton + acik etiket + pasif durum (~10)
5. Kurumsal islem isaretleri: olay isaret katmani + rozet harfleri (~8)
6. Veri yok durumlari: 5 durum karti + mesajlar (~14)
7. Responsive/mobil: @media 640px, max-width:100vw, overflow-x, resize listener (~12)
8. API baglanti: 7 ucu fetch, hata durum karti, puan kilidi (~12)
9. YASAK LISTESI: Bollinger/POC/RSI/MACD/AL-SAT/destek-direnc kelimeleri grafik kodunda YOK (~8)
Toplam = 100; `pytest tests/blok19 -v`

## 3. Dogrulama (orkestrator)
- Canli sayfa: tablodan satira tiklayinca detay acilir, grafik + listeler gorunur, kapanir
- Mobil ekran (dar viewport): detay tasmaz
- Yasak listesi taramasi: kodda yasakli gosterge YOK
- Regresyon: 1200/1200 + 100 yeni = 1300/1300

## 4. Kisitlar
- Sadece index.html + tests/blok19/; docs.html'e DOKUNULMAZ; blok6-18'e DOKUNULMAZ
- Harici grafik kutuphanesi YOK (vanilla canvas); framework YOK
- Sahte veri uretimi YOK; puan kilidi
