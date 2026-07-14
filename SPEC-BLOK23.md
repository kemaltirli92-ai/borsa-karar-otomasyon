# SPEC-BLOK23 — Tam Sistem Denetimi + Yonetici Derin Dokumantasyonu

Repo: `/mnt/agents/output/borsa-karar-otomasyon` (BLOK 6-22, 1600 test)
Site: `/mnt/agents/output/telegram-sender/` (index.html 1918 satir, docs.html 2006 satir)

## TARAMA SONUCLARI (orkestrator kesfi — SPEC'in temeli)

### Musteri sayfasi (index.html) durumu — BLOK 18/19/20 TAM
Mevcut: offline-banner, header (DEMO rozetli tarih/endeks/rapor), xk100-scan-card (8 alan),
gauge (DEMO), favori (DEMO), 100 Hisse Ozeti (17 sutun, 8 filtre, 3 siralama, sayfalama),
stk-detail paneli 8 bolum (1 Sirket, 2 Fiyat Ozeti, 3 Tarama, 4 KAP, 5 Haber, 6 Kurumsal,
7 Tedbir, 8 Ham Grafikler: sd-candles + sd-volume, 6 aralik, HAM/DUZELTILMIS),
ASELS/TUPRS/ALFAS demo bolumleri (mum, teknik gosterge, skor bar, seviye haritasi),
portfoy pasta (DEMO), BLOK20 footer (native HAZIR BEKLIYOR), PWA manifest+sw.
**GAP: musteri sayfasinda blok eksiği YOK** — dogrulama testleri bunu kanitlayacak.
Canvas envanteri (17): gauge, c1, mumASELS, hacASELS, c2, sevASELS, mumTUPRS, hacTUPRS,
c3, sevTUPRS, mumALFAS, hacALFAS, c4, sevALFAS, c8, sd-candles, sd-volume.

### Yonetici sayfasi (docs.html) GAP listesi
1. Bolum 3'te BLOK 17-22 kartlari YOK (son kart C13; BLOK 5 ve 6 kartlari var).
2. Blok serisinin derin calisma detayi YOK (dosyalar, komutlar, is akislari, AI kullanimi).
3. "Yazida kalan / bosta / anlasilmayan" durust envanteri YOK.
4. En altta ana sayfa piksel-piksel is akisi rehberi YOK (eski MUSTERI SAYFASI TAM
   ENVANTERI karti BLOK 18 oncesi durumu anlatiyor — GUNCEL degil; silinmez, uzerine
   guncellemeye yonlendiren not eklenir).
5. Repo gercegi: `app/services/` altinda yalniz `stock_scanning` var — Endeks Skorlama
   (Bolum 1-2) motoru BU REPODA YOK (kullanici baska yerde 268 testle tamamladi).
   BLOK 5 modul kaynaklari da repoda yok (yalniz test). Bunlar acikca yazilmali.

## YAPILACAKLAR

### 1. docs.html — Bolum 3'e BLOK 17-22 kartlari (C13 kartindan sonra, BOLUM 4 oncesi)
Her kart mevcut kart formatinda (h3 + dot, tablo: Kural aciklamasi / Gercek calisan dosya /
Gercek tablo veya artefakt / Gercek test dosyasi / Son test sonucu / Uygulama durumu):
- BLOK 17 YONETICI SISTEM SEMASI SAYFASI: docs.html OZET+C1-C13; test tests/blok17 YOKSA
  durust yaz (blok17 test dizini repoda yok — bu blogun dogrulamasi manuel/script yapildi);
  durum: TEST_GECTI (blok18-22 regresyonunda sayfa testleri geciyor)
- BLOK 18 MUSTERI ANA SAYFASI: telegram-sender/index.html + tests/blok18 (100/100)
- BLOK 19 HISSE DETAY + HAM GRAFIK: index.html stk-detail + tests/blok19 (100/100)
- BLOK 20 MOBIL ENTEGRASYON: manifest.webmanifest, sw.js, docs/api-contract.json,
  app/services/stock_scanning/events.py + tests/blok20 (100/100)
- BLOK 21 GUVENLIK/LOG/IZLEME/YEDEKLEME: app/ops/* (11 modul), systemd/xk100-backup.* +
  tests/blok21 (100/100)
- BLOK 22 TEST/VPS DEPLOYMENT/TAMAMLANMA: app/acceptance/*, app/api/health.py, deploy/* +
  tests/blok22 (100/100; toplam 1600/1600)

### 2. docs.html — yeni mega bolum: `id="blok-serisi-derin-rehber"`
Baslik: "BLOK SERISI (5-22) — SISTEMIN TAM CALISMA DETAYI (HERKES ICIN, EN INCE AYRINTI)"
Icerik sirasi:
a) GENEL MIMARI AKIS (tablo/liste): Evren -> Kimlik -> Fiyat+Hacim -> OHLCV Dogrulama ->
   KAP -> Haber -> Kurumsal/Tedbir -> Zamanlama/Durum -> Veri Guveni -> Veri Tabani ->
   API -> Zarf -> Web/Mobil. Her okun yaninda gercek modul yolu.
b) BLOK BLOK CALISMA DETAYI (BLOK 5..22, her blok icin alt kart):
   - Ne yapar (2-3 cumle, herkesin anlayacagi dilde)
   - Gercek dosyalar (repoda dogrulanmis yollar)
   - Veri girisi -> cikisi (alan adlariyla)
   - Komutlar (varsa): systemd unit/timer adi, CLI (python -m app.ops.backup_run),
     cron satiri, API ucu
   - Is akisi adimlari (1,2,3... numarali)
   - Yapay zeka kullanimi: var/yok + durum
   - Durum: CALISIYOR(TEST_GECTI) / YAZIDA KALDI / BOSTA
c) KOMUT KATALOGU (tablo): her komut satiri + ne ise yarar + nerede calisir:
   systemctl enable --now xk100-api.service, xk100-index-scoring.timer,
   xk100-hisse-tarama.timer, xk100-backup.timer; python -m
   app.services.stock_scanning.orchestration.run_scan; python -m app.ops.backup_run;
   python -m pytest tests/blokNN -q; curl -fsS https://<domain>/health; nginx -t;
   certbot --nginx; logrotate /etc/logrotate.d/xk100; bash deploy/deploy.sh (VPS).
   Her komutun durumu: HAZIR / VPS'TE CALISACAK / GELISTIRME ORTAMINDA CALISTIRILMAZ.
   Anlasilmayan komut YOK — hepsinin aciklamasi var (bunu acikca yaz).
d) YAPAY ZEKA ENVANTERI (durust tablo):
   - news/ai_adapter.py: OPSIYONEL, KAPALI (ai_client=None varsayilan; anahtar yok;
     acikken yalnizca belirsiz eslesmeleri oylar, hata taramayi DURDURMAZ)
   - Jeopolitik hibrit AI (Bolum 2 B11): kural+kod motoru kavrami; bu repoda AI cagrisi YOK
   - Bunun disinda HICBIR blokta yapay zeka cagrisi YOKTUR (acikca yaz)
   - Gemini/ChatGPT/Kimi API anahtari: .env'de alan YOK, entegrasyon YAZIDA KALDI
e) YAZIDA KALANLAR (durust liste, her biri neden + ne gerekiyor):
   1. BLOK 5 evren modulu kaynaklari — bu repoda YOK (yalniz test dosyasi); eklenecek
   2. Endeks Skorlama motoru (Bolum 1-2, 268 test) — bu repoda YOK; ayri konumda
   3. Gercek VPS deployment — deploy/ artefaktlari HAZIR, bu ortamdan SSH YOK;
      VPS'te `sudo bash deploy/deploy.sh` calistirilacak
   4. Lisansli fiyat API baglantisi — .env anahtarlari bos; gercek fetcher enjekte
      edilmeyi bekliyor (modul hazir, anahtar yok)
   5. Resmi XK100 listesi provider baglantisi — UniverseBook listeyi URETMEZ, enjekte
      bekliyor
   6. Native mobil uygulama — HAZIR_BEKLIYOR (sozlesme hazir, uygulama yazilmadi)
   7. Musteri bildirim kurallari (Bolum 9) — olusturulmadi; events.py yalniz 3 dahili olay
   8. Telegram entegrasyonu — PASIF (.env bos, gonderim kodu yok)
   9. PostgreSQL yedek motoru — secenek hazir; birincil SQLite (migrasyon ayri blok)
   10. Hisse Skorlama modulu (Bolum 4) — HENUZ CANLI DEGIL (musteri sayfasinda bant var)
   11. Teknik gosterge/seviye/portfoy analiz motorlari (Bolum 5-8) — yazida; sayfadaki
       ilgili grafikler DEMO
   12. 09:45 rapor yayini (Bolum 9) — yazida
f) BOSTA / BEKLEMEDE OLANLAR (durust liste):
   - gauge (endeks yon gostergesi): DEMO veriyle donuyor; gercek endeks skoru bekliyor
   - XK100 Tarama Durumu karti: API'ye BAGLI ama ilk tarama olmadigi icin
     "HENUZ CALISMA YOK" gosteriyor (BOSTA-BEKLEMEDE; sahte doldurma YOK)
   - 100 Hisse Ozeti tablosu: API'ye BAGLI, ilk tarama bekliyor (BOSTA-BEKLEMEDE)
   - DUZELTILMIS FIYAT butonu: duzeltilmis seri henuz uretilmedigi icin DISABLED (BOSTA)
   - source_health gorsel ekrani: backend kayit modulu HAZIR (app/ops/source_health.py),
     docs.html'e canli baglanti YAZIDA KALDI (BOSTA — admin API'ye endpoint eklenecek)
   - offline-banner: yalnizca sw eski onbellek sunarsa acilir (gizli varsayilan — dogru)
   - haber AI adaptoru: KAPALI (BOSTA)

### 3. docs.html — EN ALTA yeni bolum: `id="ana-sayfa-is-akisi-rehberi"` (ftr'den ONCE)
Baslik: "ANA SAYFA (index.html) TAM IS AKISI REHBERI — HER METIN, HER GRAFIK, HER BUTON"
Her oge icin satir: Oge (id) | Ne gosterir | Veriyi nereden alir | Is akisi (adim adim) |
Durum: CANLI-API'YE BAGLI / DEMO / BOSTA-BEKLEMEDE / BOSTA.
KAPSAM ZORUNLU (hicbiri atlanamaz):
- 17 canvas'in TAMAMI (gauge, c1, mumASELS, hacASELS, c2, sevASELS, mumTUPRS, hacTUPRS,
  c3, sevTUPRS, mumALFAS, hacALFAS, c4, sevALFAS, c8, sd-candles, sd-volume)
- xk100-scan-card 8 alani (xk100-scan-status, scanned-count, full-count, partial-count,
  failed-count, avg-confidence, last-updated, scan-run-id)
- stk-* kontrolleri: 8 filtre (flt-symbol, flt-name, flt-sector, flt-scan-status, flt-kap,
  flt-news, flt-measure, flt-min-confidence), siralama (sort-by, sort-dir), sayfalama
  (page-size, page-prev, page-next, page-info), stk-table/stk-tbody, stk-cards (mobil)
- stk-detail butonlari: sd-close, 6 aralik butonu, sd-btn-raw, sd-btn-adj, sdOpen(sym)
- offline-banner, demo-badge'ler, demo-band'ler, b20-footer (native HAZIR BEKLIYOR)
- API baglanti katmani: hangi ucu cagirir (/api/xk100/scan/latest, /api/xk100/stocks,
  /api/stocks/{symbol}, /api/stocks/{symbol}/prices, /kap, /news, /corporate-actions,
  /restrictions) + zarf alanlari + hata maskeleme
Durum kurallari (DURUST): demo bolumler DEMO; XK100 kartlari CANLI-API'YE BAGLI +
BOSTA-BEKLEMEDE (ilk tarama yok); sd-btn-adj BOSTA; hicbir demo oge "canli" DENMEZ.
Ayrica eski "MUSTERI SAYFASI TAM ENVANTERI" kartinin basina guncelleme notu:
"Bu kart BLOK 18 oncesi durumu anlatir; GUNCEL rehber sayfanin en altindaki
'ana-sayfa-is-akisi-rehberi' bolumudur."

### 4. index.html — DEGISIKLIK YOK (gap bulunmadi); testler bunu kilitler

## TESTLER — `tests/blok23/` TAM 100 (dagilim KESIN)
Yol cozumu: tests/blok18'deki cift-aday deseni (telegram-sender veya repo koku) — docs.html
icin de ayni desen. Repo kokunden pytest ile calisir.
| Dosya | Adet | Kapsam |
|---|---|---|
| test_blok_kartlari.py | 12 | BLOK 17-22 kartlari var (6); her kartta gercek dosya yolu repoda mevcut (4); kartlarda test sayilari dogru (100/100, 1600/1600) (2) |
| test_derin_rehber.py | 22 | mega bolum id'si var (1); BLOK 5..22'nin TAMAMI rehberde gecer (18); genel mimari akis tablosu (1); her blok alt kartinda "Is akisi" + "Yapay zeka" satiri (2) |
| test_komut_katalogu.py | 12 | katalog tablosu (1); 7 systemd unit/timer adi gecer + dosyalari repoda var (4); CLI komutlari (run_scan, backup_run) modulleri repoda var (2); health/nginx/certbot/logrotate satirlari (2); her komutun durum etiketi (HAZIR/VPS/GELISTIRME) (3) |
| test_ai_envanteri.py | 8 | ai_adapter KAPALI ibaresi (2); "bunun disinda yapay zeka cagrisi YOKTUR" ibaresi (1); jeopolitik AI notu (1); .env'de AI anahtar alani olmadigi ibaresi (1); sahte "AI aktif" iddiasi YOK (3 yasakli ifade taramasi) |
| test_yazida_kalanlar.py | 12 | 12 maddenin TAMAMI listede (12) — BLOK5 repo yok, endeks motoru repo yok, deployment calistirilmadi, lisansli API bos, resmi liste provider, mobil HAZIR_BEKLIYOR, bildirim kurallari yok, telegram pasif, postgres secenek, hisse skorlama canli degil, bolum 5-8 motorlari yazida, 09:45 yayin yazida |
| test_bosta_envanteri.py | 10 | BOSTA/BOSTA-BEKLEMEDE isaretli ogeler: gauge, scan-card, hisse ozeti, sd-btn-adj, source_health ekrani, haber AI (6); offline-banner "gizli varsayilan" notu (1); hicbir BOSTA oge "canli" denmez (3 yasakli ifade) |
| test_ana_sayfa_rehberi.py | 16 | bolum id'si + ftr'den once konum (2); index.html'deki 17 canvas id'sinin TAMAMI rehberde gecer (1, dinamik cikarim); xk100-* 8 alan id'si (1); 8 filtre id'si (1); siralama+sayfalama id'leri (1); sd-* buton id'leri (1); API uclari /api/xk100/scan/latest + /api/xk100/stocks + /api/stocks/ rehberde (2); durum etiketleri CANLI-API/DEMO/BOSTA her satirda (2); demo ogeler DEMO etiketli (2); eski envanter kartina guncelleme notu eklendi (1); rehberde "Is akisi" aciklamalari (2) |
| test_site_butunlugu.py | 8 | index.html korundu: BLOK18/19/20 markerlari + demo rozetler + HISSE SKORLAMA bandi (4); docs.html mevcut bolumleri silinmedi: BOLUM 1-9 basliklari + C1-C13 + BLOK5/6 kartlari (3); docs.html'de kirik olmayan yapisal kontrol: yeni id'ler benzersiz (1) |
| **TOPLAM** | **100** | |

## TESLIM
1. docs.html guncellemeleri (3 ekleme + 1 not)
2. tests/blok23/ TAM 100 test — 100/100
3. Regresyon blok6-23 = 1700/1700
4. Son rapor: eklenen bolumler + pytest kanitlari
