# SPEC — BLOK 7: Veri Tabani ve Migration Modulu

Proje: borsa-karar-otomasyon (VPS uzerinde Python servis, SQLite + stdlib sqlite3)
Bolum 3: Hisse Taramasi — BLOK 7
Onceki durum: Bolum 1-2 (268 test) + BLOK 5 (100 test) + BLOK 6 (100 test) tamam.
Konvansiyon: dis bagimlilik YOK (stdlib sqlite3, os, json, hashlib, shutil, datetime); dosya/identifier ASCII; Turkce docstring.

## 1. Amac
Bolum 3 (Hisse Taramasi) veri katmaninin kalici temelini kurmak:
- 11 tablo semasi
- benzersizlik kisitlari (UNIQUE)
- ham/temiz/dogrulanmis verinin ayrilmasi
- surumlu migration sistemi (ileri + geri alma)
- bos DB'de test
- mevcut veri icin yedek + kayip kontrolu

## 2. Dosya Yapisi
```
app/
  services/
    stock_scanning/
      db/
        __init__.py
        migrations/
          0001_initial.sql          # ileri: 11 tablo + indexler
          0001_initial.down.sql     # geri alma
          0002_data_layers.sql      # ileri: ham/temiz/dogrulanmis katman tablolari
          0002_data_layers.down.sql # geri alma
        migrator.py      # MigrationRunner: apply, rollback, status, pending listesi
        backup.py        # yedek + kayip kontrolu
        repo.py          # ince repository katmani (insert/select yardimcilari)
tests/
  blok7/
    __init__.py
    test_db_migration.py  # TAM 100 test
```

## 3. Migration Sistemi (migrator.py)
- `migrations/` klasorundeki dosyalar NNNN_ad.sql (up) ve NNNN_ad.down.sql (down) formatinda
- `schema_migrations` tablosu: version (PRIMARY KEY), name, checksum (SHA-256), applied_at
- `MigrationRunner(db_path)`:
  - `status()` -> uygulanmis/ bekleyen surumler
  - `apply_all()` / `apply_next()` — her migration TEK transaction icinde; hata olursa ROLLBACK, yarim kayit kalmaz
  - `rollback(steps=1)` — son N migration'u .down.sql ile geri al; checksum uyusmazsa geri almayi REDDET (semaya disaridan mudahale tespiti)
  - Ayni migration ikinci kez uygulanamaz (idempotent: zaten uygulandıysa atlar)
  - Uygulanmis migration dosyasinin checksum'i degistiyse uyari/hata
- Migration dosyasi eksik/ bozuk (up var down yok) ise kesin hata

## 4. Tablo Semasi (0001_initial.sql) — 11 tablo
SQLite. Timestamps ISO-8601 TEXT. FOREIGN KEY + CHECK kisitlari aktif (PRAGMA foreign_keys=ON baglantida zorunlu).

1. **stock_universe** — universe_id TEXT PK, name TEXT NOT NULL, source_url TEXT, is_active INTEGER CHECK(0,1), effective_from TEXT, effective_to TEXT, created_at TEXT
2. **stock_universe_memberships** — id INTEGER PK, universe_id FK, stock_id TEXT NOT NULL, member_from TEXT NOT NULL, member_to TEXT (NULL=aktif), is_active INTEGER CHECK(0,1); UNIQUE(universe_id, stock_id, member_from)
3. **stock_symbol_mappings** — id INTEGER PK, stock_id TEXT NOT NULL, platform TEXT CHECK(platform IN ('bist','yahoo','google','tradingview','kap')), symbol TEXT NOT NULL, valid_from TEXT NOT NULL, valid_to TEXT, is_active INTEGER CHECK(0,1); UNIQUE(platform, symbol, valid_from); aktif (valid_to NULL) kayit icin ayrica UNIQUE INDEX: ayni (platform, symbol) cift aktif olamaz (partial index WHERE valid_to IS NULL)
4. **stock_scan_runs** — run_id TEXT PK (BENZERSIZ), run_date TEXT NOT NULL, status TEXT CHECK(status IN ('WAITING','RUNNING','COMPLETED','FAILED','PARTIAL')), started_at, completed_at, total_stocks INTEGER, error_count INTEGER, config_version TEXT
5. **stock_scan_results** — id INTEGER PK, run_id FK NOT NULL, stock_id TEXT NOT NULL, result_status TEXT CHECK('OK','MISSING_DATA','FAILED','PENDING'), data_quality_score REAL CHECK(0..1 veya NULL), payload_json TEXT; UNIQUE(run_id, stock_id) (BENZERSIZ)
6. **stock_prices_daily** — id INTEGER PK, stock_id TEXT NOT NULL, trade_date TEXT NOT NULL, source TEXT NOT NULL, data_version TEXT NOT NULL, open/high/low/close REAL, volume INTEGER, data_layer TEXT CHECK('raw','clean','validated') NOT NULL; UNIQUE(stock_id, trade_date, source, data_version) (BENZERSIZ)
7. **stock_corporate_actions** — id INTEGER PK, stock_id TEXT NOT NULL, action_type TEXT CHECK('dividend','bonus','split','capital_increase','rights','other'), announcement_date TEXT, effective_date TEXT, ratio TEXT, kap_notice_no TEXT, source TEXT, data_layer TEXT CHECK('raw','clean','validated'), UNIQUE(kap_notice_no) — KAP bildirim numarasi BENZERSIZ (NULL'lar SQLite'ta cakismaz, ama app katmaninda NULL olmayan no tekrarlanamaz)
8. **stock_trading_restrictions** — id INTEGER PK, stock_id TEXT NOT NULL, restriction_type TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT, source TEXT, kap_notice_no TEXT UNIQUE, is_active INTEGER CHECK(0,1)
9. **stock_news_matches** — id INTEGER PK, stock_id TEXT NOT NULL, news_id TEXT NOT NULL, headline TEXT, source TEXT NOT NULL, published_at TEXT, matched_at TEXT, match_method TEXT CHECK('code','name','manual'), UNIQUE(stock_id, news_id)
10. **stock_scan_errors** — id INTEGER PK, run_id FK, stock_id TEXT, stage TEXT NOT NULL, error_type TEXT NOT NULL, message TEXT, occurred_at TEXT, resolved INTEGER CHECK(0,1) DEFAULT 0
11. **source_health** — id INTEGER PK, source_name TEXT NOT NULL, checked_at TEXT NOT NULL, status TEXT CHECK('OK','DEGRADED','DOWN','UNCHECKED'), latency_ms INTEGER, fail_count INTEGER DEFAULT 0, note TEXT; UNIQUE(source_name, checked_at)

Indexler: stock_prices_daily(stock_id, trade_date), stock_scan_results(run_id), stock_scan_errors(run_id, stage), stock_news_matches(stock_id), stock_symbol_mappings(stock_id)

## 5. Ham/Temiz/Dogrulanmis Ayrimi (0002_data_layers.sql + repo.py)
- stock_prices_daily ve stock_corporate_actions'daki `data_layer` alani ile katman ayrimi (raw → clean → validated)
- 0002'de ek: **data_layer_promotions** tablosu — id PK, table_name TEXT, record_id INTEGER, from_layer, to_layer, promoted_at, promoted_by, checksum_before, checksum_after — katman gecisleri izlenebilir
- repo.py yardimcilari: `insert_price(...)` (layer parametreli), `promote_to_clean(record_ids)`, `promote_to_validated(record_ids)` — her gecis data_layer_promotions'a kayit
- Kural: raw kayit uzerine yazilamaz; temizleme raw'i silmez; validated sadece clean'den yukseltilir (atlama yasak)

## 6. Yedek + Kayip Kontrolu (backup.py)
- `backup_db(db_path, backup_dir)` -> timestamp'li kopya (shutil) + yaninda manifest JSON: tablo adi -> satir sayisi + satir checksum toplami
- `verify_no_data_loss(original_db, restored_or_target_db)` -> tablo bazli satir sayisi karsilastirmasi; kayip varsa DataLossError + rapor (hangi tablo, kac satir eksik)
- Migration oncesi zorunlu akis yardimci fonksiyonu: `safe_migrate(runner, db_path, backup_dir)` -> yedek al → migration uygula → kayip kontrolu → kayip varsa otomatik geri al (yedekten restore + rollback)
- Varolmayan/bos DB'de backup calismaz hata VERMEZ: 0 tablo manifest'i yazar (bos DB senaryosu)

## 7. Testler (tests/blok7/test_db_migration.py) — TAM 100 test, pytest
Her test BOS gecici DB (tmp_path) uzerinde calisir; gercek dosya DB'ye dokunulmaz.
Kategoriler:
1. Migration ileri uygulama: 11 tablo olusumu, indexler, schema_migrations kaydi (~16)
2. Benzersizlik kisitlari: run_id, run_id+stock_id, stock_id+trade_date+source+data_version, kap_notice_no — cakisma testleri (~18)
3. CHECK kisitlari: platform, status, data_layer, action_type, match_method, is_active araliklari (~14)
4. Migration geri alma: rollback tek/cok adim, checksum uyusmazligi reddi, .down.sql yoksa hata, yarim transaction kalmaz (~16)
5. Ham/temiz/dogrulanmis: katman insert, promote akisi, atlama yasagi, raw silinmez, promotions kaydi (~14)
6. Yedek + kayip kontrolu: backup manifest, satir sayisi dogrulama, kayip tespiti, bos DB backup, safe_migrate senaryolari (~14)
7. Repository yardimcilari + genel uç durumlar (FK, PRAGMA, idempotency) (~8)
Toplam = 100, hepsi gecmeli: `pytest tests/blok7 -v`

## 8. Kisitlar
- Sadece BLOK 7 dosyalari; BLOK 6 ve diger modullere DOKUNULMAZ
- stdlib disinda paket yok
- Deterministik; saat enjekte edilebilir
- Hicbir test ag erisimi yapmaz
