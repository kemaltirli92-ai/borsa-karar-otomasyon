"""BLOK 24 - Sistem Yukluluk Envanteri: paylasilan veri + yardimcilar.

SPEC-BLOK24 durum tablosu TARTISILMAZDIR: 53 oge, 21 YUKLU, 32 BOS YAZI.
Bu modul docs.html'deki rozet/tablo/JSON ile birebir ayni kod kumesini tasir.

Yol cozumu: blok18 cift-aday deseni (telegram-sender / repo koku).
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_CANDIDATES = [
    REPO_ROOT.parent / "telegram-sender" / "docs.html",  # yerel calisma dizini
    REPO_ROOT / "docs.html",                             # GitHub repo koku
]
DOCS_HTML = next((p for p in DOCS_CANDIDATES if p.is_file()), DOCS_CANDIDATES[-1])

TIK = "\u2713"  # ✓ SISTEMDE YUKLU isareti (U+2713)
X = "\u2717"    # ✗ BOS YAZI isareti (U+2717)

# (kod, ad, durum, kanit) — SPEC-BLOK24 durum tablosu (DEGISTIRILEMEZ)
ITEMS = [
 ("BOLUM-1","VERI TOPLAMA","bos-yazi","Endeks veri toplayicilari (VIOP, kuresel, doviz/CDS) repoda YOK"),
 ("BOLUM-2","ENDEKS SKORLAMA","bos-yazi","Skor motoru bu repoda YOK (Bolum 1-2 baska konumda)"),
 ("BOLUM-3","HISSE TARAMASI","yuklu","app/services/stock_scanning/ + tests/blok6-23 (1700 test)"),
 ("BOLUM-4","HISSE SKORLAMA","bos-yazi","Skorlama modulu yok; sayfada HENUZ CANLI DEGIL banti"),
 ("BOLUM-5","TEKNIK GOSTERGE ANALIZI","bos-yazi","Gosterge motoru yok (RSI/MACD hesaplayici yok)"),
 ("BOLUM-6","SEVIYE HARITASI","bos-yazi","Seviye motoru yok"),
 ("BOLUM-7","HABER ANALIZI","bos-yazi","Haber TOPLAMA yuklu (BLOK 12) ama analiz/ton skoru yok"),
 ("BOLUM-8","PORTFOY DAGILIMI","bos-yazi","Portfoy motoru yok"),
 ("BOLUM-9","RAPOR YAYINI","bos-yazi","Web+API yuklu ama otomatik 09:45 yayin + bildirim yok"),
 ("B1","ONEMLI UYGULAMA TALIMATI","bos-yazi","Uygulama talimati/kavram — kod karsiligi yok"),
 ("B2","ENDEKS SKORLAMA KURALLARI","bos-yazi","Skor motoru bu repoda YOK"),
 ("B3","HESAPLAMA ZAMANI VE SCHEDULER","bos-yazi","Zamanlayici unitler repoda VAR ama tetiklenen motor yok"),
 ("B4","KULLANILACAK VERI DONEMI","bos-yazi","Endeks skorlama motoru bu repoda YOK"),
 ("B5","ENDEKS YONU VE PIYASA YAPISI","bos-yazi","Endeks skorlama motoru bu repoda YOK"),
 ("B6","VIOP","bos-yazi","Endeks skorlama motoru bu repoda YOK"),
 ("B7","HACIM VE PIYASA GENISLIGI","bos-yazi","Endeks skorlama motoru bu repoda YOK"),
 ("B8","KURESEL PIYASALAR","bos-yazi","Endeks skorlama motoru bu repoda YOK"),
 ("B9","DOVIZ, CDS VE FAIZ","bos-yazi","Endeks skorlama motoru bu repoda YOK"),
 ("B10","SEKTOR ROTASYONU","bos-yazi","Endeks skorlama motoru bu repoda YOK"),
 ("B11","JEOPOLITIK RISK","bos-yazi","AI entegrasyonu da yok (motor yok)"),
 ("B12","PUAN NORMALIZASYON VE REJIM","bos-yazi","Endeks skorlama motoru bu repoda YOK"),
 ("B13","VPS MIMARISI VE SISTEM BIRLESIMI","bos-yazi","db/schema.sql + systemd artefaktlari VAR ama backtest/golge mod/aciklama motoru yok"),
 ("C1","SISTEMIN CALISMA MODELI","yuklu","Kural karti; sayfa dogrulama blok23 regresyonunda (100/100)"),
 ("C2","XK100 EVREN YONETIMI","yuklu","app/acceptance/universe.py + tests/blok22 (100/100)"),
 ("C3","SIRKET KIMLIGI VE SEMBOL ESLESTIRME","yuklu","app/services/stock_scanning/symbol_identity.py + tests/blok6 (100/100)"),
 ("C4","FIYAT VE TARIHSEL VERI TOPLAMA","yuklu","app/services/stock_scanning/price_collection/ + tests/blok8 (100/100)"),
 ("C5","OHLCV KALITE KONTROLU","yuklu","app/services/stock_scanning/validation/ + tests/blok9 (100/100)"),
 ("C6","HACIM VE TL ISLEM HACMI","yuklu","app/services/stock_scanning/volume/ + tests/blok10 (100/100)"),
 ("C7","KAP TOPLAMA","yuklu","app/services/stock_scanning/kap_collection/ + tests/blok11 (100/100)"),
 ("C8","HABER HAVUZU VE ESLESTIRME","yuklu","app/services/stock_scanning/news/ + tests/blok12 (100/100)"),
 ("C9","KURUMSAL ISLEMLER VE TEDBIRLER","yuklu","app/services/stock_scanning/corporate_actions/ + tests/blok13 (100/100)"),
 ("C10","ZAMANLAMA VE GOREV DURUMLARI","yuklu","app/services/stock_scanning/orchestration/ + tests/blok14 (100/100)"),
 ("C11","TARAMA VERI GUVENI","yuklu","app/services/stock_scanning/confidence/ + tests/blok15 (100/100)"),
 ("C12","VERI TABANI VE API","yuklu","app/services/stock_scanning/db/ + app/api/ + tests/blok7 + tests/blok16 (100/100)"),
 ("C13","TESTLER, VPS DEPLOYMENT VE TAMAMLANMA KRITERLERI","yuklu","app/acceptance/ + deploy/ + tests/blok22 (100/100)"),
 ("BLOK-5","XK100 EVREN MODULU","bos-yazi","Modul kaynaklari bu repoda YOK — yazida kalanlar maddesi 1 (kabul: app/acceptance/universe.py haric)"),
 ("BLOK-6","SIRKET KIMLIGI VE SEMBOL ESLESTIRME","yuklu","app/services/stock_scanning/symbol_identity.py + tests/blok6 (100/100)"),
 ("BLOK-7","VERI TABANI VE MIGRATION","bos-yazi","Teslim karti bu sayfada YOK — calisma C12 kartinda yuklu sayildi (tests/blok7, 100/100); BLOK kodu cift sayilmaz"),
 ("BLOK-8","FIYAT VERISI TOPLAMA","bos-yazi","Teslim karti bu sayfada YOK — calisma C4 kartinda yuklu sayildi (tests/blok8, 100/100); BLOK kodu cift sayilmaz"),
 ("BLOK-9","OHLCV DOGRULAMA VE KURUMSAL ISLEM","bos-yazi","Teslim karti bu sayfada YOK — calisma C5 kartinda yuklu sayildi (tests/blok9, 100/100); BLOK kodu cift sayilmaz"),
 ("BLOK-10","HACIM, TL ISLEM HACMI VE HACIM ORANI","bos-yazi","Teslim karti bu sayfada YOK — calisma C6 kartinda yuklu sayildi (tests/blok10, 100/100); BLOK kodu cift sayilmaz"),
 ("BLOK-11","KAP BILDIRIM TOPLAMA","bos-yazi","Teslim karti bu sayfada YOK — calisma C7 kartinda yuklu sayildi (tests/blok11, 100/100); BLOK kodu cift sayilmaz"),
 ("BLOK-12","HABER TOPLAMA, ESLESTIRME VE TEKILLESTIRME","bos-yazi","Teslim karti bu sayfada YOK — calisma C8 kartinda yuklu sayildi (tests/blok12, 100/100); BLOK kodu cift sayilmaz"),
 ("BLOK-13","KURUMSAL ISLEMLER VE TEDBIRLER","bos-yazi","Teslim karti bu sayfada YOK — calisma C9 kartinda yuklu sayildi (tests/blok13, 100/100); BLOK kodu cift sayilmaz"),
 ("BLOK-14","ZAMANLAMA, PARALELLIK VE DURUM MAKINESI","bos-yazi","Teslim karti bu sayfada YOK — calisma C10 kartinda yuklu sayildi (tests/blok14, 100/100); BLOK kodu cift sayilmaz"),
 ("BLOK-15","VERI GUVENI (CONFIDENCE) HAZIRLIK","bos-yazi","Teslim karti bu sayfada YOK — calisma C11 kartinda yuklu sayildi (tests/blok15, 100/100); BLOK kodu cift sayilmaz"),
 ("BLOK-16","API VE RAPOR SURUMU","bos-yazi","Teslim karti bu sayfada YOK — calisma C12 kartinda yuklu sayildi (tests/blok16, 100/100); BLOK kodu cift sayilmaz"),
 ("BLOK-17","YONETICI SISTEM SEMASI SAYFASI","yuklu","telegram-sender/docs.html (bu sayfa); blok18-23 sayfa testleri regresyonu"),
 ("BLOK-18","MUSTERI ANA SAYFASI","yuklu","telegram-sender/index.html + tests/blok18 (100/100)"),
 ("BLOK-19","HISSE DETAY PANELI + HAM GRAFIKLER","yuklu","stk-detail paneli + tests/blok19 (100/100)"),
 ("BLOK-20","MOBIL ENTEGRASYON (PWA + API SOZLESMESI)","yuklu","manifest.webmanifest + sw.js + docs/api-contract.json + tests/blok20 (100/100)"),
 ("BLOK-21","GUVENLIK, LOG, IZLEME VE YEDEKLEME","yuklu","app/ops/ (11 modul) + tests/blok21 (100/100)"),
 ("BLOK-22","TEST, VPS DEPLOYMENT VE TAMAMLANMA","yuklu","app/acceptance/ + deploy/ + tests/blok22 (100/100)"),
]

KODLAR = [k for k, _, _, _ in ITEMS]
DURUM = {k: d for k, _, d, _ in ITEMS}
AD = {k: a for k, a, _, _ in ITEMS}

# Akis adimlari: (n, ttl metni) — AKIS-N durumu BOLUM-N ile ayni (SPEC)
AKIS_TTL = [
 (1, "VERI TOPLAMA"), (2, "ENDEKS SKORLAMA"), (3, "HISSE TARAMASI"),
 (4, "HISSE SKORLAMA"), (5, "TEKNIK GOSTERGE ANALIZI"), (6, "SEVIYE HARITASI"),
 (7, "HABER ANALIZI"), (8, "PORTFOY DAGILIMI"), (9, "RAPOR YAYINI"),
]
AKIS_KODLAR = [f"AKIS-{n}" for n, _ in AKIS_TTL]

B_KODLAR = [f"B{i}" for i in range(1, 14)]           # B1..B13 (hepsi bos-yazi)
C_KODLAR = [f"C{i}" for i in range(1, 14)]           # C1..C13 (hepsi yuklu)
BLOK_KART_YUKLU = ["BLOK-6", "BLOK-17", "BLOK-18", "BLOK-19",
                   "BLOK-20", "BLOK-21", "BLOK-22"]  # karti olan yuklu bloklar

BADGE_RE = re.compile(
    r'<span class="yd (yd-ok|yd-no)" data-kod="([A-Z0-9-]+)" data-durum="([^"]+)"'
    r' data-test="([^"]+)" aria-label="([^"]*)">([^<]*)</span>')


def h3_bloklari(html: str):
    """Tum <h3>...</h3> govde listesini dondur."""
    return re.findall(r"<h3>.*?</h3>", html, re.S)


def h3_icinde_kod(html: str, kod: str) -> str | None:
    """data-kod'u tasiyan rozeti iceren h3 govdesini dondur (yoksa None)."""
    for h in h3_bloklari(html):
        if f'data-kod="{kod}"' in h:
            return h
    return None


def envanter_bolumu(html: str) -> str:
    """id='sistem-yukluluk-envanteri' kartinin HTML dilimini dondur."""
    s = html.index('id="sistem-yukluluk-envanteri"')
    e = html.index("</table>", s)
    return html[s:e]


def tablo_satirlari(html: str):
    """Envanter tablosundaki (kod, durum, satir) uclulerini dondur."""
    bolum = envanter_bolumu(html)
    out = []
    for m in re.finditer(r'<tr data-kod="([^"]+)" data-durum="([^"]+)">(.*?)</tr>',
                         bolum, re.S):
        out.append((m.group(1), m.group(2), m.group(3)))
    return out
