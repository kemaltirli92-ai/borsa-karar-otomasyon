# SPEC — BLOK 6: Sirket Kimligi ve Sembol Eslestirme Modulu

Proje: borsa-karar-otomasyon (VPS uzerinde Python servis)
Bolum 3: Hisse Taramasi — BLOK 6
Onceki durum: Bolum 1-2 (268 test) + BLOK 5 (100 test) tamam.

## 1. Amaç
Tüm sistemde tek bir merkezi `stock_id` kimliği kullanılacak. Her hisse için
farklı platformlardaki (bist, yahoo, google, tradingview, kap) sembol karşılıkları
tutulacak, eşleştirme güvenli yapılacak, kod değişiklikleri geçmişiyle saklanacak,
KAP bağlantıları periyodik doğrulanacak, yönetici panelinden sembol düzenleme
yapılabilecek ve doğrulanamayan kayıtlar `SYMBOL_VERIFICATION_PENDING` kuyruğuna
düşecek.

## 2. Dosya Yapısı (repo mimarisi ile uyumlu)
```
app/
  models/
    __init__.py
    stock_identity.py          # Veri modeli (tablo şemaları)
  services/
    __init__.py
    stock_scanning/
      __init__.py
      symbol_identity.py       # Ana servis: kayıt, eşleştirme, geçmiş
      kap_verifier.py          # KAP link doğrulama (periyodik)
      identity_adapter.py      # BLOK 5 (evren modülü) entegrasyon adaptörü
  admin/
    __init__.py
    symbol_admin.py            # Yönetici paneli sembol düzenleme + audit log
tests/
  __init__.py
  blok6/
    __init__.py
    test_symbol_identity.py    # TAM 100 test
```

## 3. Veri Modeli (app/models/stock_identity.py)
Dataclass tabanlı, veritabanı bağımsız (repository deseni; ileride SQLAlchemy'ye taşınabilir).

- `StockIdentity`: stock_id (str, "STK-000001" formatı, benzersiz), company_name, isin (ops.), created_at, status
- `SymbolRecord`: stock_id, platform (bist|yahoo|google|tradingview|kap), symbol, valid_from, valid_to (None=açık), is_active
- `KapLink`: stock_id, url, status (KAP_LINK_VALID|KAP_LINK_BROKEN|KAP_LINK_UNCHECKED), last_checked_at, fail_count
- `SymbolAuditEntry`: audit_id, stock_id, action, platform, old_symbol, new_symbol, admin_user, timestamp, reason
- `VerificationQueueItem`: stock_id, reason (SYMBOL_VERIFICATION_PENDING vb.), created_at, resolved, resolved_by, resolved_at
- `VerificationStatus` enum: VERIFIED, SYMBOL_VERIFICATION_PENDING, REJECTED, DUPLICATE_SYMBOL

## 4. Servis: SymbolIdentityService (app/services/stock_scanning/symbol_identity.py)
- `register_stock(company_name, isin=None) -> stock_id` — aynı isim+ISIN tekrar kaydedilemez
- `add_symbol(stock_id, platform, symbol, valid_from=None)` — aktif sembol ekle; aynı platformda açık sembol varsa çakışma hatası
- `change_symbol(stock_id, platform, new_symbol, effective_date)` — ESKİ SEMBOL SİLİNMEZ: eskinin valid_to'su kapanır, yenisi açılır, audit yazılır
- `resolve(query, platform=None, on_date=None)` — sembol/şirket adından stock_id çözümle
- `resolve_old_code(old_symbol, platform)` — geçmiş (kapanmış) sembolle bile stock_id bulur, sonucu `historical=True` ile işaretler
- `get_active_symbol(stock_id, platform)` — aktif sembol
- `get_symbol_history(stock_id, platform=None)` — tüm geçmiş kayıtlar
- Kelime-içi yanlış eşleşme engelleme kuralları:
  * Eşleştirme her zaman TAM TOKEN bazında (word-boundary); kısa kod ("IS", "TK", "A") hiçbir zaman daha uzun bir kelimenin/sembolün içinde yakalanamaz ("ISCTR" içinde "IS" eşleşmez)
  * Case-insensitive normalize; Türkçe karakter normalize (İ/I, ı/i, Ş, Ç, Ğ, Ö, Ü)
  * Sembol eşleşmesi platform bazında birebir; şirket adı eşleşmesi normalize + token eşitliği (substring değil)
- Çift eşleştirme: aynı platform+sembol iki farklı stock_id'ye bağlanırsa `DUPLICATE_SYMBOL` hatası; resolve iki aday bulursa sonuç döndürmez, `SYMBOL_VERIFICATION_PENDING` kuyruğuna atar
- Doğrulanamayan kayıt: `mark_pending(stock_id, reason)` -> kuyruğa ekler, status = SYMBOL_VERIFICATION_PENDING

## 5. KAP Doğrulama (kap_verifier.py)
- `KapVerifier(http_client)` — http_client enjekte edilir (testte mock)
- `verify(stock_id) -> status` — KAP linkine HEAD/GET; 200 => KAP_LINK_VALID, 404/timeout => KAP_LINK_BROKEN
- Bozuk linkte fail_count artar; 3 ard arda başarısızlıkta SYMBOL_VERIFICATION_PENDING kuyruğuna
- `run_periodic_check()` — tüm açık KAP linklerini doğrular, sonuçları günceller
- http_client yoksa gerçek ağ çağrısı YAPILMAZ, KAP_LINK_UNCHECKED döner

## 6. Yönetici Paneli (admin/symbol_admin.py)
- `admin_update_symbol(admin_user, stock_id, platform, new_symbol, reason)` — validasyon + değişiklik + audit
- `admin_merge_duplicate(admin_user, keep_id, drop_id)` — çift kayıt birleştirme, audit ile
- `admin_resolve_pending(admin_user, queue_id, approve, note)` — bekleyen kayıt onay/red
- `get_audit_log(stock_id=None)` — audit kayıtları
- Tüm yönetici işlemleri audit log'a yazılır; admin_user boş olamaz

## 7. Entegrasyon Adaptörü (identity_adapter.py)
- BLOK 5 evren modülünün çağıracağı arayüz:
  `resolve_universe_symbols(symbols: list[str]) -> dict[str, str|None]` — her sembol için stock_id (bulunamazsa None + pending kuyruğu)
- Çıktı sözlüğü + pending listesi

## 8. Testler (tests/blok6/test_symbol_identity.py) — TAM 100 test, pytest
Kategoriler:
1. Doğru sembol eşleştirme (bist/yahoo/google/tradingview/kap) — ~20 test
2. Yanlış şirkete eşleşmeme (benzer isimler) — ~12 test
3. Kısa kod kelime-içi yanlış eşleşme engelleme — ~14 test
4. Kod değişikliği / eski kod geçmişi (valid_from-valid_to) — ~16 test
5. KAP kimliği + link doğrulama (mock http) — ~14 test
6. Çift eşleştirme (duplicate) senaryoları — ~12 test
7. Bozuk link + SYMBOL_VERIFICATION_PENDING kuyruğu — ~12 test
Toplam = 100 test, hepsi geçmeli. `pytest tests/blok6 -v` çalıştırılıp sonuç raporlanacak.

## 9. Kısıtlar
- Sadece BLOK 6 dosyaları oluşturulacak, başka modüle dokunulmayacak
- Türkçe karakterler kodda kullanılabilir ama dosya/identifer adları ASCII
- Hiçbir test gerçek internete erişmeyecek (http_client mock)
- Deterministik: aynı girdi -> aynı stock_id (counter tabanlı)
