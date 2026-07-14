# SPEC — BLOK 18: Musteri Ana Sayfasi ve 100 Hisse Ozeti

Proje: borsa-karar-otomasyon (statik frontend + VPS API)
Onceki durum: index.html mevcut (851 satir, sabit demo veriler iceriyor).
Kurallar: mevcut tasarim SILINMEZ; bu adimda Hisse Skoru URETMEZ; sahte veri canli gibi GOSTERILMEZ.

## 1. Mevcut Durum Analizi
index.html'de sabit demo verileri var:
- Satir 120: "09.07.2026 Persembe" (SABIT TARIH — canli gibi gorunuyor, DUZELTILECEK)
- Satir 122: "Endeks: 71.5 POZITIF" + Rapor 2026-07-09-INDEX-R1 (sabit)
- Bolum 1: Favori Hisseler + 100 Hisse Ozeti (sabit canvas)
- Bolum 2: ASELS sabit detay (skor 87.4, grafikler, haberler, portfoy %30/25/20/25)
- Portfoy dagilimi: ASELS %30, TUPRS %25, ALFAS %20, NAKIT %25 (sabit)

## 2. Yapilacaklar (index.html — mevcut yapi korunarak)

### 2a. USTE YENI KART: XK100 Tarama Durumu (mevcut header'in ALTINA, Bolum 1'in USTUNE)
Kart alanlari (id'li span'ler — JS ile API'den doldurulur):
- Tarama durumu (SON_TARAMA / HENUZ_CALISMA_YOK / PARTIAL)
- Taranan hisse: X/100
- Tam veri sayisi, kismi veri sayisi, basarisiz sayisi
- Ortalama Veri Guveni (0-100)
- Son guncelleme (last_updated_at)
- scan_run_id
API'den veri gelmezse: "HENUZ CALISMA YOK — ilk sabah taramasi bekleniyor" goster (sahte sayi YOK).

### 2b. 100 HISSE OZETI (yeni bolum, Bolum 1'in ALTINA eklenecek)
Tablo (web) / kart listesi (mobil, <640px):
Sutunlar (17): hisse_kodu, sirket_kisa_adi, sektor, son_dogrulanmis_kapanis, son_islem_tarihi,
gunluk_yuzde_degisim, islem_miktari, tl_hacim (+hacim_turu rozeti: OFFICIAL/PROVIDER/ESTIMATED/MISSING),
hacim_orani_20, veri_guveni, tarama_durumu, kap_sayisi, haber_sayisi,
kurumsal_islem_rozeti (var/yok), aktif_tedbir_rozeti (var/yok), technical_ready, scoring_ready

Filtreler (8): hisse_kodu (arama), sirket_adi (arama), sektor (select), tarama_durumu (select),
kap (var/yok), haber (var/yok), tedbir (var/yok), min_veri_guveni (number)
Siralama (3): gunluk_degisim, hacim_orani, veri_guveni (+ yon asc/desc)

- Sayfalama: WEB'de sayfa/sayfa_boyutu (25/50/100 secim) — 100 hissenin TAMAMI tek cevapta
  cekilmez; sayfa bazli istek (API: GET /api/xk100/stocks?page=&page_size=...)
- Mobil (<640px): tablo yerine kompakt kart listesi (her hisse 1 kart, ayni 17 alan ozet)
- API yoksa/bos ise: "HENUZ CALISMA YOK" + demo_data=false; sahte satir URETILMEZ

### 2c. Sabit veri isaretleri (DUZELTME — sahte canli gorunumu kir)
- Satir 120 "09.07.2026 Persembe": yanina DEMO rozeti + JS'de gercek API verisi gelince degisir;
  API yoksa metin "DEMO ORNEK — gercek veri degil" olarak isaretlenir
- Satir 122 Endeks 71.5 + Rapor: ayni sekilde DEMO rozeti (Bolum 1-2 canli degilse)
- Favori Hisseler bolumu: basliga "HISSE SKORLAMA MODULU HENUZ CANLI DEGIL" bandi eklenir
  (Hisse Skorlama Bolum 4 — henuz yazilmadi). Mevcut canvas/sabit icerik KALIR ama ustunde
  acik DEMO bandi: "BU ALANDAKI DEGERLER DEMO ORNEKTIR — gercek analiz degildir"
- ASELS bolumu (Bolum 2): ayni sekilde DEMO bandi
- Portfoy dagilimi: DEMO bandi
- PUAN KILIDI: bu adimda hicbir yerde yeni Hisse Skoru URETILMEZ; mevcut sabit skorlar (87.4, 71.5)
  DEMO olarak isaretlenir, degistirilmez/silinmez

### 2d. API baglanti katmani (index.html icine <script> — vanilla JS, framework YOK)
- `const API_BASE = ""` (ayni origin) — fetch ile GET /api/xk100/scan/latest + GET /api/xk100/stocks
- fetch basarisiz/404 -> HENUZ_CALISMA_YOK durumu (hata maskeli, console'a log)
- Gelen veri zarfli (scan_run_id vb. BLOK 16) — zarf alanlari dogrulanmadan ekrana basilmaz
- Hisse Skoru alani gelirse GOSTERILMEZ (puan kilidi: skor anahtarlari filtrelenir)

## 3. Testler (tests/blok18/test_index_page.py) — TAM 100 test
Statik analiz testleri (index.html dosyasi okunur, string/DOM benzeri kontroller):
1. XK100 Tarama Durumu karti: 8 alan id'leri mevcut (~10)
2. 100 hisse tablosu: 17 sutun basligi + hacim_turu rozeti + ready rozetleri (~16)
3. Filtreler: 8 filtre kontrolu mevcut (~12)
4. Siralama: 3 siralama secenegi + yon (~8)
5. Sayfalama: page_size secenekleri (25/50/100), sayfa kontrolleri, tek-cevapta-100 yok isareti (~14)
6. Mobil tasma: @media (max-width:640px) kurallari + kart listesi sinifi (~10)
7. DEMO isaretleri: sabit tarih/endeks/favori/ASELS/portfoy bolumlerinde DEMO veya
   "HISSE SKORLAMA MODULU HENUZ CANLI DEGIL" metni (~14)
8. API baglanti: fetch /api/xk100/stocks + /api/xk100/scan/latest, hata maskesi,
   puan kilidi (skor anahtarlari ekrana basilamaz), sahte veri uretimi YOK (~16)
Toplam = 100; `pytest tests/blok18 -v`

## 4. Dogrulama (orkestrator)
- Sayfa deploy sonrasi canlida: XK100 karti + tablo + DEMO bantlari gorunur
- Filtre/siralama/sayfalama JS ile calisiyor (tarayici kontrol)
- Mobil gorunum (dar ekran) kart listesine geciyor
- PUAN KILIDI: sayfada yeni uretilmis skor yok; sabit skorlar DEMO isaretli

## 5. Kisitlar
- Sadece index.html + tests/blok18/ + (gerekirse) kucuk css ekleri; docs.html'e DOKUNULMAZ
- Mevcut icerik SILINMEZ; sadece ekleme + DEMO isaretleme
- Framework/dis bagimlilik YOK (vanilla JS + mevcut inline CSS duzeni)
- Hisse Skoru URETME YOK
