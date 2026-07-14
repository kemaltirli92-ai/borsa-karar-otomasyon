"""BLOK 19 - Hisse Detayi ve Ham Fiyat Grafikleri: TAM 100 pytest testi.

Statik analiz testleri: telegram-sender/index.html dosyasi okunur,
string/DOM-benzeri kontroller uygulanir (ag/soket erisimi YOK).

Kategori dagilimi (SPEC-BLOK19 bolum 2, toplam = 100):
1. Grafik veri formati: OHLC 4 alan + volume + tarih ekseni paylasimi +
   validated seri secimi (14)
2. Aralik butonlari: 6 aralik + range parametreleri 30/60/90/180/260/max (12)
3. Eksik/tatil gunu: sifir mum uretimi kodda YOK; bosluk/atla mantigi var (10)
4. Ham/Duzeltilmis etiketleri: 2 buton + acik etiket + pasif durum (10)
5. Kurumsal islem isaretleri: olay isaret katmani + rozet harfleri D/B/S (8)
6. Veri yok durumlari: 5 durum karti + mesajlar (14)
7. Responsive/mobil: @media 640px, max-width:100vw, overflow-x, resize listener (12)
8. API baglanti: 7 ucu fetch, hata durum karti, puan kilidi (12)
9. YASAK LISTESI: Bollinger/POC/RSI/MACD/AL-SAT/destek-direnc kelimeleri
   BLOK 19 grafik kodunda YOK (8)

BLOK 19 dilimi uc ayri bolge olarak cozumlenir (mevcut icerik korunur):
  - CSS:   "/* ===== BLOK 19:" ... "/* ===== BLOK 19 CSS SON ===== */"
  - Panel: "<!-- ===== BLOK 19: HISSE DETAY PANELI" ... "<!-- ===== BLOK 19 PANEL SON ===== -->"
  - JS:    "<!-- ===== BLOK 19: HISSE DETAY + HAM FIYAT GRAFIK MOTORU" ... dosya sonu

Dosya yolu test icinde goreli cozumlenir:
tests/blok19/test_stock_detail.py -> ../../.. -> telegram-sender/index.html
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CANDIDATES = [
    _REPO_ROOT.parent / "telegram-sender" / "index.html",  # yerel calisma dizini
    _REPO_ROOT / "index.html",                             # GitHub repo koku
]
INDEX_HTML = next((p for p in _CANDIDATES if p.is_file()), _CANDIDATES[-1])

_CSS_START = "/* ===== BLOK 19:"
_CSS_END = "/* ===== BLOK 19 CSS SON ===== */"
_PANEL_START = "<!-- ===== BLOK 19: HISSE DETAY PANELI"
_PANEL_END = "<!-- ===== BLOK 19 PANEL SON ===== -->"
_JS_START = "<!-- ===== BLOK 19: HISSE DETAY + HAM FIYAT GRAFIK MOTORU"


@pytest.fixture(scope="module")
def html() -> str:
    assert INDEX_HTML.is_file(), f"index.html bulunamadi: {INDEX_HTML}"
    return INDEX_HTML.read_text(encoding="utf-8")


def section(html: str, start_marker: str, end_marker: str) -> str:
    """html icinde start_marker'dan end_marker'a kadar olan dilimi dondur."""
    s = html.find(start_marker)
    assert s != -1, f"baslangic marker yok: {start_marker}"
    e = html.find(end_marker, s)
    assert e != -1, f"bitis marker yok: {end_marker}"
    return html[s:e]


@pytest.fixture(scope="module")
def css19(html: str) -> str:
    """BLOK 19 CSS dilimi (yasak listesi taramasi buna uygulanir)."""
    return section(html, _CSS_START, _CSS_END)


@pytest.fixture(scope="module")
def panel19(html: str) -> str:
    """BLOK 19 detay paneli HTML dilimi."""
    return section(html, _PANEL_START, _PANEL_END)


@pytest.fixture(scope="module")
def js19(html: str) -> str:
    """BLOK 19 JS dilimi — grafik motoru + API katmani (dosya sonuna kadar)."""
    s = html.find(_JS_START)
    assert s != -1, f"JS baslangic marker yok: {_JS_START}"
    return html[s:]


@pytest.fixture(scope="module")
def slice19(css19: str, panel19: str, js19: str) -> str:
    """BLOK 19'un tamami: CSS + panel + JS (yasak listesi bu dilimde taranir)."""
    return css19 + "\n" + panel19 + "\n" + js19


# ======================================================================
# 1. GRAFIK VERI FORMATI (14 test)
# ======================================================================
class TestChartDataFormat:
    def test_candles_fn_exists(self, js19):
        assert "function drawStockCandles(canvas, bars, events)" in js19

    def test_volume_fn_exists(self, js19):
        assert "function drawStockVolume(canvas, bars)" in js19

    def test_ohlc_open_field(self, js19):
        assert "bar.open" in js19

    def test_ohlc_high_field(self, js19):
        assert "bar.high" in js19

    def test_ohlc_low_field(self, js19):
        assert "bar.low" in js19

    def test_ohlc_close_field(self, js19):
        assert "bar.close" in js19

    def test_volume_field(self, js19):
        assert "bar.volume" in js19

    def test_date_field(self, js19):
        assert "bar.date" in js19

    def test_ohlc_label_explicit(self, panel19):
        assert "Open/High/Low/Close" in panel19

    def test_validated_series_selected(self, js19):
        assert "series.validated" in js19

    def test_shared_axis_fn_exists(self, js19):
        assert "function sdAxisX(i, n, padL, cw)" in js19

    def test_shared_axis_used_by_both_charts(self, js19):
        # sdAxisX: tanim(1) + mum govde(1) + mum etiket(1) + hacim bar(1) +
        # hacim etiket(1) + isaret(1) => her iki grafik AYNI fonksiyonu kullanir
        assert js19.count("sdAxisX(") >= 5

    def test_same_date_axis_comment(self, js19):
        assert "AYNI tarih ekseni" in js19

    def test_chart_canvas_ids(self, panel19):
        assert 'id="sd-candles"' in panel19
        assert 'id="sd-volume"' in panel19


# ======================================================================
# 2. ARALIK BUTONLARI (12 test)
# ======================================================================
class TestRangeButtons:
    def test_range_30(self, panel19):
        assert 'data-range="30"' in panel19

    def test_range_60(self, panel19):
        assert 'data-range="60"' in panel19

    def test_range_90(self, panel19):
        assert 'data-range="90"' in panel19

    def test_range_180(self, panel19):
        assert 'data-range="180"' in panel19

    def test_range_260(self, panel19):
        assert 'data-range="260"' in panel19

    def test_range_max(self, panel19):
        assert 'data-range="max"' in panel19

    def test_label_3ay(self, panel19):
        assert re.search(r'data-range="90"[^>]*>\s*3AY\s*<', panel19)

    def test_label_6ay(self, panel19):
        assert re.search(r'data-range="180"[^>]*>\s*6AY\s*<', panel19)

    def test_label_1yil(self, panel19):
        assert re.search(r'data-range="260"[^>]*>\s*1YIL\s*<', panel19)

    def test_label_maksimum(self, panel19):
        assert re.search(r'data-range="max"[^>]*>\s*MAKSIMUM\s*<', panel19)

    def test_prices_range_param_in_fetch(self, js19):
        assert "/prices?range=" in js19

    def test_allowed_range_values_documented(self, js19):
        assert "30|60|90|180|260|max" in js19


# ======================================================================
# 3. EKSIK/TATIL GUNU (10 test)
# ======================================================================
class TestMissingHolidayDays:
    def test_no_zero_candle_comment(self, js19):
        assert "sifir mum URETILMEZ" in js19

    def test_no_fake_holiday_candle_comment(self, js19):
        assert "tatil gunu: sahte mum OLUSTURMA" in js19

    def test_bar_guard_fn_exists(self, js19):
        assert "function sdBarValid(bar)" in js19

    def test_invalid_bar_skipped(self, js19):
        assert "if (!sdBarValid(bar)) return;" in js19

    def test_missing_record_skipped(self, js19):
        assert "if (!r) return;" in js19

    def test_trading_day_axis_comment(self, js19):
        assert "tarih ekseni yalnizca islem gunlerinden olusur" in js19

    def test_no_random_data_in_blok19(self, js19):
        assert "Math.random" not in js19  # sahte mum/seri uretimi YOK

    def test_positive_price_guard(self, js19):
        assert "bar.close > 0" in js19

    def test_axis_labels_from_trading_days(self, js19):
        assert "bars[i].date" in js19  # eksen etiketleri gercek islem gunlerinden

    def test_no_day_padding_comment(self, js19):
        assert "gun doldurma/padding yapilmaz" in js19


# ======================================================================
# 4. HAM/DUZELTILMIS ETIKETLERI (10 test)
# ======================================================================
class TestRawAdjusted:
    def test_raw_button_id(self, panel19):
        assert 'id="sd-btn-raw"' in panel19

    def test_adjusted_button_id(self, panel19):
        assert 'id="sd-btn-adj"' in panel19

    def test_raw_label_explicit(self, panel19):
        assert ">HAM FIYAT<" in panel19

    def test_adjusted_label_explicit(self, panel19):
        assert ">DUZELTILMIS FIYAT<" in panel19

    def test_adjusted_disabled_when_absent(self, js19):
        assert 'byId("sd-btn-adj").disabled = !hasAdj;' in js19

    def test_adjusted_absent_note(self, panel19):
        assert 'id="sd-adj-note"' in panel19
        assert "duzeltilmis seri yok" in panel19

    def test_selected_button_highlight_class(self, panel19, js19):
        assert 'id="sd-btn-raw" class="sd-sel"' in panel19
        assert "sdSyncAdjustButtons" in js19

    def test_adjusted_series_read(self, js19):
        assert "series.adjusted" in js19

    def test_series_switch_flag(self, js19):
        assert "sd.useAdjusted" in js19

    def test_selected_highlight_comment(self, js19):
        assert "secili olan vurgulu" in js19


# ======================================================================
# 5. KURUMSAL ISLEM ISARETLERI (8 test)
# ======================================================================
class TestCorporateMarkers:
    def test_event_letters_map(self, js19):
        assert "SD_EVENT_LETTERS" in js19

    def test_dividend_letter_d(self, js19):
        assert 'dividend:"D"' in js19

    def test_bonus_letter_b(self, js19):
        assert 'bonus:"B"' in js19

    def test_split_letter_s(self, js19):
        assert 'split:"S"' in js19

    def test_marker_layer_fn(self, js19):
        assert "function sdDrawEventMarkers(" in js19

    def test_letter_badge_drawn_on_chart(self, js19):
        assert "fillText(letter" in js19

    def test_tooltip_like_title_list(self, js19):
        assert "sd-marker-legend" in js19
        assert "tooltip benzeri baslik listesi" in js19

    def test_markers_only_if_api_sends_comment(self, js19):
        assert "API isaret gonderirse" in js19


# ======================================================================
# 6. VERI YOK DURUMLARI (14 test)
# ======================================================================
class TestNoDataStates:
    def test_key_price_data_missing(self, js19):
        assert "PRICE_DATA_MISSING" in js19

    def test_key_limited_data(self, js19):
        assert "LIMITED_DATA" in js19

    def test_key_new_listing(self, js19):
        assert "NEW_LISTING" in js19

    def test_key_pending_review(self, js19):
        assert "PENDING_REVIEW" in js19

    def test_key_trading_halt(self, js19):
        assert "TRADING_HALT" in js19

    def test_title_price_data_missing(self, js19):
        assert "FIYAT VERISI YOK" in js19

    def test_title_limited_data(self, js19):
        assert "SINIRLI VERI" in js19

    def test_title_new_listing(self, js19):
        assert "YENI HALKA ARZ" in js19

    def test_title_pending_review(self, js19):
        assert "DOGRULAMA BEKLIYOR" in js19

    def test_title_trading_halt(self, js19):
        assert "AKTIF ISLEM DURDURMA" in js19

    def test_new_listing_no_backfill_note(self, js19):
        assert "eksik gecmis uretilmez" in js19

    def test_state_map_exists(self, js19):
        assert "SD_STATE_MAP" in js19

    def test_state_card_fn_hides_chart(self, js19):
        assert "function sdShowStateCard(" in js19
        assert 'byId("sd-chart-wrap").hidden = true;' in js19

    def test_state_card_css_classes(self, css19):
        for key in ["PRICE_DATA_MISSING", "LIMITED_DATA", "NEW_LISTING",
                    "PENDING_REVIEW", "TRADING_HALT"]:
            assert f".sd-sc-{key}" in css19


# ======================================================================
# 7. RESPONSIVE/MOBIL (12 test)
# ======================================================================
class TestResponsiveMobile:
    def test_media_640px_in_blok19_css(self, css19):
        assert "@media (max-width:640px)" in css19

    def test_detail_panel_max_width_100vw(self, css19):
        assert re.search(r"\.stk-detail\{[^}]*max-width:100vw", css19)

    def test_detail_panel_overflow_x_hidden(self, css19):
        assert "overflow-x:hidden" in css19

    def test_resize_listener(self, js19):
        assert 'addEventListener("resize"' in js19

    def test_resize_redraws_charts(self, js19):
        assert re.search(r'resize"[^)]*sdRedrawCharts|resize.*sdRedrawCharts', js19, re.S)

    def test_canvas_width_from_container(self, js19):
        assert "getBoundingClientRect()" in js19

    def test_table_scroll_wrap(self, css19):
        assert ".sd-scroll{overflow-x:auto}" in css19

    def test_canvas_full_width_css(self, css19):
        assert ".sd-canvas{width:100%" in css19

    def test_panel_inner_scroll(self, css19):
        assert re.search(r"\.sd-box\{[^}]*max-height:94vh;overflow-y:auto", css19)

    def test_mobile_grid_single_column(self, css19):
        assert ".sd-grid{grid-template-columns:1fr}" in css19

    def test_mobile_buttons_wrap(self, css19):
        assert ".sd-range button,.sd-adjust button{flex:1 1 28%" in css19

    def test_device_pixel_ratio_scaling(self, js19):
        assert "devicePixelRatio" in js19


# ======================================================================
# 8. API BAGLANTI (12 test)
# ======================================================================
class TestApiConnection:
    def test_panel_container_id(self, html):
        assert 'id="stk-detail"' in html

    def test_panel_close_button(self, panel19, js19):
        assert 'id="sd-close"' in panel19
        assert "function sdClose(" in js19

    def test_panel_esc_key(self, js19):
        assert '"Escape"' in js19
        assert "keydown" in js19

    def test_row_click_binding(self, js19):
        assert "function sdBindRowClicks(" in js19
        assert 'byId("stk-tbody")' in js19

    def test_api_base_stocks(self, js19):
        assert '"/api/stocks/"' in js19

    def test_ep_detail_and_scan(self, js19):
        assert '"/scan/latest"' in js19

    def test_ep_kap_and_news(self, js19):
        assert '"/kap"' in js19
        assert '"/news"' in js19

    def test_ep_actions_and_restrictions(self, js19):
        assert '"/corporate-actions"' in js19
        assert '"/restrictions"' in js19

    def test_ep_prices_range(self, js19):
        assert "/prices?range=" in js19

    def test_fetch_error_state_card(self, js19):
        assert "function sdShowStateError(" in js19
        assert "VERI ALINAMADI" in js19
        assert "HENUZ_CALISMA_YOK" in js19

    def test_score_lock_keys(self, js19):
        assert "SD_SCORE_KEYS" in js19
        assert "hisse_skoru" in js19
        assert "stock_score" in js19
        assert "puan" in js19

    def test_score_lock_applied_no_fake(self, js19):
        assert "function sdStripScoreKeys(" in js19
        assert "sdStripScoreKeys((env && env.data)" in js19
        assert "Sahte veri uretilmez" in js19


# ======================================================================
# 9. YASAK LISTESI (8 test) — Bolum 5/6 teknik gostergeleri BLOK 19'da YOK
# ======================================================================
class TestForbiddenList:
    def test_no_bollinger(self, slice19):
        assert "bollinger" not in slice19.lower()

    def test_no_poc(self, slice19):
        assert "poc" not in slice19.lower()

    def test_no_rsi(self, slice19):
        assert "rsi" not in slice19.lower()

    def test_no_macd(self, slice19):
        assert "macd" not in slice19.lower()

    def test_no_fibonacci(self, slice19):
        assert "fibonacci" not in slice19.lower()

    def test_no_moving_average(self, slice19):
        assert "hareketli ortalama" not in slice19.lower()

    def test_no_support_resistance(self, slice19):
        low = slice19.lower()
        assert "destek" not in low
        assert "direnc" not in low

    def test_no_signal_panel(self, slice19):
        low = slice19.lower()
        assert "al/sat" not in low
        assert "gosterge" not in low
        assert "teknik al" not in low
