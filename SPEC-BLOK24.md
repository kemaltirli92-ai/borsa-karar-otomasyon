# SPEC-BLOK24 — Sistem Yukluluk Envanteri (✓/✗ isaretleri)

Site: `/mnt/agents/output/telegram-sender/docs.html` (2485 satir; BLOK 23 tamam)
Repo: `/mnt/agents/output/borsa-karar-otomasyon` (BLOK 6-23, 1700 test)

## AMAC
Yonetici sayfasindaki her numarali/harfli ogenin yanina GORUNUR + MAKINE-OKUNABILIR
durum rozeti: ✓ SISTEMDE YUKLU (agent is akisi olarak kodlandi ve testi gecti) /
✗ BOS YAZI (yalnizca tasarim/kural metni — sisteme yuklenmedi).

## DURUM TABLOSU (repo gercegi — TARTISILMAZ)
### Sayilar (9 akis adimi + 9 BOLUM basligi) — ayni kodlari paylasir
| Kod | Ad | Durum | Kanit |
|---|---|---|---|
| BOLUM-1 | VERI TOPLAMA | bos-yazi | Endeks veri toplayicilari (VIOP, kuresel, doviz/CDS) repoda YOK |
| BOLUM-2 | ENDEKS SKORLAMA | bos-yazi | Skor motoru bu repoda YOK (Bolum 1-2 baska konumda) |
| BOLUM-3 | HISSE TARAMASI | yuklu | app/services/stock_scanning/ + tests/blok6-23 (1700 test) |
| BOLUM-4 | HISSE SKORLAMA | bos-yazi | Skorlama modulu yok; sayfada "HENUZ CANLI DEGIL" banti |
| BOLUM-5 | TEKNIK GOSTERGE ANALIZI | bos-yazi | Gosterge motoru yok (RSI/MACD hesaplayici yok) |
| BOLUM-6 | SEVIYE HARITASI | bos-yazi | Seviye motoru yok |
| BOLUM-7 | HABER ANALIZI | bos-yazi | Haber TOPLAMA yuklu (BLOK 12) ama analiz/ton skoru yok |
| BOLUM-8 | PORTFOY DAGILIMI | bos-yazi | Portfoy motoru yok |
| BOLUM-9 | RAPOR YAYINI | bos-yazi | Web+API yuklu ama otomatik 09:45 yayin + bildirim yok |
### Harfler B1-B13 (hepsi bos-yazi — Endeks Skorlama motoru bu repoda YOK)
B1 bos-yazi (talimat/kavram) · B2 bos-yazi (motor yok) · B3 bos-yazi (zamanlayici
unitler repoda VAR ama tetiklenen motor yok) · B4-B10 bos-yazi · B11 bos-yazi
(AI entegrasyonu da yok) · B12 bos-yazi · B13 bos-yazi (db/schema.sql + systemd
artefaktlari VAR ama backtest/golge mod/aciklama motoru yok)
### C kartlari C1-C13 — TAMAMI yuklu (TEST_GECTI, tests/blok6-16 karsiliklari)
### BLOK kartlari
BLOK-5 bos-yazi (modul kaynaklari bu repoda YOK — yazida kalanlar maddesi 1)
BLOK-6 yuklu · BLOK-17 yuklu · BLOK-18 yuklu · BLOK-19 yuklu · BLOK-20 yuklu ·
BLOK-21 yuklu · BLOK-22 yuklu
TOPLAM: 53 oge = 9 bolum + 13 B + 13 C + 18 blok(5-22). yuklu=21, bos-yazi=32.

## YAPILACAKLAR (docs.html — yalniz ekleme, silme YOK)

### 1. CSS (</style> oncesi, satir 62 oncesi)
```css
.yd{display:inline-block;margin-left:10px;padding:2px 10px;border-radius:10px;
font-size:10px;font-weight:800;letter-spacing:.6px;vertical-align:middle}
.yd-ok{background:rgba(34,197,94,.15);color:#22c55e;border:1px solid #22c55e}
.yd-no{background:rgba(239,68,68,.15);color:#ef4444;border:1px solid #ef4444}
```

### 2. Rozet formati (her hedef basliga, h3 kapanmadan once eklenir)
```html
<span class="yd yd-ok" data-kod="BOLUM-3" data-durum="yuklu" data-test="1700/1700"
aria-label="SISTEMDE YUKLU">✓ SISTEMDE YUKLU</span>
<span class="yd yd-no" data-kod="BOLUM-4" data-durum="bos-yazi" data-test="yok"
aria-label="BOS YAZI — sisteme yuklenmedi">✗ BOS YAZI</span>
```
- ✓ = U+2713, ✗ = U+2717 + ASCII kelimeler (YUKLU/BOS YAZI) — scraper dostu
- Akis adimlari (satir 92-137, .step icindeki .num): adim basliginin (.ttl) yanina
  AYNI kodlarla rozet (data-kod="AKIS-1".."AKIS-9", durum BOLUM-N ile ayni)
- BOLUM basliklari (bolum-no span iceren h3'ler): satir 149 (BOLUM-1), ~920 (BOLUM-3),
  ~1187 (BOLUM-4), ~1214 (5), ~1238 (6), ~1256 (7), ~1301 (8), ~1314 (9)
  NOT: BOLUM-2'nin kendi bolum-no basligi YOK; onun yerine "ENDEKS SKORLAMA SERISI
  (B1-B13)" kart basligina (satir ~286) data-kod="BOLUM-2" rozeti eklenir.
- B1-B13: bolum-no span'i B1..B13 iceren 13 h3
- C1-C13: "C1 — ", "C2 — " ... ile baslayan 13 h3 → hepsi yd-ok
- BLOK kartlari: satir 949 (BLOK 5 → yd-no!), 965 (BLOK 6 → yd-ok), 1187 (17),
  1201 (18), 1215 (19), 1229 (20), 1243 (21), 1257 (22) → 17-22 yd-ok
  BLOK 5 rozet metni: "✗ BOS YAZI (bu repoda yuklu degil)" aria-label ile

### 3. Legend + ozet tablo (GENEL AKIS SEMASI bolumunden HEMEN sonra, ~satir 145)
`id="sistem-yukluluk-envanteri"` yeni kart:
- Legend: ✓ SISTEMDE YUKLU = kod + test bu repoda, is akisi calisiyor ·
  ✗ BOS YAZI = kural/tasarim yazili, sisteme yuklenmedi (nedenleri blok-serisi-derin-rehber
  "YAZIDA KALANLAR" bolumunde)
- Ozet tablo: 53 satir (Kod | Ad | Durum | Kanit) — her satirda data-kod + data-durum
- Sayaç ozeti: "53 ogeden 21'i YUKLU, 32'si BOS YAZI (2026-07-15, 1700/1700 test)"

### 4. JSON manifest (kart icinde, tablodan sonra — makine tarayicilar icin)
```html
<script type="application/json" id="sistem-envanteri-json">
{"generated":"2026-07-15","total":53,"yuklu":21,"bos_yazi":32,
"items":[{"kod":"BOLUM-1","ad":"VERI TOPLAMA","durum":"bos-yazi","kanit":"..."}, ...]}
</script>
```
53 ogenin TAMAMI; kod/ad/durum/kanit alanlari zorunlu; JSON gecerli (parse edilebilir).

## TESTLER — `tests/blok24/` TAM 100
Yol cozumu: blok18 cift-aday deseni (telegram-sender / repo koku).
| Dosya | Adet | Kapsam |
|---|---|---|
| test_rozet_sayilar.py | 22 | 9 AKIS adimi rozeti (kod+durum dogru) (9); 9 BOLUM rozeti (kod+durum dogru: 3 yuklu, digerleri bos-yazi) (9); BOLUM-3 rozeti data-test="1700/1700" (1); rozetler h3/ttl icinde (1); ✓=U+2713 ✗=U+2717 karakterleri dogru (2) |
| test_rozet_harfler.py | 26 | B1-B13 rozetleri var + hepsi bos-yazi (13+1); B3 rozeti bos-yazi (unit var motor yok) (1); C1-C13 rozetleri var + hepsi yuklu (13); her rozette data-kod+data-durum (2) — toplamda 30 degil 26: B1..B13 tek tek (13), hepsi bos-yazi toplu (1), C1..C13 tek tek yuklu (13)→27 olursa dagilim duzeltilir; KESIN toplam 26 |
| test_rozet_bloklar.py | 18 | BLOK 5 rozeti bos-yazi + "bu repoda yuklu degil" notu (2); BLOK 6 + 17-22 rozetleri yuklu (7); blok kartlarinda mevcut "TAMAMLANDI" metni korundu (7); rozetler kart h3'unde (2) |
| test_envanter_tablosu.py | 16 | bolum id var (1); legend ✓/✗ aciklamasi (2); tabloda 53 satir (1); her satirda data-kod+data-durum (2); yuklu=21 bos-yazi=32 sayaci tutarli (2); sayac ozeti metni (1); tablo satirlari rozetlerle tutarli (kod kumesi esit) (2); AKIS kodlari tabloda YOK (ayri kod uzayi) veya aciklandi (1); aria-label'lar (2); sayfa icinde tek id (2) |
| test_json_manifest.py | 10 | script tag var (1); json.loads parse (1); 53 items (1); total/yuklu/bos_yazi alanlari dogru (3); her itemda kod/ad/durum/kanit (1); kodlar benzersiz (1); durum degerleri yalniz {yuklu,bos-yazi} (1); tablo ile ayni kod kumesi (1) |
| test_durustluk_kilidi.py | 8 | BOLUM-3 yuklu ise app/services/stock_scanning repoda VAR (1); BOLUM-4/5/6/8 bos-yazi: repoda skorlama/gosterge/seviye/portfoy modulu YOK (dosya taramasi) (4); BLOK-5 bos-yazi: evren modulu kaynaklari repoda yok (1); yasakli sahte iddia: "B2 yuklu", "endeks motoru calisiyor" ifadeleri YOK (2) |
| **TOPLAM** | **100** | |

## TESLIM
1. docs.html guncellemeleri (CSS + rozetler + legend/tablo + JSON)
2. tests/blok23 korunur; tests/blok24/ TAM 100 — 100/100
3. Regresyon blok6-24 = 1800/1800
4. Son rapor: rozet sayilari + pytest kanitlari
