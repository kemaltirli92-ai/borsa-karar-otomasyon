# SPEC — BLOK 11: KAP Bildirim Toplama Modulu

Proje: borsa-karar-otomasyon (VPS uzerinde Python servis, stdlib)
Bolum 3: Hisse Taramasi — BLOK 11
Onceki durum: Bolum 1-2 (268) + BLOK 5-10 (6x100) tamam. Toplam test havuzu: 500 (blok6-10).
Konvansiyon: stdlib only, ASCII identifier, Turkce docstring, gercek ag YASAK (fetcher enjekte), saat enjekte.

## 1. Amac
Merkezi KAP bildirim akisindan XK100 sirketlerine ait bildirimleri toplayan modul:
- Her sabah 100 sirketin 200 profil/bildirim linkini TEK TEK ACMA YASAK — merkezi akis taranir
- 6 adimli toplama zinciri
- 17 alanli standart KAP kaydi; notification_id benzersiz
- Revizyon eski kaydin UZERINE YAZILMAZ, yeni surum
- KAP kesintisi fiyat taramasini DURDURMAZ (PARTIAL)
- Kritik bildirim tam metni alinamazsa hisse FAVORI SURECINE HAZIR SAYILMAZ
- Bu modulde bildirim puani (olumlu/olumsuz) HESAPLANMAZ — kapsam kilidi

## 2. Dosya Yapisi
```
app/services/stock_scanning/
  kap_collection/
    __init__.py
    models.py         # KapNotification (17 alan), RevisionStatus, KapRunStatus, AttachmentMeta
    feed.py           # Merkezi akis kaynagi (fetcher enjekte): son kesimden sonraki bildirimler
    matcher.py        # bildirim -> aktif XK100 sirketi eslestirme (BLOK 6 kimlik servisi enjekte)
    collector.py      # KapCollector: 6 adimli zincir, dedupe, revizyon/iptal, profil haftalik kontrol
    storage.py        # KapStorage: notification_id unique, surum zinciri (previous_notification_id)
    readiness.py      # FAVORI HAZIRLIK KILIDI: kritik bildirim tam metni yoksa hazir degil
tests/blok11/
    __init__.py
    test_kap_collection.py  # TAM 100 test
```

## 3. Veri Modeli (models.py)
`KapNotification` dataclass — 17 alan (hepsi SPEC'te zorunlu):
1. notification_id (str, benzersiz) 2. stock_id 3. symbol 4. title
5. notification_type (or. FR finansal rapor, ODA ozel durum, DG diger — serbest str)
6. subtype 7. published_at 8. source_timestamp 9. body (tam metin; None olabilir)
10. summary_raw 11. amount (float|None) 12. currency 13. official_url
14. attachment_urls (list[str]) 15. revision_status (RevisionStatus)
16. previous_notification_id (str|None) 17. collected_at

`RevisionStatus` enum: ORIGINAL, REVISED, CANCELLED, SUPERSEDED
- REVISED: duzeltilmis bildirim — eski kayit SUPERSEDED isaretlenir, yenisi REVISED + previous_notification_id
- CANCELLED: iptal bildirimi — eski kayit silinmez, iptal kaydi ayrica tutulur + hedef previous_notification_id
`AttachmentMeta`: url, file_name, file_type, size_bytes, fetched (bool), fetched_at
`KapRunStatus` enum: COMPLETED, PARTIAL, FAILED
`KapCollectionResult`: run_id, status, fetched_count, matched_count, stored_count,
skipped_duplicates, revisions, cancellations, errors (list), kap_health (OK|DEGRADED|DOWN)

## 4. Merkezi Akis (feed.py)
- `KapFeed(fetcher, clock=None)`:
  - `fetch_since(cutoff_iso) -> list[dict]` — son veri kesiminden sonraki MERKEZI bildirim listesi
  - `fetch_detail(notification_id) -> dict|None` — eslesen bildirimin detayi (body, ekler)
  - fetcher None/hata -> KapFeedUnavailableError
- KONTROLSUZ TEKRAR ACMA YASAGI: ayni calisma icinde ayni notification_id icin detay
  tek kez cekilir (calisma ici onbellek); sirket PROFIL linkleri bu akista ACILMAZ
- Profil kontrolu: `ProfileChecker(checker_fetcher, clock)` — haftalik (7 gun) kontrol;
  son kontrol 7 gunden yeniyse ATLA (PROFILES_SKIPPED_FRESH); sadece haftalik pencerede cekilir

## 5. Eslestirme (matcher.py)
- `KapMatcher(identity_service, universe_provider)`:
  - bildirimdeki sirket adi/sembolu -> stock_id (BLOK 6 resolve; enjekte)
  - AKTIF XK100 disi sirket -> eslesme yok (OUT_OF_UNIVERSE, kayit yapilmaz)
  - YANLIS SIRKET ESLESMESI ENGELI: belirsiz/iki aday -> eslesme YAPILMAZ,
    MATCH_AMBIGUOUS + SYMBOL_VERIFICATION_PENDING (BLOK 6 kuyrugu) — yanlis hisseye baglanmaz
  - Eslestirilemeyen bildirim: UNMATCHED sayacina (sessizce hisseye baglanmaz)

## 6. Collector (collector.py)
- `KapCollector(feed, matcher, storage, profile_checker=None, logger=None, clock=None)`
- `collect(cutoff_iso) -> KapCollectionResult` — 6 adim:
  1) fetch_since(cutoff) — merkezi akis
  2) matcher ile aktif XK100 eslestirme
  3) eslesen bildirimin detayini ac (fetch_detail, calisma ici tek kez)
  4) ek dosya meta bilgisini kaydet (AttachmentMeta; dosya INDIRILMEZ, sadece meta)
  5) revizyon/iptal kontrolu (revision alanlari): REVISED/CANCELLED zinciri
  6) stock_id ile bagla + storage'a yaz
- Dedupe: ayni notification_id ikinci kez EKLENMEZ (storage unique; skipped_duplicates++)
- Revizyon: eski kaydin uzerine YAZILMAZ — eski SUPERSEDED, yeni kayit REVISED + previous_notification_id
- Iptal: CANCELLED kaydi olusur, hedef kayit korunur
- KAP KESINTISI: feed hata verirse -> status=PARTIAL (veya FAILED hic veri yoksa), kap_health=DOWN,
  HATA fiyat taramasina YAYILMAZ (exception disari firlatilmaz; sonuc nesnesinde tasim)
- KISMET: detay cekilemeyen kritik bildirim -> body=None + DETAIL_MISSING isareti
- PUAN KILIDI: modulde olumlu/olumsuz puan/etki HESAPLAMA YOK (fonksiyon yok; sentiment alani YOK)

## 7. Storage (storage.py)
- `KapStorage(conn=None, clock=None)` — BLOK 7 stock_news_matches ile uyumlu ama AYRI tablo:
  kap_notifications tablosu (conn verilirse BLOK 7 migrator ile olusturulmus DB'ye eklenir;
  conn=None bellek ici). Alanlar models ile ayni + version_no + superseded_by
- `insert(notification) -> StoredResult(inserted|duplicate|revision_chain)`
- `mark_superseded(old_id, new_id)`, `get_history(notification_id) -> list` (surum zinciri)
- `get_by_stock(stock_id, since=None)`
- notification_id UNIQUE; ayni no ikinci kez -> duplicate (yazilmaz)

## 8. Favori Hazirlik Kilidi (readiness.py)
- `FavoriteReadiness(storage, critical_types=None)`:
  critical_types varsayilan: {"FR","ODA","MSL"} (finansal rapor, ozel durum, maddi olay)
- `is_ready_for_favorite(stock_id) -> ReadinessVerdict(ready, blocking: list)`
  * Son kesimden beri kritik bildirim var VE body is None (tam metin alinamamis) -> ready=False
    (FAVORI_READY_BLOCKED / CRITICAL_BODY_MISSING)
  * KAP son calisma PARTIAL/FAILED iken kritik bildirim var -> ready=False (KAP_PARTIAL_BLOCK)
  * Aksi halde ready=True
- Bu modul favori SECIMI yapmaz; sadece hazirlik durumunu bildirir

## 9. Testler (tests/blok11/test_kap_collection.py) — TAM 100 test
Kategoriler:
1. Merkezi akis toplama: 6 adim zinciri, kesimden sonrasi, detay tek-cekim onbellegi (~16)
2. Tekrarlanan bildirim: ayni notification_id ikinci kez eklenmez (~12)
3. Revizyon: eski uzerine yazilmaz, SUPERSEDED+REVISED zinciri, previous_notification_id (~14)
4. Iptal: CANCELLED kaydi, hedef korunur (~10)
5. Yanlis sirket eslesmesi: belirsiz eslesme yapilmaz, evren disi reddedilir, pending kuyrugu (~14)
6. KAP kesintisi: PARTIAL, fiyat taramasi durmaz (exception sizmaz), kap_health DOWN (~12)
7. Ek dosya: meta kaydi, dosya indirilmez, coklu ek (~10)
8. Profil haftalik kontrol + favori hazirlik kilidi (kritik body eksik -> hazir degil) + puan kilidi (~12)
Toplam = 100; `pytest tests/blok11 -v`

## 10. Kisitlar
- Sadece BLOK 11 dosyalari; BLOK 6-10'a DOKUNULMAZ (entegrasyonlar enjeksiyonla)
- stdlib only; deterministik; saat enjekte; gercek ag YOK (fetcher mock)
- Puan/sentiment hesaplama YOK — kapsam kilidi testle kanitlanmali
