"""BLOK 18 - Musteri Ana Sayfasi ve 100 Hisse Ozeti: TAM 100 pytest testi.

Statik analiz testleri: telegram-sender/index.html dosyasi okunur,
string/DOM-benzeri kontroller uygulanir (ag/soket erisimi YOK).

Kategori dagilimi (SPEC-BLOK18 bolum 3, toplam = 100):
1. XK100 Tarama Durumu karti: 8 alan id'leri + kart + baslik (10)
2. 100 hisse tablosu: 17 sutun basligi + hacim_turu rozeti + ready rozetleri (16)
3. Filtreler: 8 filtre kontrolu + etiketler + JS baglantisi (12)
4. Siralama: 3 siralama secenegi + yon asc/desc (8)
5. Sayfalama: 25/50/100 secimi, sayfa kontrolleri, tek-cevapta-100 yok (14)
6. Mobil tasma: @media (max-width:640px) + kart listesi sinifi (10)
7. DEMO isaretleri: sabit tarih/endeks/favori/ASELS/portfoy DEMO bantlari (14)
8. API baglanti + puan kilidi: fetch uclari, zarf dogrulama, hata maskesi,
   skor anahtarlari filtresi, sahte veri uretimi YOK (16)

Dosya yolu test icinde goreli cozumlenir:
tests/blok18/test_index_page.py -> ../../.. -> telegram-sender/index.html
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

INDEX_HTML = Path(__file__).resolve().parents[3] / "telegram-sender" / "index.html"


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


EXPECTED_COLUMNS = [
    "hisse_kodu",
    "sirket_kisa_adi",
    "sektor",
    "son_dogrulanmis_kapanis",
    "son_islem_tarihi",
    "gunluk_yuzde_degisim",
    "islem_miktari",
    "tl_hacim",
    "hacim_orani_20",
    "veri_guveni",
    "tarama_durumu",
    "kap_sayisi",
    "haber_sayisi",
    "kurumsal_islem_rozeti",
    "aktif_tedbir_rozeti",
    "technical_ready",
    "scoring_ready",
]


# ======================================================================
# 1. XK100 TARAMA DURUMU KARTI (10 test)
# ======================================================================
class TestScanCard:
    def test_scan_card_container(self, html):
        assert 'id="xk100-scan-card"' in html

    def test_scan_card_title(self, html):
        assert "XK100 Tarama Durumu" in html

    def test_scan_field_status(self, html):
        assert 'id="xk100-scan-status"' in html

    def test_scan_field_scanned_count_x_of_100(self, html):
        assert 'id="xk100-scanned-count"' in html
        assert "/100" in html  # Taranan hisse: X/100

    def test_scan_field_full_count(self, html):
        assert 'id="xk100-full-count"' in html

    def test_scan_field_partial_count(self, html):
        assert 'id="xk100-partial-count"' in html

    def test_scan_field_failed_count(self, html):
        assert 'id="xk100-failed-count"' in html

    def test_scan_field_avg_confidence(self, html):
        assert 'id="xk100-avg-confidence"' in html

    def test_scan_field_last_updated(self, html):
        assert 'id="xk100-last-updated"' in html

    def test_scan_field_scan_run_id(self, html):
        assert 'id="xk100-scan-run-id"' in html


# ======================================================================
# 2. 100 HISSE TABLOSU — 17 SUTUN (16 test)
# ======================================================================
class TestStocksTable:
    def test_table_exists(self, html):
        assert '<table class="stk-table" id="stk-table">' in html

    def test_tbody_exists(self, html):
        assert '<tbody id="stk-tbody">' in html

    def test_exactly_17_columns(self, html):
        cols = re.findall(r'<th data-col="([^"]+)"', html)
        assert len(cols) == 17, f"17 sutun bekleniyor, {len(cols)} bulundu: {cols}"

    def test_columns_match_spec_order(self, html):
        cols = re.findall(r'<th data-col="([^"]+)"', html)
        assert cols == EXPECTED_COLUMNS

    def test_col_hisse_kodu(self, html):
        assert '<th data-col="hisse_kodu">' in html

    def test_col_sirket_kisa_adi(self, html):
        assert '<th data-col="sirket_kisa_adi">' in html

    def test_col_sektor(self, html):
        assert '<th data-col="sektor">' in html

    def test_col_son_dogrulanmis_kapanis(self, html):
        assert '<th data-col="son_dogrulanmis_kapanis">' in html

    def test_col_son_islem_tarihi(self, html):
        assert '<th data-col="son_islem_tarihi">' in html

    def test_col_gunluk_yuzde_degisim(self, html):
        assert '<th data-col="gunluk_yuzde_degisim">' in html

    def test_col_islem_miktari(self, html):
        assert '<th data-col="islem_miktari">' in html

    def test_col_tl_hacim_ve_hacim_turu_rozeti(self, html):
        assert '<th data-col="tl_hacim">' in html
        assert "hacim_turu" in html  # rozet alani

    def test_hacim_turu_badge_classes(self, html):
        for badge in ("roz-OFFICIAL", "roz-PROVIDER", "roz-ESTIMATED", "roz-MISSING"):
            assert badge in html, f"hacim_turu rozeti eksik: {badge}"

    def test_col_hacim_orani_20(self, html):
        assert '<th data-col="hacim_orani_20">' in html

    def test_col_veri_guveni_ve_tarama_durumu(self, html):
        assert '<th data-col="veri_guveni">' in html
        assert '<th data-col="tarama_durumu">' in html

    def test_ready_rozetleri(self, html):
        assert '<th data-col="technical_ready">' in html
        assert '<th data-col="scoring_ready">' in html
        assert "roz-ready" in html and "roz-notready" in html


# ======================================================================
# 3. FILTRELER — 8 KONTROL (12 test)
# ======================================================================
class TestFilters:
    def test_filter_container(self, html):
        assert 'id="stk-filters"' in html

    def test_flt_symbol_text_input(self, html):
        assert '<input type="text" id="flt-symbol"' in html

    def test_flt_name_text_input(self, html):
        assert '<input type="text" id="flt-name"' in html

    def test_flt_sector_select(self, html):
        assert '<select id="flt-sector">' in html

    def test_flt_scan_status_select_options(self, html):
        blk = section(html, '<select id="flt-scan-status">', "</select>")
        for opt in ("OK", "PARTIAL", "FAILED"):
            assert f'value="{opt}"' in blk

    def test_flt_kap_var_yok(self, html):
        blk = section(html, '<select id="flt-kap">', "</select>")
        assert ">Var<" in blk and ">Yok<" in blk

    def test_flt_news_var_yok(self, html):
        blk = section(html, '<select id="flt-news">', "</select>")
        assert ">Var<" in blk and ">Yok<" in blk

    def test_flt_measure_var_yok(self, html):
        blk = section(html, '<select id="flt-measure">', "</select>")
        assert ">Var<" in blk and ">Yok<" in blk

    def test_flt_min_confidence_number(self, html):
        assert '<input type="number" id="flt-min-confidence" min="0" max="100"' in html

    def test_exactly_8_filter_controls(self, html):
        blk = section(html, 'id="stk-filters"', "</div>")
        controls = re.findall(r'id="flt-[^"]+"', blk)
        assert len(controls) == 8, f"8 filtre bekleniyor, {len(controls)} bulundu"

    def test_filter_labels(self, html):
        blk = section(html, 'id="stk-filters"', "</div>")
        for lbl in ("Hisse Kodu", "Sirket Adi", "Sektor", "Tarama Durumu",
                    "KAP", "Haber", "Tedbir", "Min Veri Guveni"):
            assert lbl in blk, f"filtre etiketi eksik: {lbl}"

    def test_filters_bound_in_js(self, html):
        for fid in ("flt-symbol", "flt-name", "flt-sector", "flt-scan-status",
                    "flt-kap", "flt-news", "flt-measure", "flt-min-confidence"):
            assert f'byId("{fid}")' in html, f"JS filtre baglantisi eksik: {fid}"


# ======================================================================
# 4. SIRALAMA — 3 SECENEK + YON (8 test)
# ======================================================================
class TestSorting:
    def test_sort_container(self, html):
        assert 'id="stk-sort"' in html

    def test_sort_by_select(self, html):
        assert '<select id="sort-by">' in html

    def test_sort_option_gunluk_degisim(self, html):
        assert 'value="gunluk_yuzde_degisim" data-sort-key="gunluk_degisim"' in html

    def test_sort_option_hacim_orani(self, html):
        assert 'value="hacim_orani_20" data-sort-key="hacim_orani"' in html

    def test_sort_option_veri_guveni(self, html):
        assert 'value="veri_guveni" data-sort-key="veri_guveni"' in html

    def test_sort_dir_select(self, html):
        assert '<select id="sort-dir">' in html

    def test_sort_dir_asc_desc(self, html):
        blk = section(html, '<select id="sort-dir">', "</select>")
        assert 'value="asc"' in blk and 'value="desc"' in blk

    def test_sort_logic_in_js(self, html):
        assert "function sortItems(" in html
        assert 'state.sortDir === "asc"' in html


# ======================================================================
# 5. SAYFALAMA (14 test)
# ======================================================================
class TestPagination:
    def test_page_container(self, html):
        assert 'id="stk-page"' in html

    def test_page_size_select(self, html):
        assert '<select id="page-size">' in html

    def test_page_size_option_25(self, html):
        blk = section(html, '<select id="page-size">', "</select>")
        assert 'value="25"' in blk

    def test_page_size_option_50(self, html):
        blk = section(html, '<select id="page-size">', "</select>")
        assert 'value="50"' in blk

    def test_page_size_option_100(self, html):
        blk = section(html, '<select id="page-size">', "</select>")
        assert 'value="100"' in blk

    def test_page_prev_button(self, html):
        assert '<button id="page-prev"' in html

    def test_page_next_button(self, html):
        assert '<button id="page-next"' in html

    def test_page_info_label(self, html):
        assert 'id="page-info"' in html

    def test_page_buttons_disabled_initially(self, html):
        assert '<button id="page-prev" type="button" disabled="">' in html
        assert '<button id="page-next" type="button" disabled="">' in html

    def test_no_single_fetch_100_note(self, html):
        assert "tek cevapta cekilmez" in html  # 100 hisse TEK cevapta cekilmez

    def test_fetch_builds_page_param(self, html):
        assert 'p.set("page", String(state.page))' in html

    def test_fetch_builds_page_size_param(self, html):
        assert 'p.set("page_size", String(state.pageSize))' in html

    def test_page_prev_next_handlers(self, html):
        assert "state.page -= 1" in html
        assert "state.page += 1" in html

    def test_page_size_change_resets_page(self, html):
        blk = section(html, 'byId("page-size").addEventListener', "});")
        assert "state.page = 1" in blk


# ======================================================================
# 6. MOBIL TASMA — @media (max-width:640px) (10 test)
# ======================================================================
class TestMobile:
    def test_media_query_640_exists(self, html):
        assert "@media (max-width:640px)" in html

    def test_media_hides_table_wrap(self, html):
        blk = section(html, "@media (max-width:640px)", "</style>")
        assert ".stk-wrap{display:none}" in blk

    def test_media_shows_card_list(self, html):
        blk = section(html, "@media (max-width:640px)", "</style>")
        assert ".stk-cards{display:flex}" in blk

    def test_mobile_filters_two_columns(self, html):
        blk = section(html, "@media (max-width:640px)", "</style>")
        assert ".stk-filters{grid-template-columns:repeat(2,1fr)}" in blk

    def test_mobile_scan_grid_two_columns(self, html):
        blk = section(html, "@media (max-width:640px)", "</style>")
        assert ".scan-grid{grid-template-columns:repeat(2,1fr)}" in blk

    def test_cards_container_in_dom(self, html):
        assert '<div class="stk-cards" id="stk-cards">' in html

    def test_card_class_css(self, html):
        assert ".stk-card{" in html

    def test_card_head_and_row_classes(self, html):
        assert ".stk-card-head" in html and ".stk-card-row" in html

    def test_card_render_function(self, html):
        assert "function cardHtml(" in html
        assert "stk-card-head" in html and "stk-card-row" in html

    def test_cards_rendered_from_items(self, html):
        assert 'byId("stk-cards").innerHTML = items.map(cardHtml).join("")' in html


# ======================================================================
# 7. DEMO ISARETLERI (14 test)
# ======================================================================
class TestDemoMarks:
    def test_demo_badge_css(self, html):
        assert ".demo-badge{" in html

    def test_demo_band_css(self, html):
        assert ".demo-band{" in html and ".demo-band-sub{" in html

    def test_fixed_date_has_demo_badge(self, html):
        line = [ln for ln in html.splitlines() if "09.07.2026 Persembe" in ln]
        assert line and 'class="demo-badge"' in line[0]

    def test_date_demo_text(self, html):
        assert "DEMO ORNEK — gercek veri degil" in html

    def test_fixed_endeks_has_demo_badge(self, html):
        line = [ln for ln in html.splitlines() if "Endeks: 71.5 POZITIF" in ln]
        assert line and 'id="demo-badge-endeks"' in line[0]

    def test_fixed_rapor_has_demo_badge(self, html):
        line = [ln for ln in html.splitlines() if "Rapor: 2026-07-09-INDEX-R1" in ln]
        assert line and 'id="demo-badge-rapor"' in line[0]

    def test_favori_scoring_band(self, html):
        blk = section(html, "Favori Hisseler + 100 Hisse Ozeti", 'id="cb1"')
        assert "HISSE SKORLAMA MODULU HENUZ CANLI DEGIL" in blk

    def test_favori_demo_sub_band(self, html):
        blk = section(html, "Favori Hisseler + 100 Hisse Ozeti", 'id="cb1"')
        assert "BU ALANDAKI DEGERLER DEMO ORNEKTIR — gercek analiz degildir" in blk

    def test_asels_demo_band(self, html):
        blk = section(html, "ASELS | Skor: 87.4 | Guven: %81", "ASELS MUM")
        assert 'id="demo-band-asels"' in blk
        assert "BU ALANDAKI DEGERLER DEMO ORNEKTIR" in blk

    def test_portfoy_demo_band(self, html):
        blk = section(html, "Portfoy Dagilimi (Pasta Grafik)", 'id="c8"')
        assert 'id="demo-band-portfoy"' in blk
        assert "BU ALANDAKI DEGERLER DEMO ORNEKTIR" in blk

    def test_original_scores_preserved(self, html):
        assert "71.5" in html and "87.4" in html  # puan kilidi: silinmez/degistirilmez

    def test_favori_canvas_preserved(self, html):
        assert '<canvas class="cv" id="c1"' in html

    def test_asels_canvas_preserved(self, html):
        assert 'id="mumASELS"' in html

    def test_portfoy_canvas_preserved(self, html):
        assert '<canvas class="cv" id="c8"' in html


# ======================================================================
# 8. API BAGLANTI + PUAN KILIDI (16 test)
# ======================================================================
class TestApiAndScoreLock:
    def test_api_base_same_origin(self, html):
        assert 'const API_BASE = ""' in html

    def test_scan_latest_endpoint(self, html):
        assert '"/api/xk100/scan/latest"' in html

    def test_stocks_endpoint(self, html):
        assert '"/api/xk100/stocks"' in html

    def test_fetch_used_for_both(self, html):
        assert "fetch(SCAN_URL" in html
        assert "fetch(STOCKS_URL" in html

    def test_stocks_fetch_page_based(self, html):
        assert 'fetch(STOCKS_URL + "?" + readFilters()' in html
        assert "GET /api/xk100/stocks?page=" in html

    def test_envelope_required_keys(self, html):
        blk = section(html, "const ENVELOPE_KEYS", "];")
        for key in ("scan_run_id", "report_version", "last_updated_at",
                    "data_cutoff_at", "status"):
            assert f'"{key}"' in blk

    def test_envelope_validation_function(self, html):
        assert "function envelopeValid(" in html

    def test_envelope_gate_before_render(self, html):
        # zarf dogrulanmadan ekrana basilmaz (scan + stocks)
        assert html.count("if (!envelopeValid(env)) throw") == 2

    def test_score_keys_blocklist(self, html):
        blk = section(html, "const SCORE_KEYS", "];")
        for key in ("skor", "score", "puan"):
            assert f'"{key}"' in blk

    def test_strip_score_keys_function(self, html):
        assert "function stripScoreKeys(" in html

    def test_strip_applied_before_render(self, html):
        assert "env.items.map(stripScoreKeys)" in html

    def test_error_masking(self, html):
        assert "function maskError(" in html
        assert "console.warn" in html

    def test_no_run_state_text(self, html):
        assert "HENUZ CALISMA YOK — ilk sabah taramasi bekleniyor" in html

    def test_demo_data_false_marker(self, html):
        assert "demo_data=false" in html

    def test_no_fake_rows_in_tbody(self, html):
        blk = section(html, '<tbody id="stk-tbody">', "</tbody>")
        assert "<tr" not in blk  # sahte satir URETILMEZ

    def test_no_framework_dependency(self, html):
        low = html.lower()
        for fw in ("react", "vue", "angular", "jquery", "unpkg.com", "cdn.jsdelivr"):
            assert fw not in low, f"framework/dis bagimlilik bulundu: {fw}"
