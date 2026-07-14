# SPEC — BLOK 13: Kurumsal Islemler ve Aktif Tedbirler

Proje: borsa-karar-otomasyon (VPS uzerinde Python servis, stdlib)
Bolum 3: Hisse Taramasi — BLOK 13
Onceki durum: Bolum 1-2 (268) + BLOK 5-12 (8x100) tamam. Toplam test havuzu: 700 (blok6-12).
Konvansiyon: stdlib only, ASCII identifier, Turkce docstring, gercek ag YASAK, saat enjekte.

## 1. Amac
Kurumsal islem ve aktif tedbir kayitlarinin merkezi, surumlu ve kopyasiz yonetimi:
- 11 kurumsal islem tipi, 11 alanli kayit
- 7 tedbir tipi, 7 alanli kayit
- Islem durdurmadaki sirket korunur ama scoring_ready=false
- Ham + dogrulanmis olay verisi sonraki modullere aktarilir
- Bu modulde olumlu/olumsuz PUAN URETME YOK (kapsam kilidi)

## 2. Dosya Yapisi
```
app/services/stock_scanning/
  corporate_actions/
    __init__.py
    models.py       # ActionType (11), CorporateActionRecord (11 alan), RestrictionType (7),
                    # TradingRestriction (7 alan), ActionStatus, FeedPacket
    registry.py     # CorporateActionRegistry: kayit, dedupe, surum zinciri (data_version), gecmis koruma
    restrictions.py # RestrictionRegistry: tedbir kaydi, is_active hesaplama, sure bitisi
    suspension.py   # SuspensionPolicy: islem durdurmadaki sirket davranis kurallari
    feed.py         # CorporateFeed: sonraki modullere ham/dogrulanmis paket aktarimi
    collector.py    # CorporateCollector: kaynaklardan (enjekte) toplama zinciri
tests/blok13/
    __init__.py
    test_corporate_actions.py  # TAM 100 test
```

## 3. Veri Modeli (models.py)
`ActionType` enum (11): DIVIDEND (temettu), BONUS_ISSUE (bedelsiz), RIGHTS_ISSUE (bedelli),
STOCK_SPLIT (hisse bolunmesi), MERGER (birlesme), DEMERGER (bolunme),
BUYBACK_PROGRAM (geri alim programi), BUYBACK_EXECUTION (gerceklesen geri alim),
SHARE_SALE (pay satisi), OWNERSHIP_CHANGE (ortaklik yapisi degisikligi), SYMBOL_CHANGE (kod degisikligi)

`CorporateActionRecord` dataclass — TAM 11 alan:
stock_id, action_type, announcement_date, effective_date, ratio (str|None, "2:1"/"0.35"),
amount (float|None), currency (str|None), source, official_url, status (ActionStatus), data_version
(Not: kap_notice_no BLOK 7/9 ile uyum icin AYRI zorunlu olmayan baglam alani olarak registry'de tutulur — 11 alan birebir korunur)

`ActionStatus` enum: ANNOUNCED, EFFECTIVE, COMPLETED, CANCELLED, SUPERSEDED
`RestrictionType` enum (7): TRADING_HALT (islem durdurma), GROSS_SETTLEMENT (brut takas),
ORDER_PACKAGE (emir paketi), SINGLE_PRICE (tek fiyat), MARGIN_TRADING_BAN (kredili islem yasagi),
SHORT_SELLING_BAN (aciga satis yasagi), MARKET_CHANGE (pazar degisikligi)

`TradingRestriction` dataclass — TAM 7 alan:
restriction_type, start_date, end_date, is_active, source, official_url, collected_at
(registry icinde stock_id baglami ile tutulur)

`FeedPacket`: stock_id, actions_raw (list), actions_validated (list), restrictions_active (list),
restrictions_history (list), scoring_ready (bool), suspension_flag (bool), packet_version

## 4. Registry (registry.py)
- `CorporateActionRegistry(clock=None)`:
  - `register(record, kap_notice_no=None) -> RegistryResult(stored|duplicate|revision_chain)`
  - DEDUPE: ayni (stock_id, action_type, effective_date, kap_notice_no) ikinci kez EKLENMEZ (duplicate++)
  - SURUM: ayni olay icin duzeltilmis kayit -> eski SUPERSEDED, yeni kayit yeni data_version ile
    (action-v1, action-v2...); eski surum SILINMEZ, get_history ile okunur
  - ANNOUNCED -> EFFECTIVE -> COMPLETED durum gecisleri; gecersiz gecis reddedilir (COMPLETED->ANNOUNCED yok)
  - CANCELLED: iptal kaydi ayri tutulur, hedef korunur
  - SYMBOL_CHANGE: BLOK 6 sembol gecmisiyle uyumlu not (eski kod silinmez ilkesine atif; baglanti enjekte)
  - `get_actions(stock_id, status=None)`, `get_history(stock_id, action_key)`

## 5. Restrictions (restrictions.py)
- `RestrictionRegistry(clock=None)`:
  - `register(stock_id, restriction) -> stored|duplicate`
  - DEDUPE: ayni (stock_id, restriction_type, start_date) tekrari reddedilir
  - `is_active` OTOMATIK: start_date <= today <= end_date (end_date None -> acik uclu aktif);
    saat enjekte; kayitla gelen is_active bayragi ile hesaplanan uyusmazsa REVIEW_REQUIRED isareti
  - SURESI BITEN TEDBIR: end_date < today -> is_active=False (otomatik gecis), kayit KORUNUR (arsiv)
  - `active_restrictions(stock_id)`, `restriction_history(stock_id)`
  - MARKET_CHANGE icin hedef pazar bilgisi source/official_url ile izlenir (ayri alan yok — 7 alan korunur)

## 6. SuspensionPolicy (suspension.py)
- `SuspensionPolicy(restriction_registry)`:
  - `scan_status(stock_id) -> ScanStatus(keep_in_scan=True, scoring_ready, show_as_normal, reason)`
  - AKTIF TRADING_HALT varsa:
    * taramadan SILINMEZ (keep_in_scan=True her zaman)
    * gecmis grafik verisi KORUNUR (history_protected=True bayragi)
    * normal hisse gibi GOSTERILMEZ (show_as_normal=False)
    * scoring_ready=False
  - TRADING_HALT bittiginde scoring_ready tekrar True (diger tedbirler tek basina scoring_ready'yi kapatmaz;
    GROSS_SETTLEMENT/SHORT_SELLING_BAN vb. sadece risk notu olarak pakete yazilir)
- ScanStatus alanlari: keep_in_scan, history_protected, show_as_normal, scoring_ready, active_halts, notes

## 7. Feed (feed.py)
- `CorporateFeed(action_registry, restriction_registry, suspension_policy)`:
  - `build_packet(stock_id, validated_ids=None) -> FeedPacket`
    * actions_raw: ham kayitlar (tum status)
    * actions_validated: dogrulanmis (EFFECTIVE/COMPLETED; validated_ids ile isaretlenenler)
    * restrictions_active + restrictions_history
    * scoring_ready + suspension_flag (SuspensionPolicy'den)
  - Paket DEGISMEZ (frozen kopya dondurulur — eski rapor verisi sessizce degismez ilkesi)
  - `packet_version` her uretimde artar

## 8. Collector (collector.py)
- `CorporateCollector(action_source=None, restriction_source=None, action_registry, restriction_registry, clock=None)`:
  - kaynaklar enjekte (KAP/BIST uclari ileride); kaynak yok/hata -> SOURCE_UNAVAILABLE,
    tarama DURMAZ, eksik hisseler icin bos paket
  - `collect(stock_ids) -> CollectionReport(collected, deduped, errors, source_status)`
  - PUAN KILIDI: sentiment/score/impact alani veya fonksiyonu YOK

## 9. Testler (tests/blok13/test_corporate_actions.py) — TAM 100 test
Kategoriler:
1. Kurumsal islem kaydi: 11 tip, 11 alan dogrulama, durum gecisleri (~16)
2. Kurumsal islem surumu: duzeltilmis kayit, SUPERSEDED zinciri, eski surum korunur, data_version artisi (~14)
3. Cift kayit engeli: kurumsal + tedbir dedupe (~12)
4. Aktif tedbir: 7 tip kayit, is_active hesaplama, bayrak uyusmazligi (~14)
5. Suresi biten tedbir: otomatik pasif, arsiv korunur (~10)
6. Islem durdurma: taramadan silinmez, grafik korunur, normal gosterilmez, scoring_ready=False, bitince True (~16)
7. Paket aktarimi: ham/dogrulanmis ayrimi, frozen paket, packet_version (~10)
8. Collector: kaynak hatasi taramayi durdurmaz + puan kilidi (~8)
Toplam = 100; `pytest tests/blok13 -v`

## 10. Kisitlar
- Sadece BLOK 13 dosyalari; BLOK 6-12'ye DOKUNULMAZ (entegrasyonlar enjeksiyonla)
- stdlib only; deterministik; saat enjekte; gercek ag YOK
- Puan uretme YOK — kapsam kilidi testle kanitlanmali
