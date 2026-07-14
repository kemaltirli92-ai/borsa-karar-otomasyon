"""BLOK 20 - Mobil Uygulama Entegrasyonu: TAM 100 pytest testi.

Statik analiz testleri: telegram-sender/ (index.html, manifest.webmanifest,
sw.js) ve borsa-karar-otomasyon/docs/api-contract.json +
app/services/stock_scanning/events.py incelenir (ag/soket erisimi YOK;
EventBus fonksiyonel testleri bellek icinde calisir).

Kategori dagilimi (SPEC-BLOK20 bolum 2, toplam = 100):
1. API sozlesmesi: docs/api-contract.json gecerli JSON, 13 ekran eslemesi,
   zarf alanlari, HAZIR_BEKLIYOR, hata formati (16)
2. PWA: manifest alanlari, sw.js varligi, cache stratejileri, x-cached-at (14)
3. Cevrimdisi: offline-banner, CEVRIMDISI VERI + SON GUNCELLEME, eski
   onbellek canli gibi sunulmaz isareti (14)
4. Responsive/mobil tasma: viewport, touch-target 44px, scroll-wrap,
   alt-sheet (14)
5. Dokunmatik: tiklanabilir elemanlar min 44px, sayfalama/filtre
   dokunmatik dostu (10)
6. Grafik performansi: dpr siniri, resize debounce, downsample mantigi (10)
7. Bildirim kurallari: 3 dahili olay, musteri bildirim fonksiyonu YOK,
   EventBus emit/get (12)
8. Native isareti + mevcut icerik korunur (BLOK 18/19 ogeleri hala
   mevcut) (10)

Dosya yolu test icinde cift adayli cozumlenir:
tests/blok20/test_mobile_integration.py -> ../../.. -> telegram-sender/ (yerel)
-> borsa-karar-otomasyon/ (GitHub repo koku)
"""
from __future__ import annotations

import inspect
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INDEX_CANDIDATES = [
    _REPO_ROOT.parent / "telegram-sender" / "index.html",  # yerel calisma dizini
    _REPO_ROOT / "index.html",                             # GitHub repo koku
]
INDEX_HTML = next((p for p in _INDEX_CANDIDATES if p.is_file()), _INDEX_CANDIDATES[-1])
SITE_DIR = INDEX_HTML.parent
MANIFEST = SITE_DIR / "manifest.webmanifest"
SW_JS = SITE_DIR / "sw.js"
CONTRACT_JSON = _REPO_ROOT / "docs" / "api-contract.json"
EVENTS_PY = _REPO_ROOT / "app" / "services" / "stock_scanning" / "events.py"

# BLOK 16'daki 10 musteri ucu (api-contract ekran eslemesi bunlari kullanir)
CUSTOMER_ENDPOINTS = {
    "GET /api/stocks/universe/xk100",
    "GET /api/stocks/{symbol}",
    "GET /api/stocks/{symbol}/scan/latest",
    "GET /api/stocks/{symbol}/prices",
    "GET /api/stocks/{symbol}/kap",
    "GET /api/stocks/{symbol}/news",
    "GET /api/stocks/{symbol}/corporate-actions",
    "GET /api/stocks/{symbol}/restrictions",
    "GET /api/xk100/scan/latest",
    "GET /api/xk100/stocks",
}

_CSS20_START = "/* ===== BLOK 20:"
_CSS20_END = "/* ===== BLOK 20 CSS SON ===== */"


@pytest.fixture(scope="module")
def html() -> str:
    assert INDEX_HTML.is_file(), f"index.html bulunamadi: {INDEX_HTML}"
    return INDEX_HTML.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def manifest() -> dict:
    assert MANIFEST.is_file(), f"manifest.webmanifest bulunamadi: {MANIFEST}"
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def sw() -> str:
    assert SW_JS.is_file(), f"sw.js bulunamadi: {SW_JS}"
    return SW_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def contract() -> dict:
    assert CONTRACT_JSON.is_file(), f"api-contract.json bulunamadi: {CONTRACT_JSON}"
    return json.loads(CONTRACT_JSON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def css20(html: str) -> str:
    """BLOK 20 CSS dilimi."""
    s = html.find(_CSS20_START)
    assert s != -1, "BLOK 20 CSS baslangic marker yok"
    e = html.find(_CSS20_END, s)
    assert e != -1, "BLOK 20 CSS SON marker yok"
    return html[s:e]


def section(text: str, start_marker: str, end_marker: str) -> str:
    s = text.find(start_marker)
    assert s != -1, f"baslangic marker yok: {start_marker}"
    e = text.find(end_marker, s)
    assert e != -1, f"bitis marker yok: {end_marker}"
    return text[s:e]


# ======================================================================
# 1. API SOZLESMESI (16 test) — docs/api-contract.json
# ======================================================================
class TestApiContract:
    def test_contract_file_exists(self):
        assert CONTRACT_JSON.is_file()

    def test_contract_valid_json(self):
        data = json.loads(CONTRACT_JSON.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_version_1_0_0(self, contract):
        assert contract["version"] == "1.0.0"

    def test_base_api(self, contract):
        assert contract["base"] == "/api"

    def test_envelope_scan_run_id(self, contract):
        assert "scan_run_id" in contract["envelope"]["fields"]

    def test_envelope_report_version(self, contract):
        assert "report_version" in contract["envelope"]["fields"]

    def test_envelope_last_updated_at(self, contract):
        assert "last_updated_at" in contract["envelope"]["fields"]

    def test_envelope_data_cutoff_at(self, contract):
        assert "data_cutoff_at" in contract["envelope"]["fields"]

    def test_envelope_status(self, contract):
        assert "status" in contract["envelope"]["fields"]

    def test_envelope_status_values(self, contract):
        assert contract["envelope"]["status_values"] == ["OK", "PARTIAL", "FAILED", "STALE"]

    def test_screens_count_13(self, contract):
        assert len(contract["screens"]) == 13

    def test_screens_have_endpoints(self, contract):
        for scr in contract["screens"]:
            assert scr.get("endpoints"), f"ekran uclari bos: {scr.get('screen')}"
            for ep in scr["endpoints"]:
                assert ep.startswith("GET /api/"), f"uc /api altinda degil: {ep}"

    def test_all_10_customer_endpoints_mapped(self, contract):
        used = set()
        for scr in contract["screens"]:
            used.update(scr["endpoints"])
        assert used == CUSTOMER_ENDPOINTS

    def test_error_format(self, contract):
        ef = contract["error_format"]
        assert "error" in ef["shape"] and "error_id" in ef["shape"]
        assert set(ef["fields"]) == {"error", "error_id"}

    def test_native_status_hazir_bekliyor(self, contract):
        assert contract["native_mobile"]["status"] == "HAZIR_BEKLIYOR"

    def test_web_mobile_same_envelope_rule(self, contract):
        rule = contract["envelope"]["run_id_rule"]
        assert "scan_run_id" in rule and "ayn" in rule


# ======================================================================
# 2. PWA (14 test) — manifest.webmanifest + sw.js + manifest linki
# ======================================================================
class TestPwa:
    def test_manifest_exists(self):
        assert MANIFEST.is_file()

    def test_manifest_valid_json(self):
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_manifest_name(self, manifest):
        assert manifest["name"] == "XK100 Borsa"

    def test_manifest_short_name(self, manifest):
        assert manifest.get("short_name")

    def test_manifest_start_url(self, manifest):
        assert manifest["start_url"] == "index.html"

    def test_manifest_display_standalone(self, manifest):
        assert manifest["display"] == "standalone"

    def test_manifest_theme_color(self, manifest):
        assert manifest["theme_color"] == "#07130b"

    def test_manifest_icons_192_512(self, manifest):
        icons = manifest["icons"]
        assert len(icons) == 2
        sizes = {ic["sizes"] for ic in icons}
        assert sizes == {"192x192", "512x512"}
        for ic in icons:
            assert ic["src"] == "logo-aiborsam2.png"

    def test_sw_exists(self):
        assert SW_JS.is_file()

    def test_sw_shell_cache_first(self, sw):
        assert "cacheFirstShell" in sw
        for asset in ("index.html", "logo-aiborsam2.png", "favicon-xk100.png"):
            assert asset in sw, f"kabuk varligi sw.js icinde yok: {asset}"

    def test_sw_api_network_first(self, sw):
        assert "networkFirstApi" in sw
        assert '"/api/"' in sw

    def test_sw_x_cached_at_stamp(self, sw):
        assert "x-cached-at" in sw

    def test_sw_cache_put_api(self, sw):
        assert "API_CACHE" in sw
        assert "cache.put" in sw

    def test_html_manifest_link(self, html):
        assert '<link rel="manifest" href="manifest.webmanifest"' in html


# ======================================================================
# 3. CEVRIMDISI (14 test) — offline banner + eski onbellek etiketi
# ======================================================================
class TestOffline:
    def test_offline_banner_exists(self, html):
        assert 'id="offline-banner"' in html

    def test_offline_banner_hidden_default(self, html):
        assert re.search(r'<div id="offline-banner"[^>]*\bhidden\b', html)

    def test_banner_text_cevrimdisi_veri(self, html):
        blk = section(html, 'id="offline-banner"', "</div>")
        assert "CEVRIMDISI VERI" in blk

    def test_banner_text_son_guncelleme(self, html):
        blk = section(html, 'id="offline-banner"', "</div>")
        assert "SON GUNCELLEME" in blk

    def test_banner_date_span(self, html):
        assert 'id="offline-banner-date"' in html

    def test_sw_stamps_iso_timestamp(self, sw):
        assert "new Date().toISOString()" in sw

    def test_sw_cache_fallback_on_failure(self, sw):
        assert ".catch(" in sw
        assert "cache.match" in sw

    def test_sw_stale_notice_postmessage(self, sw):
        assert "B20_STALE_SERVED" in sw
        assert "postMessage" in sw

    def test_client_listens_sw_messages(self, html):
        assert "serviceWorker" in html
        assert 'addEventListener("message"' in html

    def test_client_shows_banner_on_stale(self, html):
        assert "B20_STALE_SERVED" in html
        assert "b20ShowOffline" in html

    def test_banner_css_present(self, html):
        style = section(html, "<style>", "</style>")
        assert "#offline-banner" in style

    def test_stale_not_presented_as_live(self, html, sw):
        # kural isareti: eski onbellek canli veri gibi SUNULMAZ (acik etiket zorunlu)
        assert "SUNULMAZ" in html
        assert "SUNULMAZ" in sw

    def test_sw_registration(self, html):
        assert "serviceWorker.register" in html
        assert "sw.js" in html

    def test_online_offline_events(self, html):
        assert 'addEventListener("offline"' in html
        assert 'addEventListener("online"' in html


# ======================================================================
# 4. RESPONSIVE / MOBIL TASMA (14 test)
# ======================================================================
class TestResponsive:
    def test_viewport_meta_present(self, html):
        assert '<meta name="viewport"' in html

    def test_viewport_device_width(self, html):
        m = re.search(r'<meta name="viewport" content="([^"]+)"', html)
        assert m and "width=device-width" in m.group(1)

    def test_viewport_initial_scale(self, html):
        m = re.search(r'<meta name="viewport" content="([^"]+)"', html)
        assert m and "initial-scale=1" in m.group(1)

    def test_media_query_640_exists(self, html):
        assert "@media (max-width:640px)" in html

    def test_blok20_css_marker(self, html):
        assert "/* ===== BLOK 20:" in html

    def test_scroll_wrap_overflow_x(self, css20):
        assert ".stk-wrap{overflow-x:auto" in css20

    def test_scroll_wrap_touch_scrolling(self, css20):
        assert "-webkit-overflow-scrolling:touch" in css20

    def test_scroll_wrap_max_width(self, css20):
        assert re.search(r"\.stk-wrap\{[^}]*max-width:100vw", css20)

    def test_detail_panel_max_width_100vw(self, html):
        assert "max-width:100vw" in html

    def test_bottom_sheet_rounded_top(self, css20):
        assert "border-radius:16px 16px 0 0" in css20

    def test_bottom_sheet_align_end(self, css20):
        assert re.search(r"\.stk-detail\{[^}]*align-items:flex-end", css20)

    def test_stk_cards_preserved(self, html):
        assert '<div class="stk-cards" id="stk-cards">' in html

    def test_sd_canvas_max_width(self, html):
        assert ".sd-canvas{max-width:100%}" in html

    def test_blok20_css_end_marker(self, html):
        assert "/* ===== BLOK 20 CSS SON ===== */" in html


# ======================================================================
# 5. DOKUNMATIK (10 test) — min 44px dokunmatik hedefler
# ======================================================================
class TestTouchTargets:
    def test_touch_44px_present(self, css20):
        assert "44px" in css20

    def test_filters_touch_target(self, css20):
        assert ".stk-filters input,.stk-filters select{min-height:44px" in css20

    def test_sort_touch_target(self, css20):
        assert ".stk-sort select{min-height:44px" in css20

    def test_pagination_buttons_touch_target(self, css20):
        assert ".stk-page button{min-height:44px" in css20

    def test_table_rows_touch_target(self, css20):
        assert ".stk-table tbody tr{min-height:44px}" in css20

    def test_cards_touch_target(self, css20):
        assert ".stk-cards>*{min-height:44px}" in css20

    def test_detail_close_touch_target(self, css20):
        assert re.search(r"\.sd-close\{[^}]*min-height:44px", css20)

    def test_range_buttons_touch_target(self, css20):
        assert ".sd-range button,.sd-adjust button{min-height:44px}" in css20

    def test_pagination_dom_preserved(self, html):
        assert 'id="page-prev"' in html and 'id="page-next"' in html
        assert 'id="page-size"' in html

    def test_filter_controls_dom_preserved(self, html):
        for fid in ("flt-symbol", "flt-name", "flt-sector", "flt-scan-status",
                    "flt-kap", "flt-news", "flt-measure", "flt-min-confidence"):
            assert f'id="{fid}"' in html, f"filtre kontrolu yok: {fid}"


# ======================================================================
# 6. GRAFIK PERFORMANSI (10 test) — dpr siniri + debounce + downsample
# ======================================================================
class TestChartPerformance:
    def test_cap_dpr_fn_exists(self, html):
        assert "function b20CapDpr()" in html

    def test_dpr_capped_at_2(self, html):
        assert re.search(r"Math\.min\([^)]*,\s*2\)", html)

    def test_downsample_fn_exists(self, html):
        assert "function b20DownsampleForDraw" in html

    def test_downsample_threshold_500(self, html):
        assert "B20_DOWNSAMPLE_THRESHOLD = 500" in html

    def test_raw_data_untouched_note(self, html):
        # ham veri degistirilmez — sadece cizim katmaninda downsample
        assert "HAM VERI DEGISTIRILMEZ" in html

    def test_resize_debounce_fn(self, html):
        assert "function b20Debounce" in html
        assert "clearTimeout" in html and "setTimeout" in html

    def test_debounce_delay_defined(self, html):
        assert "B20_RESIZE_DEBOUNCE_MS = 150" in html

    def test_wrappers_call_originals(self, html):
        assert "b20OrigDrawCandles" in html
        assert "b20OrigDrawVolume" in html

    def test_original_draw_fns_preserved(self, html):
        assert "function drawStockCandles(canvas, bars, events)" in html
        assert "function drawStockVolume(canvas, bars)" in html

    def test_device_pixel_ratio_present(self, html):
        assert "devicePixelRatio" in html


# ======================================================================
# 7. BILDIRIM KURALLARI (12 test) — 3 dahili olay, musteri bildirimi YOK
# ======================================================================
class TestEventRules:
    def test_events_module_exists(self):
        assert EVENTS_PY.is_file()

    def test_scan_event_exactly_3(self):
        from app.services.stock_scanning.events import ScanEvent
        assert len(ScanEvent) == 3

    def test_event_completed(self):
        from app.services.stock_scanning.events import ScanEvent
        assert ScanEvent.STOCK_SCAN_COMPLETED.value == "STOCK_SCAN_COMPLETED"

    def test_event_partial(self):
        from app.services.stock_scanning.events import ScanEvent
        assert ScanEvent.STOCK_SCAN_PARTIAL.value == "STOCK_SCAN_PARTIAL"

    def test_event_failed(self):
        from app.services.stock_scanning.events import ScanEvent
        assert ScanEvent.STOCK_SCAN_FAILED.value == "STOCK_SCAN_FAILED"

    def test_eventbus_class_exists(self):
        from app.services.stock_scanning.events import EventBus
        assert inspect.isclass(EventBus)

    def test_emit_signature(self):
        from app.services.stock_scanning.events import EventBus
        params = list(inspect.signature(EventBus.emit).parameters)
        assert params == ["self", "event", "run_id", "payload"]

    def test_get_events_signature(self):
        from app.services.stock_scanning.events import EventBus
        params = list(inspect.signature(EventBus.get_events).parameters)
        assert params == ["self", "run_id"]

    def test_no_customer_notify_function_names(self):
        # BILDIRIM KILIDI: fonksiyon/oznitelik adinda push/notification/telegram/send YOK
        from app.services.stock_scanning import events as ev
        forbidden = ("push", "notification", "telegram", "send")
        for name in dir(ev):
            low = name.lower()
            for fw in forbidden:
                assert fw not in low, f"yasak isim modulde: {name}"
        src = EVENTS_PY.read_text(encoding="utf-8")
        for m in re.finditer(r"def\s+([A-Za-z_][A-Za-z0-9_]*)", src):
            low = m.group(1).lower()
            for fw in forbidden:
                assert fw not in low, f"yasak fonksiyon adi: {m.group(1)}"

    def test_no_messaging_client_imports(self):
        # musteri bildirimi yapabilecek ag/eposta istemcisi importu YOK
        src = EVENTS_PY.read_text(encoding="utf-8")
        for fw in ("requests", "smtplib", "urllib", "http.client", "socket", "aiohttp"):
            assert not re.search(rf"^\s*(import|from)\s+{re.escape(fw)}\b", src, re.M), fw

    def test_emit_get_functional(self):
        from app.services.stock_scanning.events import EventBus, ScanEvent
        fixed = datetime(2026, 7, 9, 9, 45, tzinfo=timezone.utc)
        bus = EventBus(clock=lambda: fixed)
        rec = bus.emit(ScanEvent.STOCK_SCAN_COMPLETED, "RUN-1", {"scanned": 100})
        assert rec["event"] == "STOCK_SCAN_COMPLETED"
        assert rec["run_id"] == "RUN-1"
        assert rec["at"] == fixed.isoformat()
        assert rec["payload"] == {"scanned": 100}
        bus.emit("STOCK_SCAN_PARTIAL", "RUN-2")
        assert len(bus.get_events()) == 2

    def test_get_events_filter_and_invalid_event(self):
        from app.services.stock_scanning.events import EventBus, ScanEvent
        bus = EventBus()
        bus.emit(ScanEvent.STOCK_SCAN_COMPLETED, "RUN-1")
        bus.emit(ScanEvent.STOCK_SCAN_FAILED, "RUN-2")
        bus.emit(ScanEvent.STOCK_SCAN_PARTIAL, "RUN-1")
        runs = bus.get_events(run_id="RUN-1")
        assert len(runs) == 2
        assert all(r["run_id"] == "RUN-1" for r in runs)
        with pytest.raises(ValueError):
            bus.emit("BOGUS_EVENT", "RUN-3")


# ======================================================================
# 8. NATIVE ISARETI + MEVCUT ICERIK KORUNUR (10 test)
# ======================================================================
class TestNativeMarkerAndPreservation:
    def test_native_note_present(self, html):
        assert "Native mobil uygulama:" in html

    def test_hazir_bekliyor_marker(self, html):
        assert "HAZIR BEKLIYOR" in html

    def test_api_sozlesmesi_hazir_note(self, html):
        assert "API sozlesmesi hazir" in html

    def test_no_fake_native_download(self, html):
        # sahte uygulama butonu/indirme linki YOK
        low = html.lower()
        for fw in ("google play", "app store", "play.google", "apps.apple", ".apk", ".ipa"):
            assert fw not in low, f"sahte native indirme isareti: {fw}"

    def test_blok18_markers_preserved(self, html):
        assert "BLOK 18: XK100 TARAMA DURUMU KARTI" in html
        assert "BLOK 18: 100 HISSE OZETI" in html

    def test_blok19_markers_preserved(self, html):
        assert "BLOK 19: HISSE DETAY PANELI" in html
        assert "BLOK 19 PANEL SON" in html

    def test_stk_table_preserved(self, html):
        assert 'id="stk-table"' in html

    def test_stk_detail_preserved(self, html):
        assert 'id="stk-detail"' in html

    def test_blok18_js_preserved(self, html):
        assert "BLOK 18: API BAGLANTI KATMANI" in html

    def test_tophead_preserved(self, html):
        assert '<div class="tophead">' in html
