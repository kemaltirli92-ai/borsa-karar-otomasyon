# SPEC — BLOK 12: Haber Toplama, Eslestirme ve Duplikasyon

Proje: borsa-karar-otomasyon (VPS uzerinde Python servis, stdlib)
Bolum 3: Hisse Taramasi — BLOK 12
Onceki durum: Bolum 1-2 (268) + BLOK 5-11 (7x100) tamam. Toplam test havuzu: 600 (blok6-11).
Konvansiyon: stdlib only (RapidFuzz KURULMAZ — stdlib difflib muadili motor yazilir), ASCII identifier,
Turkce docstring, gercek ag YASAK, saat enjekte.

## 1. Amac
Haber kayitlarini yapilandiran, XK100 sirketleriyle guven skorlu eslestiren ve kopyalari tek habere
indirgeyen modul. Ton/onem/etki puani HESAPLAMAZ (Bolum 7'nin isi).

## 2. Dosya Yapisi
```
app/services/stock_scanning/
  news/
    __init__.py
    models.py        # NewsRecord (10 alan), ContentType, MatchResult, MatchMethod, DedupeResult
    aliases.py       # AliasStore: unvan/kisa ad/eski ad/eski kod/marka/bagli ortaklik/istirak/yonetici
    fuzzy.py         # stdlib fuzzy motor: token_set_ratio (difflib tabanli), normalize+tokenize
    matcher.py       # NewsMatcher: kelime sinirli eslestirme + guven skoru 0-100 + teyit kurallari
    dedupe.py        # DedupeEngine: URL + baslik + metin + zaman + ayni olay + ajans kopyasi
    tagger.py        # icerik etiketleme: reklam/sponsorlu/forum/otomatik fiyat tablosu
    ai_adapter.py    # istege bagli AI adaptor (belirsiz eslesme); hata -> tarama durmaz
    collector.py     # NewsCollector: toplama -> etiketleme -> eslestirme -> duplikasyon zinciri
tests/blok12/
    __init__.py
    test_news.py     # TAM 100 test
```

## 3. Veri Modeli (models.py)
`NewsRecord` dataclass — 10 alan: news_id, title, body, source_name, original_url,
published_at, updated_at, author, content_type, collected_at
`ContentType` enum: NEWS, ADVERTISEMENT, SPONSORED, FORUM, AUTO_PRICE_TABLE, UNKNOWN
`MatchMethod` enum: CODE, FULL_NAME, SHORT_NAME, OLD_NAME, OLD_CODE, BRAND, SUBSIDIARY,
AFFILIATE, EXECUTIVE, EVENT_DATE, AI_ASSISTED, NONE
`MatchResult`: stock_id (None olabilir), match_score (0-100 int), match_method,
matched_entity (eslesen varlik metni), is_confirmed (bool), needs_review (bool)
`DedupeResult`: canonical_news_id, duplicates: list[news_id], reason_codes: list[str]

## 4. Alias Kurallari (aliases.py)
- `AliasStore(identity_service=None, extra=None)`:
  - her stock_id icin varlik seti: code, full_name, short_name, old_names[], old_codes[],
    brand_names[], subsidiaries[] (bagli ortaklik), affiliates[] (onemli istirak), executives[] (ops.)
  - BLOK 6'dan code/old_code/history cekilebilir (enjekte); extra dict ile panel eklentisi
  - tum varliklar normalize edilir (Turkce karakter, kucuk harf, noktalama ayik) — BLOK 6 normalize ile uyumlu
  - `entities(stock_id) -> dict[MatchMethod, list[str]]`
  - ayni alias metni birden cok stock_id'ye bagliysa AMBIGUOUS_ALIAS isaretlenir (otomatik teyit yok)

## 5. Fuzzy Motor (fuzzy.py) — stdlib
- `normalize(text)`, `tokenize(text)` (Turkce), `token_set_ratio(a, b) -> 0-100`
  (difflib.SequenceMatcher tabanli; sirali ortak token kumeleri; RapidFuzz benzeri)
- `partial_ratio(a, b)`, `best_match(query, candidates) -> (text, score)`

## 6. Eslestirme (matcher.py)
- `NewsMatcher(alias_store, config=None, ai=None, clock=None)`
- KURALLAR:
  * Kelime-ici eslesme YASAK: kod/unvan aramasi her zaman TAM TOKEN (BLOK 6 ile ayni sinir motoru);
    "IS" kodu "ISLEM" icinde yakalanamaz; kisa kodlar (<=2 harf) icin baglam sarti (yaninda borsa/hisse
    baglami kelimesi yoksa kod eslesmesi sayilmaz)
  * Sadece hisse kodu gecmesi KESIN eslesme DEGIL: kod tek basina max 70 skor (is_confirmed=False);
    kod + baglam (unvan/marka/olay) ile 85+ olabilir
  * Skor tablosu (config'den ayarlanabilir):
    - tam unvan tam eslesme: 95 (is_confirmed=True)
    - kisa ad: 88 (confirmed)
    - eski ad/eski kod: 82 (confirmed, historical etiketi)
    - marka/bagli ortaklik: 75 (confirmed ancak baglamla)
    - istirak/yonetici: 65 (confirmed=False, review)
    - kod tek basina: 70 (confirmed=False)
    - fuzzy unvan >= 90: 85 (confirmed)
    - fuzzy 75-89: 60 (confirmed=False, needs_review=True)
    - < 75 fuzzy: eslesme yok
  * DUSUK GUVEN KURALI: match_score < confirm_threshold (vars. 80) -> is_confirmed=False ve
    haber hicbir hisseye KESIN olarak baglanmaz; needs_review listesine duser (stock_id adayi ile)
  * Birden cok hisseye ayni skor -> AMBIGUOUS: hicbirine baglanmaz (BLOK 6 pending davranisi ile uyumlu)
- OLAY ve TARIH karsilastirmasi: ayni olaya ait iki haber (olay anahtar kelimeleri + yayin tarihi
  yakinligi) dedupe'e olay kaniti olarak iletilir
- `match(news) -> list[MatchResult]` (adaylar, skor sirali)

## 7. Duplikasyon (dedupe.py)
- `DedupeEngine(config=None)`:
  * Ayni original_url -> DUPLICATE_SAME_URL (skor 100)
  * Baslik benzerligi >= title_threshold (vars. 85 fuzzy) + metin benzerligi >= body_threshold (vars. 80)
    -> DUPLICATE_TEXT
  * Yayin zamani yakinligi (vars. 30 dk) + baslik benzerligi yuksek -> DUPLICATE_EVENT_TIME
  * Ayni olay: olay anahtar kumesi + ayni hisse + zaman penceresi -> DUPLICATE_SAME_EVENT
  * AJANS KOPYASI: kaynak "agency" (AA, DHA, IHA, Reuters...) isaretliyse ve baska bir site
    ayni/yakin metni yayinladiysa -> AGENCY_COPY; kopyalayan site canonical SAYILMAZ,
    ajans kaynagi canonical olur; kopya site BAGIMSIZ DOGRULAMA sayilmaz (confirmation_credit=False)
  * canonical secimi: ajans > en erken published_at > en uzun body
- `dedupe(records) -> (canonical_list, [DedupeResult])`

## 8. Etiketleme (tagger.py)
- `ContentTagger(config=None)`:
  * reklam/sponsorlu: baslik/metinde "reklam", "sponsorlu", "tanitim yazisi", "advertorial" + kaynak etiketi
  * forum: forum/kullanici yorumu URL desenleri veya source_name forum listesinde
  * otomatik fiyat tablosu: govdesi cogunlukla fiyat/oran satirlari (satir bazli oran esigi), baslik sablonu
  * sonuc: content_type + tag_reasons (birden cok etiket olabilir; NEWS varsayilan)
- Etiketli icerik eslestirmeye GIRER ama ayri etiketle isaretlenir; otomatik fiyat tablosu
  dedupe ve dogrulama kredisine katilmaz

## 9. AI Adaptoru (ai_adapter.py)
- `AiMatcherAdapter(ai_client=None)`:
  - SADECE belirsiz eslestirmeler icin cagrilir (skor araligi config: vars. 55-79)
  - ai_client None -> AI kapali: belirsizler needs_review'da kalir, tarama DEVAM EDER
  - ai_client hata firlatirsa -> AI_SERVICE_ERROR logla, tarama DURMAZ, needs_review
  - ai_client yaniti schema dogrulamasindan gecer; gecersiz yanit yok sayilir
  - AI skoru asla tek basina teyit olamaz (max kaldirir: is_confirmed yine kural motorundan)

## 10. Collector (collector.py)
- `NewsCollector(matcher, dedupe_engine, tagger, clock=None)`:
  - `process(records: list[NewsRecord]) -> NewsProcessResult(records_tagged, matches, dedupe_groups, review_queue)`
  - zincir: etiketle -> her haber icin match -> dedupe -> canonical'lara eslesme aktar
  - PUAN KILIDI: ton/onem/etki puani HESAPLANMAZ (fonksiyon ve alan YOK — sentiment/score/impact adinda alan bulunamaz)

## 11. Testler (tests/blok12/test_news.py) — TAM 100 test
Kategoriler:
1. Dogru haber eslestirme: tam unvan, kisa ad, marka, kod+baglam (~16)
2. Yanlis kod / kelime ici engel: kisa kod baglamsiz, "IS" vs "ISCTR", kod tek basina confirmed=False (~14)
3. Bagli ortaklik + onemli istirak + yonetici eslestirme (~12)
4. Eski sirket adi + eski kod (historical etiketi) (~10)
5. Kopya haber: URL/baslik/metin/zaman/olay duplikasyonu (~16)
6. Ajans kopyasi: canonical=ajans, kopya site bagimsiz dogrulama degil (~12)
7. Etiketleme: reklam/sponsorlu/forum/otomatik fiyat tablosu (~10)
8. AI kapali + AI hata + belirsiz eslestirme + puan kilidi (~10)
Toplam = 100; `pytest tests/blok12 -v`

## 12. Kisitlar
- Sadece BLOK 12 dosyalari; BLOK 6-11'e DOKUNULMAZ (entegrasyon enjeksiyonla)
- stdlib only; RapidFuzz kurulmaz; deterministik; saat enjekte; gercek ag YOK
- Puan/ton hesaplama YOK — kapsam kilidi testle kanitlanmali
