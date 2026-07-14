"""BLOK 6 - Sirket Kimligi ve Sembol Eslestirme: TAM 100 pytest testi.

Kategoriler (toplam = 100):
1. Dogru sembol eslestirme (bist/yahoo/google/tradingview/kap) - 20 test
2. Yanlis sirkete eslesmeme (benzer isimler) - 12 test
3. Kisa kod kelime-ici yanlis eslesme engelleme - 14 test
4. Kod degisikligi / eski kod gecmisi (valid_from-valid_to) - 16 test
5. KAP kimligi + link dogrulama (mock http) - 14 test
6. Cift eslestirme (duplicate) senaryolari - 12 test
7. Bozuk link + SYMBOL_VERIFICATION_PENDING kuyrugu - 12 test

Hicbir test gercek internete erismez (http_client mock).
"""
from __future__ import annotations

import re
from datetime import date, datetime

import pytest

from app.admin.symbol_admin import SymbolAdmin
from app.models.stock_identity import KapLinkStatus, VerificationStatus
from app.services.stock_scanning.identity_adapter import IdentityAdapter
from app.services.stock_scanning.kap_verifier import KapVerifier
from app.services.stock_scanning.symbol_identity import (
    REASON_KAP_LINK_BROKEN,
    REASON_UNRESOLVED_UNIVERSE_SYMBOL,
    DuplicateSymbolError,
    InvalidPlatformError,
    QueueItemNotFoundError,
    StockAlreadyExistsError,
    StockNotFoundError,
    SymbolConflictError,
    SymbolIdentityService,
    SymbolNotFoundError,
)

FIXED_NOW = datetime(2024, 1, 15, 12, 0, 0)


# ---------------------------------------------------------------------------
# Yardimcilar / fixture'lar
# ---------------------------------------------------------------------------
class MockHttpResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


class MockHttpClient:
    """Sahte HTTP istemcisi: routes {url: status_code}, errors {url: exc}."""

    def __init__(self, routes=None, errors=None):
        self.routes = routes or {}
        self.errors = errors or {}
        self.calls = []

    def head(self, url):
        self.calls.append(("HEAD", url))
        if url in self.errors:
            raise self.errors[url]
        return MockHttpResponse(self.routes.get(url, 404))


@pytest.fixture
def clock():
    return lambda: FIXED_NOW


@pytest.fixture
def service(clock):
    return SymbolIdentityService(clock=clock)


@pytest.fixture
def universe(service):
    """Uc hisseli tam platform evreni."""
    ids = {}
    ids["THY"] = service.register_stock("Türk Hava Yolları", "TRATHYAO91M5")
    service.add_symbol(ids["THY"], "bist", "THYAO")
    service.add_symbol(ids["THY"], "yahoo", "THYAO.IS")
    service.add_symbol(ids["THY"], "google", "IST:THYAO")
    service.add_symbol(ids["THY"], "tradingview", "BIST:THYAO")
    service.add_symbol(ids["THY"], "kap", "THYAO")

    ids["ISB"] = service.register_stock("Türkiye İş Bankası C", "TRAISCTR91N2")
    service.add_symbol(ids["ISB"], "bist", "ISCTR")
    service.add_symbol(ids["ISB"], "yahoo", "ISCTR.IS")
    service.add_symbol(ids["ISB"], "google", "IST:ISCTR")
    service.add_symbol(ids["ISB"], "tradingview", "BIST:ISCTR")
    service.add_symbol(ids["ISB"], "kap", "ISCTR")

    ids["KCH"] = service.register_stock("Koç Holding", "TRAKCHOL91Q8")
    service.add_symbol(ids["KCH"], "bist", "KCHOL")
    service.add_symbol(ids["KCH"], "yahoo", "KCHOL.IS")
    service.add_symbol(ids["KCH"], "kap", "KCHOL")
    return ids


# ===========================================================================
# KATEGORI 1: Dogru sembol eslestirme (bist/yahoo/google/tradingview/kap) - 20
# ===========================================================================
class TestCorrectSymbolMatching:
    def test_001_resolve_bist_symbol(self, service, universe):
        res = service.resolve("THYAO", platform="bist")
        assert res is not None
        assert res.stock_id == universe["THY"]
        assert res.historical is False

    def test_002_resolve_yahoo_symbol(self, service, universe):
        res = service.resolve("THYAO.IS", platform="yahoo")
        assert res.stock_id == universe["THY"]

    def test_003_resolve_google_symbol(self, service, universe):
        res = service.resolve("IST:THYAO", platform="google")
        assert res.stock_id == universe["THY"]

    def test_004_resolve_tradingview_symbol(self, service, universe):
        res = service.resolve("BIST:THYAO", platform="tradingview")
        assert res.stock_id == universe["THY"]

    def test_005_resolve_kap_symbol(self, service, universe):
        res = service.resolve("ISCTR", platform="kap")
        assert res.stock_id == universe["ISB"]

    def test_006_resolve_case_insensitive(self, service, universe):
        res = service.resolve("thyao", platform="bist")
        assert res.stock_id == universe["THY"]

    def test_007_resolve_turkish_dotted_i_symbol(self, service, universe):
        # "İSCTR" -> normalize -> "ISCTR"
        res = service.resolve("İSCTR", platform="bist")
        assert res.stock_id == universe["ISB"]

    def test_008_resolve_symbol_without_platform(self, service, universe):
        res = service.resolve("THYAO.IS")
        assert res.stock_id == universe["THY"]
        assert res.platform == "yahoo"

    def test_009_resolve_company_name_exact(self, service, universe):
        res = service.resolve("Türk Hava Yolları")
        assert res.stock_id == universe["THY"]
        assert res.matched_by == "company_name"

    def test_010_resolve_company_name_normalized_upper(self, service, universe):
        res = service.resolve("TURK HAVA YOLLARI")
        assert res.stock_id == universe["THY"]

    def test_011_resolve_company_name_turkish_chars(self, service, universe):
        res = service.resolve("TÜRKİYE İŞ BANKASI C")
        assert res.stock_id == universe["ISB"]

    def test_012_resolve_company_name_koc(self, service, universe):
        res = service.resolve("KOC HOLDING")
        assert res.stock_id == universe["KCH"]

    def test_013_get_active_symbol(self, service, universe):
        assert service.get_active_symbol(universe["THY"], "bist") == "THYAO"
        assert service.get_active_symbol(universe["THY"], "yahoo") == "THYAO.IS"
        assert service.get_active_symbol(universe["KCH"], "kap") == "KCHOL"

    def test_014_stock_id_format_and_sequence(self, service):
        id1 = service.register_stock("A Şirketi")
        id2 = service.register_stock("B Şirketi")
        assert id1 == "STK-000001"
        assert id2 == "STK-000002"
        assert re.fullmatch(r"STK-\d{6}", id1)

    def test_015_deterministic_stock_id(self, clock):
        s1 = SymbolIdentityService(clock=clock)
        s2 = SymbolIdentityService(clock=clock)
        a1 = s1.register_stock("Deterministik AŞ", "TR0000000001")
        a2 = s2.register_stock("Deterministik AŞ", "TR0000000001")
        assert a1 == a2 == "STK-000001"

    def test_016_register_duplicate_name_isin_raises(self, service, universe):
        with pytest.raises(StockAlreadyExistsError) as exc:
            service.register_stock("Türk Hava Yolları", "TRATHYAO91M5")
        assert exc.value.code == "STOCK_ALREADY_EXISTS"

    def test_017_add_symbol_conflict_open_record(self, service, universe):
        with pytest.raises(SymbolConflictError) as exc:
            service.add_symbol(universe["THY"], "bist", "THYAO2")
        assert exc.value.code == "SYMBOL_CONFLICT"

    def test_018_add_symbol_invalid_platform_raises(self, service, universe):
        with pytest.raises(InvalidPlatformError) as exc:
            service.add_symbol(universe["THY"], "nyse", "THYAO")
        assert exc.value.code == "INVALID_PLATFORM"

    def test_019_add_symbol_unknown_stock_raises(self, service):
        with pytest.raises(StockNotFoundError) as exc:
            service.add_symbol("STK-999999", "bist", "XXXX")
        assert exc.value.code == "STOCK_NOT_FOUND"

    def test_020_resolve_unknown_returns_none(self, service, universe):
        assert service.resolve("ZZZZZ") is None
        assert service.resolve("Bilinmeyen Şirket") is None
        assert service.resolve("") is None


# ===========================================================================
# KATEGORI 2: Yanlis sirkete eslesmeme (benzer isimler) - 12
# ===========================================================================
@pytest.fixture
def similar(service):
    ids = {}
    ids["ABCH"] = service.register_stock("ABC Holding")
    service.add_symbol(ids["ABCH"], "bist", "ABCH")
    ids["ABCY"] = service.register_stock("ABC Yatırım Holding")
    service.add_symbol(ids["ABCY"], "bist", "ABCY")
    ids["ISCTR"] = service.register_stock("Türkiye İş Bankası C")
    service.add_symbol(ids["ISCTR"], "bist", "ISCTR")
    ids["ISMEN"] = service.register_stock("İş Yatırım Menkul Değerler")
    service.add_symbol(ids["ISMEN"], "bist", "ISMEN")
    ids["ANSGR"] = service.register_stock("Anadolu Sigorta")
    service.add_symbol(ids["ANSGR"], "bist", "ANSGR")
    ids["ANHYT"] = service.register_stock("Anadolu Hayat Emeklilik")
    service.add_symbol(ids["ANHYT"], "bist", "ANHYT")
    ids["GARAN"] = service.register_stock("Garanti BBVA")
    service.add_symbol(ids["GARAN"], "bist", "GARAN")
    ids["GRNYO"] = service.register_stock("Garanti Yatırım Ortaklığı")
    service.add_symbol(ids["GRNYO"], "bist", "GRNYO")
    return ids


class TestSimilarNamesNoMismatch:
    def test_021_abc_holding_resolves_correctly(self, service, similar):
        res = service.resolve("ABC Holding")
        assert res.stock_id == similar["ABCH"]

    def test_022_abc_yatirim_holding_resolves(self, service, similar):
        res = service.resolve("ABC Yatırım Holding")
        assert res.stock_id == similar["ABCY"]

    def test_023_abc_alone_no_match(self, service, similar):
        # "ABC" tek tokeni hicbir sirket adinin token kumesine esit degil
        assert service.resolve("ABC") is None

    def test_024_is_bankasi_partial_no_match(self, service, similar):
        # "İş Bankası" eksik tokenli sorgu; "Türkiye İş Bankası C"ye eslesmemeli
        assert service.resolve("İş Bankası") is None

    def test_025_is_yatirim_resolves(self, service, similar):
        res = service.resolve("İş Yatırım Menkul Değerler")
        assert res.stock_id == similar["ISMEN"]

    def test_026_anadolu_alone_no_match(self, service, similar):
        assert service.resolve("Anadolu") is None

    def test_027_anadolu_sigorta_resolves(self, service, similar):
        res = service.resolve("Anadolu Sigorta")
        assert res.stock_id == similar["ANSGR"]

    def test_028_anadolu_hayat_resolves(self, service, similar):
        res = service.resolve("Anadolu Hayat Emeklilik")
        assert res.stock_id == similar["ANHYT"]

    def test_029_garanti_alone_no_match(self, service, similar):
        # "Garanti" -> ne "Garanti BBVA" ne "Garanti Yatırım Ortaklığı"
        assert service.resolve("Garanti") is None

    def test_030_garanti_bbva_resolves(self, service, similar):
        res = service.resolve("Garanti BBVA")
        assert res.stock_id == similar["GARAN"]

    def test_031_sigorta_token_no_substring_match(self, service, similar):
        # "Sigorta", "Anadolu Sigorta" icindeki bir token; substring eslesme yok
        assert service.resolve("Sigorta") is None
        assert service.resolve("HOLDING") is None

    def test_032_symbols_map_to_correct_company(self, service, similar):
        res = service.resolve("ISMEN", platform="bist")
        assert res.stock_id == similar["ISMEN"]
        assert res.stock_id != similar["ISCTR"]
        res2 = service.resolve("ABCY", platform="bist")
        assert res2.stock_id == similar["ABCY"]
        assert res2.stock_id != similar["ABCH"]


# ===========================================================================
# KATEGORI 3: Kisa kod kelime-ici yanlis eslesme engelleme - 14
# ===========================================================================
@pytest.fixture
def shortcodes(service):
    ids = {}
    ids["ISGM"] = service.register_stock("IS Gayrimenkul Yatırım Ortaklığı")
    service.add_symbol(ids["ISGM"], "bist", "IS")
    ids["ISCTR"] = service.register_stock("Türkiye İş Bankası C")
    service.add_symbol(ids["ISCTR"], "bist", "ISCTR")
    ids["TKT"] = service.register_stock("TK Teknoloji")
    service.add_symbol(ids["TKT"], "bist", "TK")
    ids["TKNSA"] = service.register_stock("Teknosa İç ve Dış Ticaret")
    service.add_symbol(ids["TKNSA"], "bist", "TKNSA")
    ids["AYT"] = service.register_stock("A Yatırım")
    service.add_symbol(ids["AYT"], "bist", "A")
    ids["ASELS"] = service.register_stock("Aselsan Elektronik")
    service.add_symbol(ids["ASELS"], "bist", "ASELS")
    ids["ISBM"] = service.register_stock("IS Bankası Menkul Değerler")
    service.add_symbol(ids["ISBM"], "bist", "ISB")
    ids["ISGSY"] = service.register_stock("IS Girişim Sermayesi")
    service.add_symbol(ids["ISGSY"], "bist", "ISGSY")
    return ids


class TestShortCodeWordBoundary:
    def test_033_short_code_is_exact(self, service, shortcodes):
        res = service.resolve("IS", platform="bist")
        assert res.stock_id == shortcodes["ISGM"]

    def test_034_isctr_not_matched_by_is(self, service, shortcodes):
        res = service.resolve("ISCTR", platform="bist")
        assert res.stock_id == shortcodes["ISCTR"]

    def test_035_is_does_not_resolve_to_isctr(self, service, shortcodes):
        res = service.resolve("IS", platform="bist")
        assert res.stock_id != shortcodes["ISCTR"]

    def test_036_partial_isy_no_match(self, service, shortcodes):
        assert service.resolve("ISY", platform="bist") is None

    def test_037_short_code_tk_exact(self, service, shortcodes):
        res = service.resolve("TK", platform="bist")
        assert res.stock_id == shortcodes["TKT"]

    def test_038_tknsa_not_matched_by_tk(self, service, shortcodes):
        res = service.resolve("TKNSA", platform="bist")
        assert res.stock_id == shortcodes["TKNSA"]
        assert res.stock_id != shortcodes["TKT"]

    def test_039_single_letter_a_exact(self, service, shortcodes):
        res = service.resolve("A", platform="bist")
        assert res.stock_id == shortcodes["AYT"]

    def test_040_asels_not_matched_by_a(self, service, shortcodes):
        res = service.resolve("ASELS", platform="bist")
        assert res.stock_id == shortcodes["ASELS"]
        assert res.stock_id != shortcodes["AYT"]

    def test_041_short_code_without_platform(self, service, shortcodes):
        res = service.resolve("IS")
        assert res.stock_id == shortcodes["ISGM"]

    def test_042_turkish_dotted_i_query(self, service, shortcodes):
        # "İs" -> "IS"
        res = service.resolve("İs", platform="bist")
        assert res.stock_id == shortcodes["ISGM"]

    def test_043_turkish_dotless_i_query(self, service, shortcodes):
        # "ıs" -> "IS"
        res = service.resolve("ıs", platform="bist")
        assert res.stock_id == shortcodes["ISGM"]

    def test_044_isb_symbol_resolves_to_own_stock(self, service, shortcodes):
        res = service.resolve("ISB", platform="bist")
        assert res.stock_id == shortcodes["ISBM"]
        assert res.stock_id != shortcodes["ISGM"]

    def test_045_token_subset_no_match(self, service, shortcodes):
        # "IS Girişim" tokenleri "IS Girişim Sermayesi"nin alt kumesi -> eslesme yok
        assert service.resolve("IS Girişim") is None

    def test_046_substring_never_matches(self, service, shortcodes):
        assert service.resolve("SCTR", platform="bist") is None
        assert service.resolve("SELS", platform="bist") is None
        assert service.resolve("KNSA", platform="bist") is None


# ===========================================================================
# KATEGORI 4: Kod degisikligi / eski kod gecmisi - 16
# ===========================================================================
@pytest.fixture
def hist(service):
    sid = service.register_stock("Değişken Kodlu Şirket")
    service.add_symbol(sid, "bist", "OLDK", valid_from=date(2020, 1, 1))
    return sid


class TestCodeChangeHistory:
    def test_047_change_creates_two_history_records(self, service, hist):
        service.change_symbol(hist, "bist", "NEWK", date(2023, 6, 1))
        records = service.get_symbol_history(hist, "bist")
        assert len(records) == 2

    def test_048_old_record_closed(self, service, hist):
        service.change_symbol(hist, "bist", "NEWK", date(2023, 6, 1))
        old = [r for r in service.get_symbol_history(hist, "bist") if r.symbol == "OLDK"][0]
        assert old.is_active is False
        assert old.valid_to == date(2023, 6, 1)

    def test_049_new_record_open(self, service, hist):
        service.change_symbol(hist, "bist", "NEWK", date(2023, 6, 1))
        new = [r for r in service.get_symbol_history(hist, "bist") if r.symbol == "NEWK"][0]
        assert new.is_active is True
        assert new.valid_from == date(2023, 6, 1)
        assert new.valid_to is None

    def test_050_get_active_symbol_after_change(self, service, hist):
        service.change_symbol(hist, "bist", "NEWK", date(2023, 6, 1))
        assert service.get_active_symbol(hist, "bist") == "NEWK"

    def test_051_resolve_new_symbol(self, service, hist):
        service.change_symbol(hist, "bist", "NEWK", date(2023, 6, 1))
        res = service.resolve("NEWK", platform="bist")
        assert res.stock_id == hist
        assert res.historical is False

    def test_052_resolve_old_symbol_active_only_none(self, service, hist):
        service.change_symbol(hist, "bist", "NEWK", date(2023, 6, 1))
        assert service.resolve("OLDK", platform="bist") is None

    def test_053_resolve_old_code_finds_stock(self, service, hist):
        service.change_symbol(hist, "bist", "NEWK", date(2023, 6, 1))
        res = service.resolve_old_code("OLDK", "bist")
        assert res is not None
        assert res.stock_id == hist
        assert res.historical is True
        assert res.matched_by == "historical_symbol"

    def test_054_resolve_on_date_before_change(self, service, hist):
        service.change_symbol(hist, "bist", "NEWK", date(2023, 6, 1))
        res = service.resolve("OLDK", platform="bist", on_date=date(2022, 1, 1))
        assert res.stock_id == hist
        assert res.historical is True

    def test_055_resolve_on_date_after_change(self, service, hist):
        service.change_symbol(hist, "bist", "NEWK", date(2023, 6, 1))
        res = service.resolve("NEWK", platform="bist", on_date=date(2024, 1, 1))
        assert res.stock_id == hist
        assert res.historical is False

    def test_056_resolve_on_effective_date_boundary(self, service, hist):
        service.change_symbol(hist, "bist", "NEWK", date(2023, 6, 1))
        # Gecerlilik: valid_from <= d < valid_to -> sinir gununde yeni kod gecerli
        assert service.resolve("OLDK", platform="bist", on_date=date(2023, 6, 1)) is None
        res = service.resolve("NEWK", platform="bist", on_date=date(2023, 6, 1))
        assert res.stock_id == hist

    def test_057_audit_written_on_change(self, service, hist):
        service.change_symbol(hist, "bist", "NEWK", date(2023, 6, 1))
        logs = service.get_audit_log(hist)
        assert len(logs) == 1
        entry = logs[0]
        assert entry.action == "CHANGE_SYMBOL"
        assert entry.old_symbol == "OLDK"
        assert entry.new_symbol == "NEWK"
        assert entry.admin_user == "system"
        assert entry.platform == "bist"

    def test_058_old_symbol_not_deleted(self, service, hist):
        service.change_symbol(hist, "bist", "NEWK", date(2023, 6, 1))
        symbols = [r.symbol for r in service.get_symbol_history(hist, "bist")]
        assert symbols == ["OLDK", "NEWK"]  # eski kayit korunur, sirali

    def test_059_multiple_changes_chain(self, service, hist):
        service.change_symbol(hist, "bist", "MIDK", date(2021, 1, 1))
        service.change_symbol(hist, "bist", "NEWK", date(2023, 6, 1))
        records = service.get_symbol_history(hist, "bist")
        assert [r.symbol for r in records] == ["OLDK", "MIDK", "NEWK"]
        res = service.resolve_old_code("MIDK", "bist")
        assert res.stock_id == hist
        assert res.historical is True
        assert service.get_active_symbol(hist, "bist") == "NEWK"

    def test_060_change_to_conflicting_symbol_raises(self, service, hist):
        other = service.register_stock("Rakip Şirket")
        service.add_symbol(other, "bist", "NEWK")
        with pytest.raises(DuplicateSymbolError):
            service.change_symbol(hist, "bist", "NEWK", date(2023, 6, 1))
        # Degisiklik uygulanmamis olmali
        assert service.get_active_symbol(hist, "bist") == "OLDK"
        assert len(service.get_symbol_history(hist, "bist")) == 1

    def test_061_change_without_active_symbol_raises(self, service, hist):
        with pytest.raises(SymbolNotFoundError) as exc:
            service.change_symbol(hist, "yahoo", "XXXX.IS", date(2023, 6, 1))
        assert exc.value.code == "SYMBOL_NOT_FOUND"

    def test_062_admin_update_symbol_writes_audit(self, service, hist):
        admin = SymbolAdmin(service)
        entry = admin.admin_update_symbol(
            "admin1", hist, "bist", "ADMN", reason="kod guncelleme"
        )
        assert entry.action == "CHANGE_SYMBOL"
        assert entry.admin_user == "admin1"
        assert entry.reason == "kod guncelleme"
        assert entry.old_symbol == "OLDK"
        assert entry.new_symbol == "ADMN"
        assert service.get_active_symbol(hist, "bist") == "ADMN"
        # admin_user bos olamaz
        with pytest.raises(ValueError):
            admin.admin_update_symbol("", hist, "bist", "XXXX", reason="r")


# ===========================================================================
# KATEGORI 5: KAP kimligi + link dogrulama (mock http) - 14
# ===========================================================================
@pytest.fixture
def kap_env(service):
    ids = {}
    ids["A"] = service.register_stock("Kap A Şirketi")
    ids["B"] = service.register_stock("Kap B Şirketi")
    ids["C"] = service.register_stock("Kap C Şirketi")
    ids["D"] = service.register_stock("Kap D Şirketi")
    urls = {
        "A": "https://kap.example.com/a",
        "B": "https://kap.example.com/b",
        "C": "https://kap.example.com/c",
        "D": "https://kap.example.com/d",
    }
    for key, url in urls.items():
        service.set_kap_link(ids[key], url)
    client = MockHttpClient(
        routes={urls["A"]: 200, urls["B"]: 404, urls["D"]: 500},
        errors={urls["C"]: TimeoutError("baglanti zaman asimi")},
    )
    return ids, urls, client


class TestKapLinkVerification:
    def test_063_verify_valid_link_200(self, service, kap_env):
        ids, urls, client = kap_env
        verifier = KapVerifier(service, http_client=client)
        assert verifier.verify(ids["A"]) == KapLinkStatus.KAP_LINK_VALID

    def test_064_verify_updates_last_checked(self, service, kap_env):
        ids, urls, client = kap_env
        verifier = KapVerifier(service, http_client=client)
        verifier.verify(ids["A"])
        link = service.get_kap_link(ids["A"])
        assert link.last_checked_at == FIXED_NOW

    def test_065_verify_404_broken(self, service, kap_env):
        ids, urls, client = kap_env
        verifier = KapVerifier(service, http_client=client)
        assert verifier.verify(ids["B"]) == KapLinkStatus.KAP_LINK_BROKEN

    def test_066_fail_count_increments(self, service, kap_env):
        ids, urls, client = kap_env
        verifier = KapVerifier(service, http_client=client)
        verifier.verify(ids["B"])
        assert service.get_kap_link(ids["B"]).fail_count == 1
        verifier.verify(ids["B"])
        assert service.get_kap_link(ids["B"]).fail_count == 2

    def test_067_no_http_client_returns_unchecked(self, service, kap_env):
        ids, urls, _ = kap_env
        verifier = KapVerifier(service, http_client=None)
        assert verifier.verify(ids["A"]) == KapLinkStatus.KAP_LINK_UNCHECKED

    def test_068_no_http_client_no_state_change(self, service, kap_env):
        ids, urls, _ = kap_env
        verifier = KapVerifier(service, http_client=None)
        verifier.verify(ids["A"])
        link = service.get_kap_link(ids["A"])
        # Gercek ag cagrisi yapilmadi: hicbir durum degismedi
        assert link.last_checked_at is None
        assert link.fail_count == 0
        assert link.status == KapLinkStatus.KAP_LINK_UNCHECKED

    def test_069_timeout_is_broken(self, service, kap_env):
        ids, urls, client = kap_env
        verifier = KapVerifier(service, http_client=client)
        assert verifier.verify(ids["C"]) == KapLinkStatus.KAP_LINK_BROKEN

    def test_070_http_500_is_broken(self, service, kap_env):
        ids, urls, client = kap_env
        verifier = KapVerifier(service, http_client=client)
        assert verifier.verify(ids["D"]) == KapLinkStatus.KAP_LINK_BROKEN

    def test_071_success_resets_fail_count(self, service, kap_env):
        ids, urls, client = kap_env
        verifier = KapVerifier(service, http_client=client)
        verifier.verify(ids["B"])
        verifier.verify(ids["B"])
        assert service.get_kap_link(ids["B"]).fail_count == 2
        client.routes[urls["B"]] = 200  # link duzeldi
        assert verifier.verify(ids["B"]) == KapLinkStatus.KAP_LINK_VALID
        assert service.get_kap_link(ids["B"]).fail_count == 0

    def test_072_three_failures_create_pending(self, service, kap_env):
        ids, urls, client = kap_env
        verifier = KapVerifier(service, http_client=client)
        for _ in range(3):
            verifier.verify(ids["B"])
        pending = service.get_pending_queue()
        assert any(item.stock_id == ids["B"] for item in pending)

    def test_073_pending_reason_and_stock_status(self, service, kap_env):
        ids, urls, client = kap_env
        verifier = KapVerifier(service, http_client=client)
        for _ in range(3):
            verifier.verify(ids["B"])
        items = [i for i in service.get_pending_queue() if i.stock_id == ids["B"]]
        assert len(items) == 1
        assert items[0].reason == REASON_KAP_LINK_BROKEN
        assert (
            service.get_stock(ids["B"]).status
            == VerificationStatus.SYMBOL_VERIFICATION_PENDING
        )

    def test_074_run_periodic_check_all_links(self, service, kap_env):
        ids, urls, client = kap_env
        verifier = KapVerifier(service, http_client=client)
        results = verifier.run_periodic_check()
        assert set(results.keys()) == {ids["A"], ids["B"], ids["C"], ids["D"]}
        assert results[ids["A"]] == KapLinkStatus.KAP_LINK_VALID

    def test_075_run_periodic_check_broken_statuses(self, service, kap_env):
        ids, urls, client = kap_env
        verifier = KapVerifier(service, http_client=client)
        results = verifier.run_periodic_check()
        assert results[ids["B"]] == KapLinkStatus.KAP_LINK_BROKEN
        assert results[ids["C"]] == KapLinkStatus.KAP_LINK_BROKEN
        assert results[ids["D"]] == KapLinkStatus.KAP_LINK_BROKEN

    def test_076_head_called_with_correct_url(self, service, kap_env):
        ids, urls, client = kap_env
        verifier = KapVerifier(service, http_client=client)
        verifier.verify(ids["A"])
        assert ("HEAD", urls["A"]) in client.calls


# ===========================================================================
# KATEGORI 6: Cift eslestirme (duplicate) senaryolari - 12
# ===========================================================================
@pytest.fixture
def dup_env(service):
    a = service.register_stock("Alfa Şirketi")
    b = service.register_stock("Beta Şirketi")
    service.add_symbol(a, "bist", "ALFA")
    service.add_symbol(b, "bist", "BETA")
    return a, b


class TestDuplicateScenarios:
    def test_077_duplicate_same_platform_raises(self, service, dup_env):
        a, b = dup_env
        with pytest.raises(DuplicateSymbolError):
            service.add_symbol(b, "bist", "ALFA")

    def test_078_duplicate_error_code(self, service, dup_env):
        a, b = dup_env
        with pytest.raises(DuplicateSymbolError) as exc:
            service.add_symbol(b, "bist", "ALFA")
        assert exc.value.code == "DUPLICATE_SYMBOL"
        assert exc.value.details["existing_stock_id"] == a
        assert exc.value.details["attempted_stock_id"] == b

    def test_079_original_mapping_intact_after_failed_duplicate(self, service, dup_env):
        a, b = dup_env
        with pytest.raises(DuplicateSymbolError):
            service.add_symbol(b, "bist", "ALFA")
        assert service.resolve("ALFA", platform="bist").stock_id == a
        assert service.get_active_symbol(b, "bist") == "BETA"

    def test_080_same_symbol_different_platform_allowed(self, service, dup_env):
        a, b = dup_env
        rec = service.add_symbol(b, "yahoo", "ALFA")
        assert rec.symbol == "ALFA"
        assert service.get_active_symbol(b, "yahoo") == "ALFA"

    def test_081_ambiguous_resolve_returns_none(self, service, dup_env):
        a, b = dup_env
        service.add_symbol(b, "yahoo", "ALFA")
        # Platform belirtilmeden "ALFA" iki farkli hisseye isaret ediyor
        assert service.resolve("ALFA") is None

    def test_082_ambiguous_resolve_creates_pending(self, service, dup_env):
        a, b = dup_env
        service.add_symbol(b, "yahoo", "ALFA")
        assert service.resolve("ALFA") is None
        pending_ids = {item.stock_id for item in service.get_pending_queue()}
        assert {a, b} <= pending_ids

    def test_083_platform_disambiguates(self, service, dup_env):
        a, b = dup_env
        service.add_symbol(b, "yahoo", "ALFA")
        assert service.resolve("ALFA", platform="bist").stock_id == a
        assert service.resolve("ALFA", platform="yahoo").stock_id == b

    def test_084_same_name_different_isin_allowed_then_ambiguous(self, service):
        n1 = service.register_stock("Gamma Holding", "TR0000000001")
        n2 = service.register_stock("Gamma Holding", "TR0000000002")
        assert n1 != n2
        # Ayni isimden cozumleme belirsiz -> None + pending
        assert service.resolve("Gamma Holding") is None
        pending_ids = {item.stock_id for item in service.get_pending_queue()}
        assert {n1, n2} <= pending_ids

    def test_085_change_symbol_to_existing_raises(self, service, dup_env):
        a, b = dup_env
        with pytest.raises(DuplicateSymbolError):
            service.change_symbol(b, "bist", "ALFA", FIXED_NOW.date())
        assert service.get_active_symbol(b, "bist") == "BETA"

    def test_086_ambiguous_old_code_returns_none_and_pends(self, service):
        x = service.register_stock("X1 Şirket")
        service.add_symbol(x, "bist", "ESKI", valid_from=date(2020, 1, 1))
        service.change_symbol(x, "bist", "X1N", date(2022, 1, 1))
        y = service.register_stock("X2 Şirket")
        service.add_symbol(y, "bist", "ESKI", valid_from=date(2023, 1, 1))
        service.change_symbol(y, "bist", "X2N", date(2024, 1, 1))
        # "ESKI" kapali kayit olarak iki hissedede var -> belirsiz
        assert service.resolve_old_code("ESKI", "bist") is None
        pending_ids = {item.stock_id for item in service.get_pending_queue()}
        assert {x, y} <= pending_ids

    def test_087_admin_merge_duplicate(self, service, dup_env):
        a, b = dup_env
        admin = SymbolAdmin(service)
        entries = admin.admin_merge_duplicate("admin1", keep_id=a, drop_id=b)
        drop = service.get_stock(b)
        assert drop.status == VerificationStatus.DUPLICATE_SYMBOL
        assert drop.merged_into == a
        actions = [e.action for e in entries]
        assert actions == ["MERGE_DUPLICATE", "MERGE_DUPLICATE"]
        assert all(e.admin_user == "admin1" for e in entries)
        with pytest.raises(ValueError):
            admin.admin_merge_duplicate("", keep_id=a, drop_id=b)

    def test_088_resolve_old_code_after_merge(self, service, dup_env):
        a, b = dup_env
        admin = SymbolAdmin(service)
        admin.admin_merge_duplicate("admin1", keep_id=a, drop_id=b)
        res = service.resolve_old_code("BETA", "bist")
        assert res is not None
        assert res.stock_id == a  # birlestirilen kayda yonlenir
        assert res.historical is True
        # keep kaydinin aktif sembolu etkilenmedi
        assert service.resolve("ALFA", platform="bist").stock_id == a


# ===========================================================================
# KATEGORI 7: Bozuk link + SYMBOL_VERIFICATION_PENDING kuyrugu - 12
# ===========================================================================
@pytest.fixture
def pend(service):
    pid = service.register_stock("Pending Şirketi")
    return pid


class TestPendingQueueAndBrokenLinks:
    def test_089_mark_pending_creates_queue_item(self, service, pend):
        item = service.mark_pending(pend, "SYMBOL_VERIFICATION_PENDING")
        assert item.queue_id == "Q-000001"
        assert item.resolved is False
        assert item in service.get_pending_queue()

    def test_090_mark_pending_sets_stock_status(self, service, pend):
        service.mark_pending(pend, "SYMBOL_VERIFICATION_PENDING")
        assert (
            service.get_stock(pend).status
            == VerificationStatus.SYMBOL_VERIFICATION_PENDING
        )

    def test_091_mark_pending_idempotent(self, service, pend):
        i1 = service.mark_pending(pend, "SYMBOL_VERIFICATION_PENDING")
        i2 = service.mark_pending(pend, "SYMBOL_VERIFICATION_PENDING")
        assert i1.queue_id == i2.queue_id
        assert len(service.get_pending_queue()) == 1

    def test_092_admin_approve_resolves(self, service, pend):
        admin = SymbolAdmin(service)
        item = service.mark_pending(pend, "SYMBOL_VERIFICATION_PENDING")
        entry = admin.admin_resolve_pending("admin1", item.queue_id, True, "onaylandi")
        assert item.resolved is True
        assert item.resolved_by == "admin1"
        assert item.resolved_at == FIXED_NOW
        assert item.note == "onaylandi"
        assert service.get_stock(pend).status == VerificationStatus.VERIFIED
        assert entry.action == "RESOLVE_PENDING"
        assert entry in admin.get_audit_log(pend)

    def test_093_admin_reject_sets_rejected(self, service, pend):
        admin = SymbolAdmin(service)
        item = service.mark_pending(pend, "SYMBOL_VERIFICATION_PENDING")
        admin.admin_resolve_pending("admin2", item.queue_id, False, "red nedeni")
        assert item.resolved is True
        assert item.resolved_by == "admin2"
        assert service.get_stock(pend).status == VerificationStatus.REJECTED

    def test_094_admin_user_required(self, service, pend):
        admin = SymbolAdmin(service)
        item = service.mark_pending(pend, "SYMBOL_VERIFICATION_PENDING")
        with pytest.raises(ValueError):
            admin.admin_resolve_pending("", item.queue_id, True)
        with pytest.raises(ValueError):
            admin.admin_resolve_pending(None, item.queue_id, True)
        # Basarisiz deneme kaydi cozmemis olmali
        assert item.resolved is False

    def test_095_unknown_queue_id_raises(self, service, pend):
        admin = SymbolAdmin(service)
        with pytest.raises(QueueItemNotFoundError) as exc:
            admin.admin_resolve_pending("admin1", "Q-999999", True)
        assert exc.value.code == "QUEUE_ITEM_NOT_FOUND"

    def test_096_two_kap_failures_no_pending_yet(self, service):
        sid = service.register_stock("Kap Fail Şirketi")
        service.set_kap_link(sid, "https://kap.example.com/fail")
        client = MockHttpClient(routes={"https://kap.example.com/fail": 404})
        verifier = KapVerifier(service, http_client=client)
        verifier.verify(sid)
        verifier.verify(sid)
        assert service.get_kap_link(sid).fail_count == 2
        assert service.get_pending_queue() == []

    def test_097_third_kap_failure_pends_then_approve(self, service):
        sid = service.register_stock("Kap Fail Şirketi")
        service.set_kap_link(sid, "https://kap.example.com/fail")
        client = MockHttpClient(routes={"https://kap.example.com/fail": 404})
        verifier = KapVerifier(service, http_client=client)
        for _ in range(3):
            verifier.verify(sid)
        items = [i for i in service.get_pending_queue() if i.stock_id == sid]
        assert len(items) == 1
        assert items[0].reason == REASON_KAP_LINK_BROKEN
        assert (
            service.get_stock(sid).status
            == VerificationStatus.SYMBOL_VERIFICATION_PENDING
        )
        admin = SymbolAdmin(service)
        admin.admin_resolve_pending("admin1", items[0].queue_id, True, "link duzeltildi")
        assert service.get_stock(sid).status == VerificationStatus.VERIFIED
        assert service.get_pending_queue() == []

    def test_098_adapter_mapping_known_unknown(self, service):
        sid = service.register_stock("Türk Hava Yolları")
        service.add_symbol(sid, "bist", "THYAO")
        adapter = IdentityAdapter(service)
        result = adapter.resolve_universe_symbols(["THYAO", "UNKNOWN1"])
        assert result == {"THYAO": sid, "UNKNOWN1": None}

    def test_099_adapter_unknown_goes_pending(self, service):
        adapter = IdentityAdapter(service)
        result = adapter.resolve_universe_symbols(["UNKNOWN1", "UNKNOWN2"])
        assert result == {"UNKNOWN1": None, "UNKNOWN2": None}
        pending = service.get_pending_queue()
        assert len(pending) == 2
        queries = {item.query for item in pending}
        assert queries == {"UNKNOWN1", "UNKNOWN2"}
        assert all(item.reason == REASON_UNRESOLVED_UNIVERSE_SYMBOL for item in pending)
        assert all(item.stock_id is None for item in pending)

    def test_100_adapter_all_known_no_pending(self, service):
        t = service.register_stock("Türk Hava Yolları")
        service.add_symbol(t, "bist", "THYAO")
        i = service.register_stock("Türkiye İş Bankası C")
        service.add_symbol(i, "bist", "ISCTR")
        adapter = IdentityAdapter(service)
        result = adapter.resolve_universe_symbols(["THYAO", "ISCTR"])
        assert result == {"THYAO": t, "ISCTR": i}
        assert service.get_pending_queue() == []
