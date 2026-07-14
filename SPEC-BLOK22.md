# SPEC-BLOK22 — Test, VPS Deployment ve Kesin Tamamlanma

Repo: `/mnt/agents/output/borsa-karar-otomasyon` (BLOK 6-21 tamam, 1500 test geciyor)

## GENEL KURALLAR (KESIN)
- Python 3.12, yalnizca stdlib (testlerde pytest). Deterministik: clock/fetcher/duration ENJEKTE.
- Gercek ag/subprocess YOK. Smoke suite'in default fetch'i urllib olabilir ama testlerde ASLA kullanilmaz.
- Turkce alan adlari; ASCII tanimlayicilar.
- **MEVCUT DOSYALARA DOKUNULMAZ.** Yalnizca yeni: `app/acceptance/`, `app/api/health.py`, `deploy/`, `tests/blok22/`.
- Puan kilidi + bildirim kilidi suruyor. Sahte tarih/skor/hisse/test sonucu "canli" GOSTERILMEZ.
- Kabul testleri GERCEK modulleri cagirir (BLOK 5-21); sahte yalnizca fetcher/clock/duration seviyesinde.
- `python -m pytest tests/blok22 -q` -> **TAM 100/100**; regresyon blok6-22 -> **1600/1600**.

## ONCE OKUNACAK ARAYUZLER (kullanim ornegi icin test dosyalarina bak)
- `app/services/stock_scanning/symbol_identity.py` — `SymbolIdentityService(clock=...)`: `register_stock(company_name, isin=None)->stock_id`, `add_symbol(...)`, `change_symbol(...)`, `get_active_symbol(stock_id, platform)`, `get_symbol_history(...)`, `resolve(...)`, `resolve_old_code(old, platform)`, `set_kap_link(stock_id,url)`, `mark_pending(...)`, `get_audit_log(...)`. Istisnalar: `DuplicateSymbolError`, `SymbolNotFoundError`, `StockNotFoundError` vb. Kullanim: `tests/blok6/`.
- `app/services/stock_scanning/identity_adapter.py` — `IdentityAdapter(service).resolve_universe_symbols(...)`, `get_pending_symbols()`.
- `app/services/stock_scanning/kap_verifier.py` — `KapVerifier(...).verify(stock_id)->KapLinkStatus`, probe ENJEKTE. Kullanim: `tests/blok6/`.
- `price_collection/` (collector, sources, storage, validator) — kaynak fallback + fiyat farki + artimli guncelleme. Kullanim: `tests/blok8/`.
- `validation/ohlcv_validator.py`, `validation/calendar.py` (tatil/islem gunu), `validation/corporate.py`. Kullanim: `tests/blok9/`.
- `volume/` — NULL vs 0 ayrimi (hacim 0 gercek sifir; eksik fiyat None kalir, ASLA 0 yapilmaz). Kullanim: `tests/blok10/`.
- `kap_collection/collector.py` — duplikasyon + revizyon zinciri (`revises`/`cancels` alanlari). Kullanim: `tests/blok11/`.
- `news/matcher.py`, `news/dedupe.py` — yanlis eslesme engeli + 6 kanal duplikasyon. Kullanim: `tests/blok12/`.
- `corporate_actions/registry.py`, `restrictions.py`, `suspension.py` — TRADING_HALT: taramada kalir + scoring_ready=false. Kullanim: `tests/blok13/`.
- `orchestration/runs.py` (run_id idempotens, R2), `orchestration/pool.py` (hata izolasyonu), `orchestration/schedule.py` (fazlar, 09:40 DATA_CUTOFF). Kullanim: `tests/blok14/`.
- `confidence/calculator.py` — `ConfidenceCalculator().calculate(stock_id, components, readiness)`. Kullanim: `tests/blok15/`.
- `app/api/router.py` (`Router.register/dispatch`), `app/api/customer.py` (`CustomerHandlers(ds).register(router)`, uclar: universe, stock_summary, scan_latest, prices, kap, news, corporate_actions, restrictions, index_scan_latest, stocks_list), `app/api/auth.py`. Kullanim: `tests/blok16/`.
- `app/ops/*` (BLOK 21): `recovery.BootRecovery`, `backup`, `restore`, `disk`, `source_health`, `oplog`. Kullanim: `tests/blok21/`.
- Sayfa testleri ornegi: `tests/blok18/`, `tests/blok19/`, `tests/blok20/` (index.html cift-aday yol cozumu deseni AYNEN kullanilir).

## YENI PAKET: `app/acceptance/`

### 1. `app/acceptance/__init__.py` — docstring (BLOK 22 basligi)

### 2. `app/acceptance/universe.py` — Resmi XK100 evren defteri
```python
@dataclass(frozen=True) class MembershipInterval: symbol: str; entered: str; exited: str|None  # ISO gun
class UniverseBook:
    """Resmi evren listesi ENJEKTE provider'dan gelir; modul liste URETMEZ (sahte evren yok)."""
    def __init__(self, identity: SymbolIdentityService, clock=None): ...
    def load_official(self, symbols: list[str], day: str) -> None
        # ilk yukleme: her sembol icin identity'de kayit yoksa register_stock+add_symbol; uyelik araligi acar
    def active_symbols(self, day: str) -> list[str]          # o gun aktif uyeler (tarihsel uyelik)
    def active_count(self, day: str) -> int
    def validate_count(self, day: str, expected: int = 100) -> dict
        # {"day":..., "expected":100, "actual":n, "ok":bool, "extra":[...], "missing":[...]}
    def enter(self, symbol: str, company_name: str, day: str) -> None   # yeni sirket girisi (+halka arz)
    def exit(self, symbol: str, day: str) -> None                       # sirket cikisi; kayit SILINMEZ (tarihsel korunur)
    def is_member(self, symbol: str, day: str) -> bool                  # tarihsel uyelik sorgusu
    def history(self, symbol: str) -> list[MembershipInterval]
```

### 3. `app/acceptance/staging.py` — Tam gunluk ornek tarama
```python
@dataclass(frozen=True) class StockDayResult:
    symbol: str; state: str            # READY|PARTIAL_DATA|FAILED|INACTIVE
    price_rows: int|None; volume_rows: int|None; kap_count: int; news_count: int
    action_count: int; restriction_count: int
    data_confidence: int               # 0-100 (ConfidenceCalculator ile)
    missing_fields: tuple[str, ...]    # eksik alanlar; None->alan adi, ASLA 0'a cevrilmez
@dataclass(frozen=True) class StagingReport:
    run_id: str; day: str; started_at: str; finished_at: str
    finish_by_0935: bool               # simulated finished_at <= 09:35
    total: int; ready: int; partial: int; failed: int; inactive: int
    missing_total: int                 # hic sessiz dusme yoksa total == len(results)
    results: tuple[StockDayResult, ...]
    envelope: dict                     # scan_run_id/report_version/data_cutoff_at/last_updated_at/status
class StagingRunner:
    """Tam gun ornek tarama — GERCEK modullerle, ENJEKTE fetcher'larla.
    Gercek ag YOK. 'staging' run_id oneki: 'STAGING-YYYY-MM-DD-TARAMA-R1'."""
    def __init__(self, universe: UniverseBook, fetchers: dict, clock=None,
                 durations: dict | None = None, fail_symbols: set[str] | None = None):
        # fetchers: {"price": fn(symbol)->list[bar]|None, "volume": fn, "kap": fn(symbol)->list,
        #            "news": fn(symbol)->list, "actions": fn(symbol)->list, "restrictions": fn(symbol)->list}
        # durations: gorev basina simule sure (sn); toplam 08:00'dan eklenir -> finished_at
        # fail_symbols: bu sembollerde price fetcher hata firlatir (hata izolasyonu kaniti)
    def run(self, day: str) -> StagingReport
        # 1) evren validate_count(100)  2) her sembol icin: fetch -> OHLC dogrula (validation) ->
        #    hacim siniflandir (volume) -> KAP/haber say -> kurumsal islem/tedbir (corporate_actions) ->
        #    Veri Guveni hesapla (confidence)  3) sembol hatasi digerlerini DURDURMAZ (state=FAILED, devam)
        # 4) eksik veri None kalir; missing_fields'a yazilir (0'a CEVRILMEZ)
        # 5) zarf (envelope) uret; status: OK|PARTIAL|FAILED  6) finish_by_0935 hesapla
```

### 4. `app/acceptance/deployment.py` — Deployment artefakt dogrulayici + dry-run
```python
DEPLOY_STEPS = ("migration","backend_service","api_service","systemd_service","systemd_timer",
                "reverse_proxy","https","health_endpoint","log_rotation","backup")   # TAM 10
@dataclass(frozen=True) class DeployStep: name: str; ok: bool; detail: str
@dataclass(frozen=True) class DeploymentReport: ok: bool; steps: tuple[DeployStep, ...]; mode: str  # mode="dry-run"
def validate_artifacts(deploy_dir: str, repo_root: str) -> DeploymentReport
    # deploy/deploy.sh, nginx-xk100.conf, certbot-https.sh, logrotate-xk100, DEPLOYMENT.md var mi;
    # icerik kontrolleri: nginx'te proxy_pass + listen 443 + ssl_certificate; logrotate'te rotate N +
    #   missingok + copytruncate|create; deploy.sh'te migrator cagrisi + systemctl enable --now xk100-api +
    #   xk100-hisse-tarama.timer + xk100-backup.timer + curl /health smoke satiri;
    # systemd unitlerinde [Install] WantedBy (BLOK21 verify_autostart yeniden kullanilabilir)
def dry_run_migration(repo_root: str, work_dir: str) -> DeployStep
    # BLOK7 migrator: schema.sql ile work_dir'de gecici DB olustur -> migration uygula ->
    # tablolar var mi (repo tablolari) -> ok. Gercek DB'ye DOKUNMAZ.
def health_wiring_check(repo_root: str) -> DeployStep   # app/api/health.py import edilebilir + register deseni
```

### 5. `app/acceptance/smoke.py` — Deployment sonrasi smoke suite
```python
@dataclass(frozen=True) class SmokeCheck: name: str; ok: bool; detail: str
@dataclass(frozen=True) class SmokeReport: ok: bool; checks: tuple[SmokeCheck, ...]; base_url: str
class SmokeSuite:
    def __init__(self, base_url: str, fetch_fn=None, admin_token: str | None = None):
        # fetch_fn: callable(method, path, headers=None) -> (status:int, body:dict|str)
        # default: urllib tabanli gercek istemci (YALNIZ kullanici VPS'te calistirir; testlerde enjekte)
    def run_all(self) -> SmokeReport
        # checks: health_200, health_fields, summary_envelope_keys, pagination_25_of_100,
        # admin_missing_token_401, admin_wrong_token_403, chart_format, api_contract_ok
```

### 6. `app/acceptance/completion.py` — 14 kesin tamamlanma kriteri
```python
@dataclass(frozen=True) class CriterionResult: key: str; ok: bool; evidence: str
CRITERIA = ("official_universe_verified","hundred_active_scanned","data_collected_all_channels",
    "missing_not_zeroed","confidence_per_stock","standard_packet_built","home_real_scan_status",
    "real_summary_table_works","detail_real_raw_chart","mobile_same_api_or_contract",
    "admin_schema_real_files","no_fake_live_data","staging_fullday_verified","deployment_artifacts_ready")  # TAM 14
def check_completion(repo_root: str, site_root: str, staging_report: StagingReport,
                     deploy_report: DeploymentReport) -> list[CriterionResult]
    # Her kriter GERECEK kanita bakar: staging_report alanlari, site_root/index.html'de
    # stk-summary/stk-detail baglanti noktalari + "HISSE SKORLAMA MODULU HENUZ CANLI DEGIL" bandi,
    # docs.html C1-C13 + gercek test dosyasi yollari, api-contract.json native_mobile=HAZIR_BEKLIYOR,
    # DEMO rozeti yalnizca sabit demo bloklarinda (canli kartlarda yok) — dürüst, kanitsiz kriter ok=False.
```

### 7. `app/api/health.py` — Health endpoint (yeni dosya; BLOK16 deseni)
```python
class HealthHandlers:
    def __init__(self, clock=None, disk_stat_provider=None, version: str = "1.0.0",
                 started_at: str | None = None): ...
    def health(self, request) -> tuple[int, dict] | Response
        # {"status":"ok","version":...,"time":ISO,"uptime_s":int,"disk":{"used_pct":..,"level":..},
        #  "checks":{"api":"ok"}} — BLOK21 disk.check_disk_usage yeniden kullanilir
    def register(self, router) -> None      # GET /health — auth YOK (izleme ucu); govdede sir YOK
```

## deploy/ ARTEFAKTLARI (gercek, VPS'te calistirilabilir)
- `deploy/deploy.sh` — bash, `set -euo pipefail`; adimlar: pip install -r requirements.txt →
  `python -m app.services.stock_scanning.db.migrator` (veya schema uygulama) → systemd unitlerini
  /etc/systemd/system'e kopyala → `systemctl daemon-reload` → `systemctl enable --now xk100-api.service
  xk100-index-scoring.timer xk100-hisse-tarama.timer xk100-backup.timer` → nginx conf kopyala + `nginx -t`
  + reload → smoke: `curl -fsS https://<domain>/health` → yedek: xk100-backup.timer dogrula.
  Basinda ACIKCA: "Bu betik VPS uzerinde root/sudo ile calistirilir; bu ortamda CALISTIRILMAZ."
- `deploy/nginx-xk100.conf` — server 80→443 redirect; 443: ssl_certificate /etc/letsencrypt/live/<domain>/...;
  `location /api/ { proxy_pass http://127.0.0.1:8000; proxy_set_header ... }`; `location /health { proxy_pass ... }`;
  statik site root /var/www/xk100.
- `deploy/certbot-https.sh` — certbot --nginx -d <domain> adimlari + yenileme timer notu.
- `deploy/logrotate-xk100` — /var/log/xk100/*.log: daily, rotate 14, compress, missingok, notifempty, copytruncate.
- `deploy/DEPLOYMENT.md` — sirali kontrol listesi (10 adim, her adimin dogrulama komutu) + geri alma notu.

## TESTLER — `tests/blok22/` TAM 100 (dagilim KESIN)
| Dosya | Adet | Kapsam (30 zorunlu senaryo → test) |
|---|---|---|
| test_universe_membership.py | 8 | aktif sayi=100 (1); giris: aktif 101 + yeni sembol cozulur (2); cikis: aktif 99 + kayit korunur (2); tarihsel uyelik: gecmis gun uye/degil, araliklar, cikis oncesi/sonrasi (3) |
| test_symbol_identity.py | 6 | kod degisikligi: eski->yeni resolve + tarihce (2); sembol eslestirme: normalize + yanlis sembol reddi/queue (2); KAP kimligi: set_kap_link + KapVerifier enjekte probe (2) |
| test_price_integrity.py | 8 | OHLC: high>=max(o,c,l), low<=min(o,c,h), bozuk bar reddi (3); NULL/sifir: eksik gun None kalir, hacim 0 gercek sifir, None ASLA 0 olmaz (3); artimli: yalniz yeni gun eklenir, mevcut gun tekrar eklenmez (2) |
| test_source_resilience.py | 5 | kaynak gecisi: ana kaynak hata -> yedek kaynak + fallback kaydi (2); kaynak fiyat farki: esik ustu fark tespiti + hangi kaynak secildi (3) |
| test_corporate_calendar.py | 9 | kurumsal islem: bolunme duzeltmesi fiyat serisine uygulanir + versiyon zinciri (3); yeni halka arz: IPO gunu eklenir, oncesi None (URETILMEZ) (2); tatil gunu: islem gunu degil -> bar uretilmez/tarama atlanir (2); islem durdurma: TRADING_HALT taramada kalir + scoring_ready=false (2) |
| test_kap_news_integrity.py | 9 | KAP duplikasyon: ayni bildirim tek kayit (2); KAP revizyon: revises zinciri SUPERSEDED/REVISED (2); haber yanlis eslesme: benzer isim baska sirkete baglanmaz/queue (2); haber duplikasyon: ajans kopyasi + ayni URL tek (3) |
| test_run_resilience.py | 9 | ayni run_id: RunAlreadyActiveError / idempotent, R2 kurali (2); hata izolasyonu: 1 sembol patlar, 99 devam + FlowReport sayaclari (2); VPS restart: ACTIVE->ABORTED + cift tarama engeli + yayin korunur (3); 09:35: durations toplamiyla finish<=09:35 True + asimda False (2) |
| test_confidence_api.py | 14 | Veri Guveni: 0-100 + technical_ready/scoring_ready + eksik alanlar (3); API yetkilendirme: 401/403/200 + token sizmaz (3); sayfalama: 100 hisse page_size=25 -> 4 sayfa + total=100 + sayfa smiri (3); filtreleme: sektor + durum filtresi (2); grafik format: prices ucu mum dizisi {date,open,high,low,close,volume} + HAM/DUZELTILMIS ayrimi (2); mobil tasma: index.html media query + 44px + viewport (1) |
| test_staging_fullday.py | 8 | 100 sirket uretilir (universe provider enjekte); run() -> total==100 (sessiz dusme yok); her sonucta state + data_confidence var; eksik veri missing_fields'ta, 0'a cevrilmemis; fail_symbols izolasyonu; finish_by_0935; zarf alanlari (scan_run_id STAGING- oneki, report_version, data_cutoff_at); rapor JSON'a serilestirilebilir |
| test_deployment.py | 8 | 5 artefakt dosyasi var; nginx icerik (proxy_pass+443+ssl); logrotate icerik; deploy.sh adimlari (migrate+enable+health satiri); dry_run_migration gecici DB'de OK; DEPLOY_STEPS==10; systemd autostart (BLOK21 ile tutarli); DeploymentReport.ok |
| test_smoke.py | 6 | health_200+alanlar; zarf anahtarlari; sayfalama 25/100; admin 401 + yanlis 403; grafik format; SmokeReport.ok + tum SmokeCheck kayitlari (hepsi enjekte fetch_fn ile, in-process router) |
| **TOPLAM** | **100** | |

Not: sayfa testlerinde `tests/blok18`'deki cift-aday yol cozumu deseni KULLANILIR
(`_REPO_ROOT.parent/"telegram-sender"` veya `_REPO_ROOT`); site_root completion icin de ayni desen.

## TESLIM
1. `app/acceptance/` (6 modul) + `app/api/health.py` + `deploy/` (5 dosya)
2. `tests/blok22/` TAM 100 test — 100/100
3. Regresyon blok6-22 = 1600/1600 bozulmasin
4. Son rapor: dosya listesi + pytest kanitlari + kisa mimari ozet
