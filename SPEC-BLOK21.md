# SPEC-BLOK21 — Guvenlik, Log, Izleme ve Yedekleme

Repo: `/mnt/agents/output/borsa-karar-otomasyon` (mevcut proje; BLOK 6-20 tamam, 1400 test geciyor)

## GENEL KURALLAR (KESIN)
- Python 3.12, **yalnizca stdlib** (os, json, re, shutil, hashlib, sqlite3, dataclasses, enum, datetime, pathlib, typing, threading, secrets, string). Testlerde pytest kullanilabilir.
- **Deterministik**: her zaman/saat/disk/istatistik ihtiyaci ENJEKTE edilir (`clock=lambda: datetime(...)`, `stat_provider=...`). Modulde dogrudan `datetime.now()` / `time.time()` cagrisi olmaz; default clock parametresi kullanilir.
- **Gercek ag / subprocess YOK**: pg_dump gibi dis araclar enjekte `dump_fn` ile soyutlanir; testlerde sahte fonksiyon.
- Turkce alan adlari; ASCII tanimlayicilar (snake_case, Turkce karakter yok: `kaynak` degil `kaynak`... ornek: `son_basari_at`, `art_arda_hata`).
- **MEVCUT DOSYALARA DOKUNULMAZ.** Yalnizca: yeni `app/ops/` paketi, `tests/blok21/`, `systemd/xk100-backup.service` + `systemd/xk100-backup.timer` (yeni), `.env.example`a EK (dosyanin sonuna yeni bolum, mevcut satirlar silinmez/degismez).
- Puan kilidi suruyor: bu modul hisse puani/sinyal URETMEZ. Bildirim kilidi suruyor: musteriye bildirim/push/telegram YOK (yonetici uyarisi = dahili kayit listesi, dis kanal gonderimi degil).
- Tum testler repo kokunden `python -m pytest tests/blok21 -q` ile gecmeli: **TAM 100 test, 100/100.**

## MEVCUT ARAYUZLER (yeniden kullan, DEGISTIRME)
- `app/services/stock_scanning/db/backup.py`:
  - `backup_db(db_path, backup_dir, clock=None) -> dict` — timestamp'li kopya + manifest JSON (tablo->satir sayisi+checksum). Bos/olmayan DB'de hata vermez.
  - `verify_no_data_loss(original_db, target_db) -> dict` — kayip varsa `DataLossError` (.report).
  - `class DataLossError(Exception)`
- `app/api/masking.py`: `class ApiError(Exception)` — `ApiError(code: str, message: str, status: int=..., field: str|None=...)`; mevcut kodlar: `CODE_ADMIN_TOKEN_MISSING="ADMIN_TOKEN_MISSING"`, `CODE_ADMIN_TOKEN_INVALID="ADMIN_TOKEN_INVALID"`.
- `app/api/auth.py`: `class AdminAuth(token_provider)` — `X-Admin-Token` header dogrular; token_provider: callable / `.get_admin_token()` nesne / dict. `secrets.compare_digest` kullanir.
- `app/services/stock_scanning/orchestration/runs.py`: run durumlari `ACTIVE/COMPLETED/FAILED/ABORTED`, `TERMINAL_STATUSES`.
- `.gitignore` zaten `.env`, `*.db`, `logs/`, `yedekler/` iceriyor (dogrula, degistirme).

## YENI PAKET: `app/ops/`

### 1. `app/ops/__init__.py`
Bos/docstring.

### 2. `app/ops/secrets.py` — Gizli anahtar saglayici + redaksiyon
```python
class SecretMissingError(Exception): ...      # .name niteligi: eksik anahtar adi
class SecretProvider:
    def __init__(self, environ: dict | None = None):  # default os.environ; testte enjekte dict
    def get(self, name: str, required: bool = True, default: str | None = None) -> str | None
        # bos string = eksik sayilir; required ve eksikse SecretMissingError
    def require_all(self, names: list[str]) -> dict[str, str]
    def known_values(self) -> list[str]       # bos olmayan TUM degerler (redaksiyon icin); kopya dondurur
def redact_text(text: str, secret_values: list[str]) -> str
    # Her gizli degerin gectigi yere "***" koyar. Deger uzunlugu < 4 ise redaksiyon
    # uygulanmaz (kisa/genel degerlerin metni bozmasi engellenir) ama istersen
    # min_len parametresi (default 4). Gizli deger ASLA geri donmez.
SENSITIVE_KEY_RE = re.compile(r"(password|passwd|secret|token|api[_-]?key|authorization|sifre)", re.I)
def redact_mapping(data: dict, secret_values: list[str]) -> dict
    # Anahtari SENSITIVE_KEY_RE ile eslesen her deger -> "***" (deger ne olursa olsun);
    # diger string degerler redact_text'ten gecer; ic ice dict/list desteklenir; orijinal DEGISTIRILMEZ (kopya).
```
Kaynak koda hicbir gercek gizli deger yazilmaz; testlerde sahte degerler ("test-token-12345" gibi).

### 3. `app/ops/oplog.py` — Yapilandirilmis olay gunlugu (19 olay tipi)
```python
class LogEvent(str, Enum):
    SCAN_STARTED="SCAN_STARTED"; SCAN_FINISHED="SCAN_FINISHED"
    STOCK_TASK_STATUS="STOCK_TASK_STATUS"          # hisse bazli gorev durumu
    SOURCE_REQUEST="SOURCE_REQUEST"                # kaynak istegi
    SOURCE_HTTP_STATUS="SOURCE_HTTP_STATUS"        # HTTP durum kodu
    SOURCE_RESPONSE_TIME="SOURCE_RESPONSE_TIME"    # cevap suresi (ms)
    SOURCE_RETRY="SOURCE_RETRY"                    # tekrar deneme
    SOURCE_FALLBACK="SOURCE_FALLBACK"              # yedek kaynaga gecis
    PRICE_ROWS_FETCHED="PRICE_ROWS_FETCHED"        # cekilen fiyat satiri sayisi
    KAP_COUNT="KAP_COUNT"; NEWS_COUNT="NEWS_COUNT"
    DUPLICATES_ELIMINATED="DUPLICATES_ELIMINATED"  # elenen kopya
    WRONG_MATCH="WRONG_MATCH"                      # yanlis sirket eslesmesi
    MISSING_DATA="MISSING_DATA"; ABNORMAL_DATA="ABNORMAL_DATA"
    MANUAL_RESCAN="MANUAL_RESCAN"
    UNIVERSE_CHANGE="UNIVERSE_CHANGE"; SYMBOL_CHANGE="SYMBOL_CHANGE"
    ADMIN_SETTING_CHANGE="ADMIN_SETTING_CHANGE"
# TAM 19 uye. Test: len(LogEvent)==19.
class OpsLogger:
    def __init__(self, sink=None, clock=None, secret_provider=None, min_secret_len=4):
        # sink: callable(dict) — default: bellek listesi (logger.records)
        # clock: callable()->datetime — default UTC now
    def log(self, event: LogEvent, message: str="", *, run_id=None, symbol=None,
            source=None, level="INFO", **extra) -> dict
        # Kayit semasi (SABIT alan sirasi sozlukte korunur):
        # {"ts": ISO8601Z, "level": ..., "event": event.value, "run_id": ...|None,
        #  "symbol": ...|None, "source": ...|None, "message": ..., "extra": {...}}
        # KAYIT ONCESI: message ve extra redact_text / redact_mapping'den gecer
        # (secret_provider.known_values() + SENSITIVE_KEY_RE). Gizli deger ASLA yazilmaz.
    def to_json_lines(self) -> str             # her kayit bir satir JSON (ensure_ascii=False degil; ASCII guvenli: ensure_ascii=True)
```
Kolaylik metodlari ZORUNLU (her biri dogru event'i uretir):
`scan_started(run_id)`, `scan_finished(run_id, status)`, `stock_task(run_id, symbol, status, detail="")`, `source_request(source, url_path)`, `http_status(source, status_code)`, `response_time(source, elapsed_ms)`, `retry(source, attempt, delay_s)`, `fallback(source, from_target, to_target)`, `price_rows(source, symbol, rows)`, `kap_count(run_id, count)`, `news_count(run_id, count)`, `duplicates_eliminated(run_id, count)`, `wrong_match(symbol, expected, matched)`, `missing_data(symbol, field)`, `abnormal_data(symbol, field, value)`, `manual_rescan(run_id, by, reason)`, `universe_change(added, removed)`, `symbol_change(old, new)`, `admin_setting(key, by)`.
(**YASAK alan adlari**: hicbir log alaninda `puan`, `score`, `sinyal` gecmez — puan kilidi testi.)

### 4. `app/ops/roles.py` — Backend rol kontrolu
```python
ROLE_ADMIN="ADMIN"; ROLE_READONLY="READONLY"
ROLE_ORDER = {"READONLY": 1, "ADMIN": 2}     # hiyerarsi: ADMIN, READONLY'yi kapsar
CODE_ROLE_FORBIDDEN = "ROLE_FORBIDDEN"       # YENI kod — masking.py DEGISTIRILMEZ, burada tanimla
class RoleAuth:
    """X-Admin-Token -> rol eslesmesi. Backend ZORUNLULUGU: buton gizlemek yetmez,
    her yonetici cagrisi bu kontrolden gecer."""
    def __init__(self, token_roles_provider, clock=None):
        # token_roles_provider: callable()->dict[str,str] / .get_token_roles() / dict
        #  {"<token>": "ADMIN", ...}. Eslesme secrets.compare_digest ile.
    def role_for(self, headers: dict) -> str
        # header yok/bos -> ApiError(CODE_ADMIN_TOKEN_MISSING, 401)
        # token eslesmez  -> ApiError(CODE_ADMIN_TOKEN_INVALID, 403)
        # token degerleri hata MESAJINA ASLA yazilmaz
    def require(self, headers: dict, required_role: str) -> str
        # rol yetersizse ApiError(CODE_ROLE_FORBIDDEN, 403) — mesaj sabit, rol adi SIZMAZ? rol adi yazilabilir ama token asla.
def load_token_roles_from_env(environ: dict) -> dict[str,str]
    # ADMIN_TOKEN -> ADMIN; ek olarak ADMIN_ROLES_JSON='{"tok":"READONLY"}' parse;
    # bozuksa {} (hata firlatmaz, guvenli taraf: hicbir token rol alamaz)
```

### 5. `app/ops/source_health.py` — Kaynak saglik ekrani + 3-hata uyarisi
```python
@dataclass(frozen=True) class SourceHealth:
    name: str; active: bool; consecutive_errors: int
    last_success_at: str|None; last_error_at: str|None; last_error_message: str|None
    last_response_ms: float|None
class SourceHealthRegistry:
    def __init__(self, clock=None, warn_threshold=3, warning_sink=None):
        # warning_sink: callable(dict) — default dahili liste .warnings
    def register(self, name: str) -> None
    def record_success(self, name: str, response_ms: float|None=None) -> SourceHealth
        # consecutive_errors=0; last_success_at=clock(); kaynak yoksa otomatik register
    def record_error(self, name: str, message: str, response_ms: float|None=None) -> SourceHealth
        # consecutive_errors+=1; last_error_*; threshold'a ULASILDIĞINDA (== threshold) TEK uyari:
        # {"type":"SOURCE_UNHEALTHY","source":name,"consecutive_errors":n,"at":...}
        # (4.,5. hata tekrar uyari URETMEZ; basariyla sifirlaninca yeni esik tekrar uyarabilir)
        # mesaj redact_text'ten gecer (opsiyonel secret_provider ctor parametresi)
    def set_active(self, name: str, active: bool) -> None
    def get(self, name: str) -> SourceHealth
    def screen(self) -> list[dict]   # ekran sirasi: kayit sirasi; her satir SourceHealth alanlarinin dict'i
    warnings: list[dict]             # uretilen tum yonetici uyarilari (dahili kayit; musteri bildirimi DEGIL)
```

### 6. `app/ops/disk.py` — Disk kullanim kontrolu
```python
DISK_OK="OK"; DISK_WARN="WARN"; DISK_CRITICAL="CRITICAL"
@dataclass(frozen=True) class DiskStatus:
    path: str; total_bytes: int; used_bytes: int; free_bytes: int
    used_pct: float; level: str     # OK/WARN/CRITICAL
def check_disk_usage(path="/", warn_pct=80.0, critical_pct=95.0, stat_provider=None) -> DiskStatus
    # stat_provider: callable(path)->(total,used,free); default shutil.disk_usage sarmalayici
    # esik: pct >= critical -> CRITICAL; >= warn -> WARN; else OK (sinir degerleri WARN/CRITICAL'a dahil)
    # total=0 -> used_pct=0.0, level OK (sifira bolunme yok)
```

### 7. `app/ops/retention.py` — Arsiv + saklama suresi
```python
RAW_KINDS = ("raw_html","raw_api")                    # sinirli saklama
STRUCTURED_KINDS = ("price","kap","scan_result")      # KALICI — retention ASLA silmez
class ArchiveStore:
    def __init__(self, root_dir: str|Path, clock=None, raw_retention_days=14):
        # root_dir yoksa olusturur; alt klasorler: kind bazli
    def put(self, kind: str, name: str, content: bytes) -> Path
        # kind RAW_KINDS veya STRUCTURED_KINDS'den biri olmali, degilse ValueError
        # dosya adi guvenli hale getirilir (path traversal engellenir: "..", "/", "\\" -> "_")
    def list(self, kind: str) -> list[Path]
    def apply_retention(self, now: datetime|None=None) -> dict
        # yalniz RAW_KINDS: dosya mtime'indan (veya clock) raw_retention_days'ten eski -> sil
        # STRUCTURED_KINDS'a ASLA dokunmaz
        # rapor: {"deleted": [str...], "kept_raw": n, "kept_structured": n}
        # determinizm: dosya yasina karar 'now' parametresi (default clock())
```

### 8. `app/ops/backup.py` — Gunluk yedekleme (motor soyutlamasi)
NOT: Proje birincil DB = SQLite (BLOK 7). Talep "PostgreSQL gunluk yedekleme" — cozum:
motor soyutlamasi; `sqlite` motoru birincil, `postgres` motoru pg_dump-UYUMLU SQL dump
uretir (gercekte dump_fn=subprocess pg_dump cagirir; burada ENJEKTE).
```python
ENGINE_SQLITE="sqlite"; ENGINE_POSTGRES="postgres"
@dataclass(frozen=True) class BackupRecord:
    backup_id: str; engine: str; path: str; created_at: str; size_bytes: int
class SqliteBackupEngine:
    def __init__(self, db_path: str, backup_dir: str, clock=None): ...
    def run(self, now: datetime) -> BackupRecord
        # BLOK7 backup_db'yi cagirir; backup_id="bkp-YYYYMMDD-HHMMSS-sqlite"
class PostgresBackupEngine:
    def __init__(self, backup_dir: str, dump_fn, clock=None): ...
        # dump_fn: callable(out_path: Path) -> None — SQL dump'u out_path'e yazar (enjekte)
    def run(self, now: datetime) -> BackupRecord
        # out: backup_dir/bkp-...-postgres.sql; dump_fn cagrilir; size olculur
class DailyBackupScheduler:
    def __init__(self, engine, clock=None, retention_count=14, state_path: str|None=None):
        # state_path: son yedek bilgisinin JSON'da tutuldugu dosya (deterministik test icin enjekte)
    def is_due(self, now: datetime|None=None) -> bool
        # bugun (Europe/Istanbul gunu) icin basarili yedek YOKSA True
    def run_daily(self, now: datetime|None=None) -> BackupRecord | None
        # due degilse None; due ise engine.run + state guncelle + eski yedekleri budama
        # (retention_count'tan fazla BackupRecord en eskiden silinir; state dosyasindan izlenir)
```
Istanbul gunu: `zoneinfo.ZoneInfo("Europe/Istanbul")` ile gun sinirina gore.

### 9. `app/ops/restore.py` — Geri yukleme + geri yukleme TESTI
```python
@dataclass(frozen=True) class RestoreReport:
    ok: bool; engine: str; checks: list[str]; errors: list[str]
def restore_sqlite_backup(backup_record_path: str, target_dir: str) -> RestoreReport
    # BLOK7 manifest yanindaysa: tablo sayilari/checksum dogrulanir;
    # hedef gecici dizine kopyalanir, verify_no_data_loss ile karsilastirilir
def test_restore(record: BackupRecord, engine: str, work_dir: str, clock=None) -> RestoreReport
    # CANLI DB'ye DOKUNMAZ: yedegi work_dir'e geri yukler, butunluk kontrolleri,
    # raporlar. checks: ["backup_exists","copied","manifest_ok"/"sql_nonempty", ...]
    # hata -> ok=False + errors listesi (hicbir zaman exception SIZDIRMAZ; rapora yazar)
```

### 10. `app/ops/recovery.py` — VPS yeniden baslama guvenligi
```python
ABORT_REASON_VPS_RESTART = "vps_restart"
class FileRunStateStore:     # run durumlarini JSON dosyasinda tutan kalici depo
    def __init__(self, path: str, clock=None): ...
    def upsert(self, run_id: str, status: str, payload: dict|None=None) -> None
    def list_runs(self) -> list[dict]            # [{"run_id","status",...}]
    def mark(self, run_id: str, status: str, reason: str|None=None) -> None
class BootRecovery:
    """Servis acilisinda cagrilir."""
    def __init__(self, store: FileRunStateStore, clock=None): ...
    def recover(self) -> dict
        # status=="ACTIVE" kalan (yarim) run'lar -> ABORTED + reason=vps_restart
        # rapor: {"aborted": [run_id...], "already_terminal": n}
    def should_start_scan(self, day: str, revision: int=1) -> bool
        # ayni gun+revision icin COMPLETED run varsa False (cift tarama YOK);
        # ABORTED varsa True (yeniden denenebilir)
class PublishedStore:        # son yayinlanmis veri — restart'ta KAYBOLMAZ
    def __init__(self, path: str): ...
    def save(self, envelope: dict) -> None       # atomik yazim (tmp+rename)
    def load_last(self) -> dict | None           # dosya yoksa None; restart bunu SILMEZ
def verify_autostart(units_dir: str) -> dict
    # systemd/*.service|timer dosyalarini okur: [Install] WantedBy iceriyor mu
    # rapor: {"units": [{"file":..., "autostart": bool}...], "all_ok": bool}
```

## systemd EKLERI (yeni dosyalar)
- `systemd/xk100-backup.service`: Type=oneshot, `ExecStart=/usr/bin/python3 -m app.ops.backup_run`, `[Install] WantedBy=multi-user.target`
- `systemd/xk100-backup.timer`: `OnCalendar=*-*-* 23:30:00`, `Persistent=true`, `[Install] WantedBy=timers.target`
- `app/ops/backup_run.py`: `main()` — env'den BACKUP_ENGINE (default sqlite), DATABASE_PATH, BACKUP_DIR okuyup DailyBackupScheduler.run_daily cagiran giris noktasi (modul `python -m app.ops.backup_run` ile calisir; gercek DB yoksa bile import hatasiz yuklenir, main() cagrilmadikca is yapmaz).

## `.env.example` EKI (dosyanin SONUNA, mevcut icerik korunur)
```
# --- BLOK 21: Guvenlik, Log, Izleme, Yedekleme ---
# Rol eslemesi (JSON): {"<token>":"ADMIN"} — bos birakilirsa ADMIN_TOKEN ADMIN sayilir
ADMIN_ROLES_JSON=
# Ops log dizini (JSON-lines)
OPS_LOG_DIR=/var/log/xk100
# Kaynak saglik: art arda kac hata yonetici uyarisi uretir
SOURCE_HEALTH_WARN_THRESHOLD=3
# Disk esikleri (yuzde)
DISK_WARN_PCT=80
DISK_CRITICAL_PCT=95
# Ham arsiv saklama (gun) — yapilandirilmis veri KALICIdir
RAW_RETENTION_DAYS=14
# Yedekleme: sqlite|postgres
BACKUP_ENGINE=sqlite
BACKUP_DIR=/var/backups/xk100
BACKUP_RETENTION_COUNT=14
```

## TESTLER — `tests/blok21/` TAM 100 (dagilim KESIN)
| Dosya | Adet | Kapsam |
|---|---|---|
| test_secrets.py | 12 | get/require_all/eksik/bos string/default/known_values kopya/redact_text kisa deger/coklu gecis/redact_mapping anahtar-esli/ic ice/orijinal bozulmaz/SENSITIVE_KEY_RE |
| test_oplog_format.py | 12 | sema alanlari, ts format, 19 enum, her kolaylik metodu dogru event (toplu), json lines parse, ascii, extra serbest alan |
| test_oplog_redaction.py | 10 | message'da token, extra'da api_key degeri, anahtar adi password, ic ice extra, log sonrasi records'ta sizinti yok, bilinen tum degerler taranir, bilinmeyen metin korunur, kisa deger, json ciktisinda sizinti yok, sink'e giden kayit redakte |
| test_roles.py | 12 | header yok 401, bos 401, yanlis 403, ADMIN ok, READONLY ok, ADMIN>=READONLY require, READONLY ADMIN gereken yerde ROLE_FORBIDDEN, token mesajda sizmaz, env json parse, bozuk json {}, dict provider, compare_digest kullanimi (monkeypatch okunur veya sabit zaman) |
| test_source_health.py | 14 | register, basari sifirlar, hata sayaci, 3. hatada TEK uyari, 4./5. uyari yok, basari sonrasi yeni esik, ekran alanlari, aktif/pasif, bilinmeyen kaynak oto-register, last_response_ms, uyari semasi, mesaj redaksiyonu, screen sirasi, clock determinizm |
| test_disk.py | 8 | OK/WARN/CRITICAL sinirlari, tam esik degerleri, total=0, stat_provider enjekte, DiskStatus alanlari, pct hesabi, varsayilan esikler |
| test_retention.py | 10 | put/list, kind ValueError, path traversal temizligi, raw eski silinir, raw yeni kalir, structured ASLA silinmez, rapor alanlari, retention_days=0, now enjekte, klasor olusumu |
| test_backup.py | 10 | sqlite engine record, backup_id format, postgres dump_fn cagirildi+dosya, is_due ayni gun False, ertesi gun True, run_daily due-degil None, retention budama, state dosyasi, clock enjekte, engine secimi |
| test_restore.py | 6 | sqlite yedek->test_restore ok, checks icerigi, bozuk/missing dosya ok=False errors, canli DB dokunulmaz (varsa yol kontrol), postgres sql bos-degil kontrol, rapor alanlari |
| test_recovery.py | 6 | ACTIVE->ABORTED reason, terminal'e dokunmaz, should_start cift-tarama engeli, ABORTED yeniden izin, PublishedStore save/load + recover sonrasi korunur, verify_autostart units |
| **TOPLAM** | **100** | |

Her test dosyasinda ustte kisa Turkce docstring. Fixture'lar tmp_path kullanir. Gercek zaman kullanan test YOK (clock enjekte).

## TESLIM
1. `app/ops/` paketi (10 modul + backup_run.py) — tamamı docstring'li (Turkce, BLOK 21 basligi)
2. `tests/blok21/` — TAM 100 test, `python -m pytest tests/blok21 -q` -> 100 passed
3. Mevcut regresyonu BOZMA: `python -m pytest tests/blok6 tests/blok7 tests/blok8 tests/blok9 tests/blok10 tests/blok11 tests/blok12 tests/blok13 tests/blok14 tests/blok15 tests/blok16 tests/blok18 tests/blok19 tests/blok20 -q` -> 1400 passed kalmali
4. systemd 2 yeni dosya + .env.example eki
5. Son rapor: dosya listesi + test ciktilari
