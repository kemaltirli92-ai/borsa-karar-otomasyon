# SPEC — BLOK 16: API ve Rapor Surumu

Proje: borsa-karar-otomasyon (VPS uzerinde Python servis, stdlib)
Bolum 3: Hisse Taramasi — BLOK 16
Onceki durum: Bolum 1-2 (268) + BLOK 5-15 (11x100) tamam. Toplam test havuzu: 1000 (blok6-15).
Konvansiyon: stdlib only (http.server tabanli ama testler handler duzeyinde, gercek soket YOK),
ASCII identifier, Turkce docstring, gercek ag YASAK, saat enjekte.

## 1. Amac
Web sitesi ve mobil uygulamanin TEK veri kaynagi olacak VPS backend API katmani:
- 10 musteri ucu + yonetici uclari
- 12 liste parametresi, sayfalama/filtreleme/siralama
- Rapor surumu zarfi (scan_run_id, report_version, last_updated_at, data_cutoff_at, status)
- Run tutarliligi (ayni sayfada run_id karismaz)
- Yonetici kimlik dogrulama + musteri hata maskesi + OpenAPI semasi

## 2. Dosya Yapisi
```
app/
  api/
    __init__.py
    envelope.py       # ApiEnvelope: zorunlu zarf alanlari + ReportVersion
    router.py         # ApiRouter: yol eslestirme + method kontrolu + 404/405
    customer.py       # 10 musteri ucu handler'i
    admin.py          # yonetici uclari handler'i
    auth.py           # AdminAuth: X-Admin-Token dogrulama
    filters.py        # 12 parametre parser + dogrulama + sayfalama/siralama motoru
    masking.py        # musteri hata maskesi + publishability filtresi
    openapi.py        # OpenAPI 3.0 sema uretici (JSON dict)
tests/blok16/
    __init__.py
    test_api.py       # TAM 100 test
```

## 3. Zarf (envelope.py)
- Her cevap zorunlu alanlar: scan_run_id, report_version (int, artan), last_updated_at (ISO),
  data_cutoff_at (ISO, 09:40 kesim), status (OK|PARTIAL|FAILED|STALE)
- `build_envelope(run_record, data, status)` — run_record'tan zarf; data_run_id != envelope run_id ise
  RUN_MISMATCH hatasi (karistirma engeli)
- `list_envelope(run_record, items, page_meta)` — liste cevaplari icin (items + pagination)

## 4. Router (router.py)
- `ApiRouter()`: `register(method, pattern, handler, scope)` — path param: /api/stocks/{symbol}
- `dispatch(request) -> Response(status, body)` — method/path eslesmezse 404/405 JSON
- Request: method, path, query (dict), headers (dict), body (dict|None) — soket yok
- Cevap her zaman JSON + content_type isareti

## 5. Musteri Uclari (customer.py) — TAM 10
1. GET /api/stocks/universe/xk100 — aktif evren listesi
2. GET /api/stocks/{symbol} — hisse ozeti
3. GET /api/stocks/{symbol}/scan/latest — son tarama sonucu (BLOK 15 confidence dahil)
4. GET /api/stocks/{symbol}/prices — fiyat serisi (data_layer filtresi: vars. validated/clean)
5. GET /api/stocks/{symbol}/kap — KAP bildirimleri (BLOK 11)
6. GET /api/stocks/{symbol}/news — haberler (BLOK 12; dedupe canonical)
7. GET /api/stocks/{symbol}/corporate-actions — kurumsal islemler (BLOK 13)
8. GET /api/stocks/{symbol}/restrictions — tedbirler (BLOK 13)
9. GET /api/xk100/scan/latest — endeks tarama ozeti
10. GET /api/xk100/stocks — 100 hisse listesi (12 parametre destekli)
- Hepsi enjekte repository/servis uzerinden (data_source dict enjeksiyonu)
- YALNIZCA YAYINLANABILIR VERI: masking.publishable(data) filtresi — admin-only alanlar cikarilir
  (internal_notes, raw_error, debug, pending_review, admin_* onekli alanlar)
- Bilinmeyen sembol -> 404 (SYMBOL_NOT_FOUND); pasif/evren disi -> 404 (musteriye sizdirmaz)

## 6. Yonetici Uclari (admin.py)
1. GET /api/admin/stock-scans/latest — son run detayi (ham durumlar)
2. GET /api/admin/stock-scans/{run_id} — run detayi
3. POST /api/admin/stock-scans/run — manuel tarama baslat (R1/R2 kurali BLOK 14'e delege)
4. POST /api/admin/stock-scans/{symbol}/rescan — hisse yeniden tarama
5. POST /api/admin/stock-universe/sync — evren senkronu tetikle
6. GET /api/admin/symbols/{stock_id} — sembol eslestirme goruntule (BLOK 6)
7. PUT /api/admin/symbols/{stock_id} — sembol eslestirme guncelle (BLOK 6 admin servisi; audit)
- Tum admin uclari auth ZORUNLU; audit kaydi yazilir (admin_audit_log)

## 7. Kimlik Dogrulama (auth.py)
- `AdminAuth(token_provider)`:
  - header `X-Admin-Token` ZORUNLU; eksik -> 401 (ADMIN_TOKEN_MISSING)
  - yanlis -> 403 (ADMIN_TOKEN_INVALID); hata govdesi musteri maskesiyle degil admin formatiyla ama
    token degeri ASLA yanitta yer almaz
  - token_provider enjekte (env'den okunur, kod icinde sabit token YOK)
  - musteri uclarinda auth YOK ama yayinlanabilirlik filtresi VAR

## 8. Filtreler (filters.py)
- 12 parametre: page (>=1), page_size (1-200, vars. 50), search (sembol/unvan icinde, kelime siniri),
  sector, scan_status (ScanState degerleri), minimum_confidence (0-100),
  has_kap / has_news / has_action / has_restriction (true/false),
  sort_by (symbol|confidence|scan_status|sector|last_updated), sort_direction (asc|desc)
- Gecersiz parametre -> 400 (INVALID_PARAMETER + alan adi; ham exception mesaji YOK)
- `apply_filters(items, params) -> (page_items, pagination{page, page_size, total, total_pages})`
- Run tutarliligi: liste TEK run_id'den gelir; farkli run'lu kayit gelirse en son run'a hizalanir
  ya da RUN_MISMATCH (config: strict)

## 9. Hata Maskesi (masking.py)
- Musteri API: bilinmeyen hata -> 500 {"error": "INTERNAL_ERROR"} + error_id (log ile eslestirilir);
  stack trace, dosya yolu, SQL, kaynak URL, exception mesaji ASLA musteriye gitmez
- Bilinen hata kodlari (SYMBOL_NOT_FOUND, INVALID_PARAMETER vb.) kontrollu mesajla doner
- Admin API: hata detayi doner ama token/secret degerler maskelenir (*** )
- `mask_exception(exc, scope)` + `error_id` uretimi (deterministik sayac veya uuid4 — test icin enjekte)

## 10. OpenAPI (openapi.py)
- `build_openapi() -> dict` — OpenAPI 3.0.3: info, servers (VPS placeholder), paths (10 musteri + 7 admin),
  components.schemas (ApiEnvelope, StockSummary, ScanResult, PriceBar, KapNotification,
  NewsItem, CorporateAction, Restriction, Pagination, Error), securitySchemes (AdminToken header)
- Her path: method, parameters, responses (200/400/401/403/404/500), zarf $ref
- Semaya musteri disi kaynak baglantisi (yfinance/KAP dogrudan URL) EKLENMEZ — mimari kural notu

## 11. Frontend Kurali (router/openapi notu)
- Mimari kural: frontend YALNIZCA bu API'yi kullanir; dogrudan yfinance/KAP/TradingView/haber/DB
  baglantisi YASAK — openapi info.description + modul docstring'inde sabit; musteri handler'larinda
  dis kaynak importu YOK (testle kanitlanir)

## 12. Testler (tests/blok16/test_api.py) — TAM 100 test
Kategoriler:
1. Yetkilendirme: token eksik 401, yanlis 403, dogru 200, token sizintisi yok, musteri ucunda auth yok (~14)
2. Sayfalama: page/page_size sinirlari, total_pages, bos sayfa (~12)
3. Filtreleme: search/sector/scan_status/minimum_confidence/has_* kombinasyonlari (~16)
4. Siralama: sort_by/direction, gecersiz deger 400 (~10)
5. Run_id tutarliligi: zarf zorunlu alanlari, karisik run reddi, report_version artisi (~14)
6. Hata maskesi: 500 INTERNAL_ERROR + error_id, stack/SQL/yol sizintisi yok, admin maske (~14)
7. Uclar: 10 musteri + 7 admin ucu dogru yol/method/404/405 (~12)
8. OpenAPI + yayinlanabilirlik + frontend kurali (~8)
Toplam = 100; `pytest tests/blok16 -v`

## 13. Kisitlar
- Sadece BLOK 16 dosyalari; BLOK 6-15'e DOKUNULMAZ (entegrasyonlar enjeksiyonla)
- stdlib only; gercek soket YOK (handler duzeyi test); deterministik; saat enjekte
- Musteri API'de ham hata ve admin-only alan YOK — testle kanitlanmali
