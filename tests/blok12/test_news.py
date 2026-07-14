"""BLOK 12 - Haber Toplama, Eslestirme ve Duplikasyon: TAM 100 pytest testi.

Kategoriler (toplam = 100, SPEC BLOK 12 bolum 11):
1. Dogru haber eslestirme: tam unvan, kisa ad, marka, kod+baglam (16).
2. Yanlis kod / kelime ici engel: kisa kod baglamsiz, "IS" vs "ISCTR",
   kod tek basina confirmed=False (14).
3. Bagli ortaklik + onemli istirak + yonetici eslestirme (12).
4. Eski sirket adi + eski kod (historical etiketi) (10).
5. Kopya haber: URL/baslik/metin/zaman/olay duplikasyonu (16).
6. Ajans kopyasi: canonical=ajans, kopya site bagimsiz dogrulama degil (12).
7. Etiketleme: reklam/sponsorlu/forum/otomatik fiyat tablosu (10).
8. AI kapali + AI hata + belirsiz eslestirme + puan kilidi (10).

Hicbir test gercek aga erismez: tum kaynaklar/AI istemcileri mock veya
enjekte edilir. Saat enjekte edilir (deterministik). stdlib only.
"""
from __future__ import annotations

import dataclasses
import inspect
from datetime import date, datetime, timedelta

import pytest

from app.services.stock_scanning.news import collector as collector_module
from app.services.stock_scanning.news.ai_adapter import (
    AI_INVALID_RESPONSE,
    AI_SERVICE_ERROR,
    AiMatcherAdapter,
)
from app.services.stock_scanning.news.aliases import AliasStore
from app.services.stock_scanning.news.collector import (
    REASON_AMBIGUOUS,
    REASON_LOW_CONFIDENCE,
    NewsCollector,
    NewsProcessResult,
    ReviewQueueItem,
)
from app.services.stock_scanning.news.dedupe import (
    AGENCY_COPY,
    DUPLICATE_SAME_EVENT,
    DUPLICATE_SAME_URL,
    DUPLICATE_TEXT,
    DUPLICATE_EVENT_TIME,
    DedupeConfig,
    DedupeEngine,
)
from app.services.stock_scanning.news.matcher import NewsMatcher
from app.services.stock_scanning.news.models import (
    ContentType,
    MatchMethod,
    MatchResult,
    NewsRecord,
)
from app.services.stock_scanning.news.tagger import ContentTagger
from app.services.stock_scanning.symbol_identity import SymbolIdentityService

T0 = datetime(2025, 3, 10, 9, 0)
FIXED_NOW = datetime(2025, 3, 10, 12, 0)


def fixed_clock() -> datetime:
    return FIXED_NOW


def build_store() -> AliasStore:
    """Standart test alias deposu (5 hisse)."""
    store = AliasStore()
    store.register(
        "STK-IS",
        code="ISCTR",
        full_name="Türkiye İş Bankası A.Ş.",
        short_name="İş Bankası",
        brand_names=["İşCep", "Maximum Kart"],
        subsidiaries=["İş Yatırım Menkul Değerler A.Ş.", "İş GYO"],
        affiliates=["Anadolu Sigorta"],
        executives=["Adnan Bali"],
    )
    store.register(
        "STK-THY",
        code="THYAO",
        full_name="Türk Hava Yolları A.O.",
        short_name="THY",
        brand_names=["Turkish Airlines"],
        subsidiaries=["SunExpress"],
    )
    store.register(
        "STK-GAR",
        code="GARAN",
        full_name="Türkiye Garanti Bankası A.Ş.",
        short_name="Garanti",
        brand_names=["Bonus Kart"],
    )
    store.register(
        "STK-AKB",
        code="AKBNK",
        full_name="Akbank T.A.Ş.",
        short_name="Akbank",
    )
    store.register(
        "STK-PETK",
        code="PETKM",
        full_name="Petkim Petrokimya Holding A.Ş.",
        old_names=["Petkim Aliağa Petrol A.Ş."],
        old_codes=["PETK", "PK"],
    )
    return store


def make_matcher(store=None, **kwargs) -> NewsMatcher:
    return NewsMatcher(store or build_store(), **kwargs)


def news(
    nid,
    title="",
    body="",
    source="HaberSitesi",
    url="",
    published=None,
) -> NewsRecord:
    return NewsRecord(
        news_id=nid,
        title=title,
        body=body,
        source_name=source,
        original_url=url,
        published_at=published,
    )


def by_stock(results, stock_id):
    for r in results:
        if r.stock_id == stock_id:
            return r
    return None


BODY_TEXT = (
    "Türk Hava Yolları 2025 yılı ilk çeyreğinde rekor yolcu sayısına ulaştığını "
    "duyurdu. Şirket kapasite artırımı planlıyor ve yeni hat açılışları yapacak."
)


# ===========================================================================
# 1. DOGRU HABER ESLESTIRME (16)
# ===========================================================================
class TestDogruEslesme:
    def test_01_tam_unvan_baslikta_95_confirmed(self):
        m = make_matcher()
        res = m.match(news("N1", title="Türkiye İş Bankası A.Ş. temettü kararını açıkladı"))
        r = by_stock(res, "STK-IS")
        assert r is not None
        assert r.match_score == 95
        assert r.match_method == MatchMethod.FULL_NAME
        assert r.is_confirmed is True
        assert r.needs_review is False

    def test_02_tam_unvan_govdede_confirmed(self):
        m = make_matcher()
        res = m.match(
            news(
                "N2",
                title="Bankacılık devi temettü açıkladı",
                body="Türkiye İş Bankası A.Ş. 2025 yılı temettü ödemesini duyurdu.",
            )
        )
        r = by_stock(res, "STK-IS")
        assert r is not None and r.is_confirmed is True
        assert r.match_method == MatchMethod.FULL_NAME

    def test_03_kisa_ad_88_confirmed(self):
        m = make_matcher()
        res = m.match(news("N3", title="İş Bankası temettü dağıtacak"))
        r = by_stock(res, "STK-IS")
        assert r is not None
        assert r.match_score == 88
        assert r.match_method == MatchMethod.SHORT_NAME
        assert r.is_confirmed is True

    def test_04_kisa_ad_matched_entity_orijinal(self):
        m = make_matcher()
        res = m.match(news("N4", title="Garanti kâr rakamlarını açıkladı"))
        r = by_stock(res, "STK-GAR")
        assert r is not None
        assert r.match_score == 88
        assert r.matched_entity == "Garanti"

    def test_05_marka_baglamla_85_confirmed(self):
        m = make_matcher()
        res = m.match(
            news("N5", title="Maximum Kart kampanyası hisse senedi piyasasında başladı")
        )
        r = by_stock(res, "STK-IS")
        assert r is not None
        assert r.match_score == 85
        assert r.match_method == MatchMethod.BRAND
        assert r.is_confirmed is True

    def test_06_kod_arti_marka_kombinasyonu_85(self):
        m = make_matcher()
        res = m.match(news("N6", title="ISCTR kodlu Maximum Kart hamlesi"))
        r = by_stock(res, "STK-IS")
        assert r is not None
        assert r.match_score == 85
        assert r.is_confirmed is True
        assert r.matched_entity == "Maximum Kart"

    def test_07_kod_arti_tam_unvan_kombinasyonu(self):
        m = make_matcher()
        res = m.match(
            news(
                "N7",
                title="ISCTR temettü ödemesi",
                body="ISCTR (Türkiye İş Bankası A.Ş.) temettü ödemesini tamamladı.",
            )
        )
        r = by_stock(res, "STK-IS")
        assert r is not None
        assert r.match_score >= 85
        assert r.is_confirmed is True
        assert r.match_method == MatchMethod.FULL_NAME

    def test_08_fuzzy_yuksek_tam_unvan_85_confirmed(self):
        m = make_matcher()
        # Siralama bozuk baslik: tam token dizisi yok, token kumesi ayni.
        res = m.match(news("N8", title="Bankası İş Türkiye A.Ş. temettü"))
        r = by_stock(res, "STK-IS")
        assert r is not None
        assert r.match_score == 85
        assert r.match_method == MatchMethod.FULL_NAME
        assert r.is_confirmed is True

    def test_09_fuzzy_yuksek_baska_hisse(self):
        m = make_matcher()
        res = m.match(news("N9", title="Yolları Hava Türk A.O. seferleri artırdı"))
        r = by_stock(res, "STK-THY")
        assert r is not None
        assert r.match_score == 85
        assert r.is_confirmed is True

    def test_10_sonuclar_skor_sirali(self):
        m = make_matcher()
        res = m.match(
            news("N10", title="Türkiye İş Bankası A.Ş. ve Garanti Bankası temettü")
        )
        assert len(res) >= 2
        scores = [r.match_score for r in res]
        assert scores == sorted(scores, reverse=True)
        assert res[0].stock_id == "STK-IS"
        assert res[0].match_score == 95
        assert res[1].stock_id == "STK-GAR"

    def test_11_match_result_alan_tipleri(self):
        m = make_matcher()
        res = m.match(news("N11", title="İş Bankası temettü dağıtacak"))
        r = res[0]
        assert isinstance(r.stock_id, str)
        assert isinstance(r.match_score, int) and 0 <= r.match_score <= 100
        assert isinstance(r.match_method, MatchMethod)
        assert isinstance(r.matched_entity, str)
        assert isinstance(r.is_confirmed, bool)
        assert isinstance(r.needs_review, bool)

    def test_12_kod_tek_basina_70_confirmed_degil(self):
        m = make_matcher()
        res = m.match(news("N12", title="THYAO bugün prim yaptı"))
        r = by_stock(res, "STK-THY")
        assert r is not None
        assert r.match_score == 70
        assert r.match_method == MatchMethod.CODE
        assert r.is_confirmed is False
        assert r.needs_review is True

    def test_13_marka_matched_entity_orijinal_metin(self):
        m = make_matcher()
        res = m.match(news("N13", title="Maximum Kart yeni kampanya duyurdu"))
        r = by_stock(res, "STK-IS")
        assert r is not None
        assert r.matched_entity == "Maximum Kart"
        assert r.match_method == MatchMethod.BRAND

    def test_14_turkce_karakter_normalize(self):
        m = make_matcher()
        res = m.match(news("N14", title="TÜRKİYE İŞ BANKASI A.Ş. KÂR AÇIKLADI"))
        r = by_stock(res, "STK-IS")
        assert r is not None
        assert r.is_confirmed is True
        assert r.match_score == 95

    def test_15_sadece_govdede_gecen_kisa_ad(self):
        m = make_matcher()
        res = m.match(
            news(
                "N15",
                title="Bankacılık sektöründe temettü rüzgarı",
                body="Garanti bu çeyrekte kârını artırdı.",
            )
        )
        r = by_stock(res, "STK-GAR")
        assert r is not None
        assert r.match_score == 88
        assert r.is_confirmed is True

    def test_16_iki_farkli_hisse_ikisi_de_confirmed(self):
        m = make_matcher()
        res = m.match(
            news("N16", title="Türkiye İş Bankası A.Ş. ve Garanti temettü yarışında")
        )
        r_is = by_stock(res, "STK-IS")
        r_gar = by_stock(res, "STK-GAR")
        assert r_is is not None and r_is.is_confirmed is True
        assert r_gar is not None and r_gar.is_confirmed is True
        assert r_is.match_score != r_gar.match_score  # esitlik yok -> AMBIGUOUS degil


# ===========================================================================
# 2. YANLIS KOD / KELIME ICI ENGEL (14)
# ===========================================================================
class TestYanlisKodKelimeIci:
    def _mini_store(self) -> AliasStore:
        store = AliasStore()
        store.register("STK-X", code="IS", full_name="İzmir Sigorta A.Ş.")
        store.register("STK-Y", code="ISCTR", full_name="Türkiye İş Bankası A.Ş.")
        return store

    def test_17_is_kodu_isctr_icinde_yakalanamaz(self):
        m = NewsMatcher(self._mini_store())
        res = m.match(news("N17", title="ISCTR hissesi bugün yükseldi"))
        assert by_stock(res, "STK-X") is None
        assert by_stock(res, "STK-Y") is not None

    def test_18_is_kodu_islem_icinde_yakalanamaz(self):
        m = NewsMatcher(self._mini_store())
        res = m.match(news("N18", title="Bankacılık işlem hacmi arttı"))
        assert res == []

    def test_19_kisa_kod_baglamsiz_eslesmez(self):
        m = NewsMatcher(self._mini_store())
        res = m.match(news("N19", title="IS yükselişte"))
        assert res == []

    def test_20_kisa_kod_baglamla_70_confirmed_degil(self):
        m = NewsMatcher(self._mini_store())
        res = m.match(news("N20", title="IS hissesi yükselişte"))
        r = by_stock(res, "STK-X")
        assert r is not None
        assert r.match_score == 70
        assert r.is_confirmed is False

    def test_21_uzun_kod_tek_basina_confirmed_degil(self):
        m = make_matcher()
        res = m.match(news("N21", title="GARAN yön arıyor"))
        r = by_stock(res, "STK-GAR")
        assert r is not None
        assert r.is_confirmed is False

    def test_22_kod_tek_basina_needs_review(self):
        m = make_matcher()
        res = m.match(news("N22", title="AKBNK seansta dalgalandı"))
        r = by_stock(res, "STK-AKB")
        assert r is not None
        assert r.needs_review is True

    def test_23_kod_skoru_teyit_esiginin_altinda(self):
        m = make_matcher()
        res = m.match(news("N23", title="PETKM gündemde"))
        r = by_stock(res, "STK-PETK")
        assert r is not None
        assert r.match_score < 80
        assert r.is_confirmed is False

    def test_24_ak_kodu_banka_icinde_yakalanamaz(self):
        store = AliasStore()
        store.register("STK-AK2", code="AK", full_name="Ak Enerji A.Ş.")
        m = NewsMatcher(store)
        res = m.match(news("N24", title="Banka kâr açıkladı"))
        assert res == []

    def test_25_garan_garantisi_icinde_yakalanamaz(self):
        m = make_matcher()
        res = m.match(news("N25", title="Depozito garantisi genişledi"))
        assert by_stock(res, "STK-GAR") is None

    def test_26_fuzzy_75_alti_eslesme_yok(self):
        m = make_matcher()
        res = m.match(news("N26", title="Türkiye İş rekoru"))
        assert res == []

    def test_27_fuzzy_orta_bant_60_needs_review(self):
        m = make_matcher()
        res = m.match(news("N27", title="Türkiye İş A.Ş. temettü"))
        r = by_stock(res, "STK-IS")
        assert r is not None
        assert r.match_score == 60
        assert r.match_method == MatchMethod.FULL_NAME
        assert r.is_confirmed is False
        assert r.needs_review is True

    def test_28_esit_skor_ambiguous_hicbiri_confirmed_degil(self):
        m = make_matcher()
        res = m.match(news("N28", title="Garanti ve İş Bankası kâr açıkladı"))
        r_is = by_stock(res, "STK-IS")
        r_gar = by_stock(res, "STK-GAR")
        assert r_is is not None and r_gar is not None
        assert r_is.match_score == r_gar.match_score
        assert r_is.is_confirmed is False
        assert r_gar.is_confirmed is False
        assert r_is.needs_review is True and r_gar.needs_review is True

    def test_29_ambiguous_collector_review_kuyrugu(self):
        matcher = make_matcher()
        collector = NewsCollector(matcher, DedupeEngine(), ContentTagger(), clock=fixed_clock)
        result = collector.process(
            [news("N29", title="Garanti ve İş Bankası kâr açıkladı", published=T0)]
        )
        items = [q for q in result.review_queue if q.news_id == "N29"]
        assert len(items) == 2
        assert all(q.reason == REASON_AMBIGUOUS for q in items)

    def test_30_ambiguous_alias_otomatik_teyit_yok(self):
        store = AliasStore()
        store.register("STK-A", code="ANAD", full_name="Anadolu Holding A.Ş.",
                       brand_names=["Anadolu Grubu"])
        store.register("STK-B", code="ANHB", full_name="Anadolu Hayat A.Ş.",
                       brand_names=["Anadolu Grubu"])
        assert store.is_ambiguous("Anadolu Grubu") is True
        m = NewsMatcher(store)
        res = m.match(news("N30", title="Anadolu Grubu hisse alımı yaptı"))
        assert len(res) == 2
        assert all(r.is_confirmed is False for r in res)
        assert all(r.needs_review is True for r in res)


# ===========================================================================
# 3. BAGLI ORTAKLIK + ISTIRAK + YONETICI (12)
# ===========================================================================
class TestBagliOrtaklikIstirakYonetici:
    def test_31_bagli_ortaklik_baglamsiz_75_review(self):
        m = make_matcher()
        res = m.match(
            news("N31", title="İş Yatırım Menkul Değerler A.Ş. yeni fon kurdu")
        )
        r = by_stock(res, "STK-IS")
        assert r is not None
        assert r.match_score == 75
        assert r.match_method == MatchMethod.SUBSIDIARY
        assert r.is_confirmed is False
        assert r.needs_review is True

    def test_32_bagli_ortaklik_baglamla_85_confirmed(self):
        m = make_matcher()
        res = m.match(
            news("N32", title="İş Yatırım Menkul Değerler A.Ş. yeni hisse fonu kurdu")
        )
        r = by_stock(res, "STK-IS")
        assert r is not None
        assert r.match_score == 85
        assert r.is_confirmed is True

    def test_33_marka_baglamsiz_75_confirmed_degil(self):
        m = make_matcher()
        res = m.match(news("N33", title="Maximum Kart kampanya başlattı"))
        r = by_stock(res, "STK-IS")
        assert r is not None
        assert r.match_score == 75
        assert r.is_confirmed is False

    def test_34_istirak_65_review(self):
        m = make_matcher()
        res = m.match(news("N34", title="Anadolu Sigorta yeni ürün tanıttı"))
        r = by_stock(res, "STK-IS")
        assert r is not None
        assert r.match_score == 65
        assert r.match_method == MatchMethod.AFFILIATE
        assert r.is_confirmed is False
        assert r.needs_review is True

    def test_35_istirak_baglamla_bile_75_review(self):
        m = make_matcher()
        res = m.match(news("N35", title="Anadolu Sigorta hisse performansı"))
        r = by_stock(res, "STK-IS")
        assert r is not None
        assert r.match_score == 75
        assert r.is_confirmed is False
        assert r.needs_review is True

    def test_36_yonetici_65_review(self):
        m = make_matcher()
        res = m.match(news("N36", title="Adnan Bali sektörü değerlendirdi"))
        r = by_stock(res, "STK-IS")
        assert r is not None
        assert r.match_score == 65
        assert r.match_method == MatchMethod.EXECUTIVE
        assert r.is_confirmed is False

    def test_37_bagli_ortaklik_arti_kod_85_confirmed(self):
        m = make_matcher()
        res = m.match(
            news("N37", title="İş Yatırım Menkul Değerler A.Ş. ISCTR önerisi")
        )
        r = by_stock(res, "STK-IS")
        assert r is not None
        assert r.match_score == 85
        assert r.is_confirmed is True

    def test_38_ayni_hissenin_baska_bagli_ortakligi(self):
        m = make_matcher()
        res = m.match(news("N38", title="İş GYO kira gelirlerini artırdı"))
        r = by_stock(res, "STK-IS")
        assert r is not None
        assert r.match_method == MatchMethod.SUBSIDIARY
        assert r.match_score == 75

    def test_39_bagli_ortaklik_dogru_hisseye(self):
        m = make_matcher()
        res = m.match(news("N39", title="SunExpress yeni hat açtı"))
        r = by_stock(res, "STK-THY")
        assert r is not None
        assert by_stock(res, "STK-IS") is None

    def test_40_bagli_ortaklik_review_kuyrugunda(self):
        matcher = make_matcher()
        collector = NewsCollector(matcher, DedupeEngine(), ContentTagger(), clock=fixed_clock)
        result = collector.process(
            [news("N40", title="İş Yatırım Menkul Değerler A.Ş. yeni fon kurdu", published=T0)]
        )
        items = [q for q in result.review_queue if q.news_id == "N40"]
        assert len(items) == 1
        assert items[0].stock_id == "STK-IS"
        assert items[0].match_score == 75
        assert items[0].reason == REASON_LOW_CONFIDENCE

    def test_41_yonetici_kelime_ici_yakalanamaz(self):
        m = make_matcher()
        res = m.match(news("N41", title="Alibaba hisseleri yükseldi"))
        assert by_stock(res, "STK-IS") is None

    def test_42_istirak_needs_review_true(self):
        m = make_matcher()
        res = m.match(news("N42", title="Anadolu Sigorta prim üretimini açıkladı"))
        r = by_stock(res, "STK-IS")
        assert r is not None
        assert r.needs_review is True
        assert r.match_score == 65


# ===========================================================================
# 4. ESKI SIRKET ADI + ESKI KOD (10)
# ===========================================================================
class TestEskiAdKod:
    def test_43_eski_ad_82_confirmed(self):
        m = make_matcher()
        res = m.match(
            news("N43", title="Petkim Aliağa Petrol A.Ş. tarihi tesisini yeniledi")
        )
        r = by_stock(res, "STK-PETK")
        assert r is not None
        assert r.match_score == 82
        assert r.is_confirmed is True

    def test_44_eski_ad_yontem_old_name(self):
        m = make_matcher()
        res = m.match(
            news("N44", title="Petkim Aliağa Petrol A.Ş. arşiv kayıtlarında")
        )
        r = by_stock(res, "STK-PETK")
        assert r is not None
        assert r.match_method == MatchMethod.OLD_NAME  # historical etiketi

    def test_45_eski_kod_82_confirmed(self):
        m = make_matcher()
        res = m.match(
            news("N45", title="PETK kodlu hisse eski kayıtlarda işlem gördü")
        )
        r = by_stock(res, "STK-PETK")
        assert r is not None
        assert r.match_score == 82
        assert r.match_method == MatchMethod.OLD_CODE
        assert r.is_confirmed is True

    def test_46_kisa_eski_kod_baglamsiz_eslesmez(self):
        m = make_matcher()
        res = m.match(news("N46", title="PK primlendi"))
        assert by_stock(res, "STK-PETK") is None

    def test_47_kisa_eski_kod_baglamla_82(self):
        m = make_matcher()
        res = m.match(news("N47", title="PK hissesi primlendi"))
        r = by_stock(res, "STK-PETK")
        assert r is not None
        assert r.match_score == 82
        assert r.match_method == MatchMethod.OLD_CODE
        assert r.is_confirmed is True

    def test_48_eski_ad_needs_review_degil(self):
        m = make_matcher()
        res = m.match(
            news("N48", title="Petkim Aliağa Petrol A.Ş. dönemine ait belgeler")
        )
        r = by_stock(res, "STK-PETK")
        assert r is not None
        assert r.needs_review is False

    def test_49_eski_ad_arti_eski_kod_92(self):
        m = make_matcher()
        res = m.match(
            news("N49", title="Petkim Aliağa Petrol A.Ş. PETK dönemi rekoru")
        )
        r = by_stock(res, "STK-PETK")
        assert r is not None
        assert r.match_score == 92
        assert r.is_confirmed is True

    def test_50_alias_store_blok6_aktif_kod(self):
        svc = SymbolIdentityService(clock=lambda: datetime(2025, 1, 1, 9, 0))
        sid = svc.register_stock("Anadolu Efes Biracılık ve Malt Sanayii A.Ş.")
        svc.add_symbol(sid, "bist", "AEFES")
        store = AliasStore(identity_service=svc)
        profile = store.get_profile(sid)
        assert profile is not None
        assert profile.code == "AEFES"
        assert profile.full_name == "Anadolu Efes Biracılık ve Malt Sanayii A.Ş."

    def test_51_alias_store_blok6_eski_kod_gecmisi(self):
        svc = SymbolIdentityService(clock=lambda: datetime(2025, 1, 1, 9, 0))
        sid = svc.register_stock("Anadolu Efes Biracılık ve Malt Sanayii A.Ş.")
        svc.add_symbol(sid, "bist", "AEFES")
        svc.change_symbol(sid, "bist", "AEFESX", date(2025, 6, 1))
        store = AliasStore(identity_service=svc)
        profile = store.get_profile(sid)
        assert profile.code == "AEFESX"
        assert "AEFES" in profile.old_codes

    def test_52_extra_panel_enjeksiyonu(self):
        store = AliasStore(
            extra={
                "STK-Z": {
                    "full_name": "Zorlu Enerji A.Ş.",
                    "brand_names": ["Zorlu Marka"],
                }
            }
        )
        ents = store.entities("STK-Z")
        assert ents[MatchMethod.FULL_NAME] == ["Zorlu Enerji A.Ş."]
        assert ents[MatchMethod.BRAND] == ["Zorlu Marka"]


# ===========================================================================
# 5. KOPYA HABER: URL/BASLIK/METIN/ZAMAN/OLAY DUPLIKASYONU (16)
# ===========================================================================
class TestKopyaHaber:
    def test_53_ayni_url_duplicate(self):
        d = DedupeEngine()
        a = news("A", title="Haber bir", body="Metin bir", url="https://x.com/h/1", published=T0)
        b = news("B", title="Haber iki", body="Metin iki", url="https://x.com/h/1",
                 published=T0 + timedelta(minutes=20))
        canonical, groups = d.dedupe([a, b])
        assert len(groups) == 1
        assert DUPLICATE_SAME_URL in groups[0].reason_codes
        assert len(canonical) == 1

    def test_54_ayni_url_canonical_en_erken(self):
        d = DedupeEngine()
        a = news("A", title="Haber bir", body="Metin bir", url="https://x.com/h/2", published=T0)
        b = news("B", title="Haber iki", body="Metin iki", url="https://x.com/h/2",
                 published=T0 - timedelta(minutes=30))
        canonical, groups = d.dedupe([a, b])
        assert groups[0].canonical_news_id == "B"
        assert canonical[0].news_id == "B"

    def test_55_baslik_metin_benzerligi_duplicate_text(self):
        d = DedupeEngine()
        a = news("A", title="THY rekor yolcu sayısına ulaştı", body=BODY_TEXT,
                 url="https://a.com/1", published=T0)
        b = news("B", title="THY rekor yolcu sayısına ulaştı", body=BODY_TEXT,
                 url="https://b.com/2", published=T0 + timedelta(minutes=40))
        canonical, groups = d.dedupe([a, b])
        assert len(groups) == 1
        assert DUPLICATE_TEXT in groups[0].reason_codes
        assert groups[0].canonical_news_id == "A"
        assert groups[0].duplicates == ["B"]

    def test_56_baslik_ayni_metin_farkli_pencere_disi_degil(self):
        d = DedupeEngine()
        a = news("A", title="THY rekor kırdı", body=BODY_TEXT, published=T0)
        b = news("B", title="THY rekor kırdı",
                 body="Merkez Bankası faiz kararını açıkladı. Piyasalar yön arıyor.",
                 published=T0 + timedelta(minutes=60))
        canonical, groups = d.dedupe([a, b])
        assert groups == []
        assert len(canonical) == 2

    def test_57_metin_ayni_baslik_farkli_duplicate_degil(self):
        d = DedupeEngine()
        a = news("A", title="THY rekor kırdı", body=BODY_TEXT, published=T0)
        b = news("B", title="Piyasalarda faiz indirimi beklentisi", body=BODY_TEXT,
                 published=T0 + timedelta(minutes=10))
        canonical, groups = d.dedupe([a, b])
        assert groups == []
        assert len(canonical) == 2

    def test_58_zaman_yakinligi_duplicate_event_time(self):
        d = DedupeEngine()
        a = news("A", title="Garanti temettü açıkladı", body="Kısa haber.",
                 published=T0)
        b = news("B", title="Garanti temettü açıkladı",
                 body="Piyasa uzmanları yorum yaptı.",
                 published=T0 + timedelta(minutes=20))
        canonical, groups = d.dedupe([a, b])
        assert len(groups) == 1
        assert DUPLICATE_EVENT_TIME in groups[0].reason_codes
        assert DUPLICATE_TEXT not in groups[0].reason_codes

    def test_59_zaman_penceresi_disi_duplicate_degil(self):
        d = DedupeEngine()
        a = news("A", title="Garanti temettü açıkladı", body="Kısa haber.",
                 published=T0)
        b = news("B", title="Garanti temettü açıkladı",
                 body="Piyasa uzmanları yorum yaptı.",
                 published=T0 + timedelta(minutes=45))
        canonical, groups = d.dedupe([a, b])
        assert groups == []
        assert len(canonical) == 2

    def _event_match_map(self, sid_a="STK-THY", sid_b="STK-THY"):
        def mr(sid):
            return MatchResult(
                stock_id=sid,
                match_score=95,
                match_method=MatchMethod.FULL_NAME,
                matched_entity="Türk Hava Yolları A.O.",
                is_confirmed=True,
            )
        return {"E1": [mr(sid_a)], "E2": [mr(sid_b)]}

    def test_60_ayni_olay_duplicate_same_event(self):
        d = DedupeEngine()
        a = news("E1", title="THY bedelsiz sermaye artırımı kararı", published=T0)
        b = news("E2", title="Türk Hava Yolları bedelsiz sermaye kararı duyurdu",
                 published=T0 + timedelta(minutes=30))
        canonical, groups = d.dedupe([a, b], match_map=self._event_match_map())
        assert len(groups) == 1
        assert groups[0].reason_codes == [DUPLICATE_SAME_EVENT]

    def test_61_ayni_olay_farkli_hisse_duplicate_degil(self):
        d = DedupeEngine()
        a = news("E1", title="THY bedelsiz sermaye artırımı kararı", published=T0)
        b = news("E2", title="Türk Hava Yolları bedelsiz sermaye kararı duyurdu",
                 published=T0 + timedelta(minutes=30))
        canonical, groups = d.dedupe(
            [a, b], match_map=self._event_match_map(sid_b="STK-IS")
        )
        assert groups == []
        assert len(canonical) == 2

    def test_62_ayni_olay_pencere_disi_duplicate_degil(self):
        d = DedupeEngine()
        a = news("E1", title="THY bedelsiz sermaye artırımı kararı", published=T0)
        b = news("E2", title="Türk Hava Yolları bedelsiz sermaye kararı duyurdu",
                 published=T0 + timedelta(hours=8, minutes=30))
        canonical, groups = d.dedupe([a, b], match_map=self._event_match_map())
        assert groups == []
        assert len(canonical) == 2

    def test_63_canonical_en_erken_published(self):
        d = DedupeEngine()
        a = news("A", title="THY rekor yolcu sayısına ulaştı", body=BODY_TEXT,
                 url="https://a.com/1", published=T0)
        b = news("B", title="THY rekor yolcu sayısına ulaştı", body=BODY_TEXT,
                 url="https://b.com/2", published=T0 - timedelta(minutes=30))
        c = news("C", title="THY rekor yolcu sayısına ulaştı", body=BODY_TEXT,
                 url="https://c.com/3", published=T0 + timedelta(minutes=30))
        canonical, groups = d.dedupe([a, b, c])
        assert len(groups) == 1
        assert groups[0].canonical_news_id == "B"
        assert set(groups[0].duplicates) == {"A", "C"}

    def test_64_canonical_esitlikte_en_uzun_body(self):
        d = DedupeEngine()
        a = news("A", title="Aynı haber", body="Kısa metin.", url="https://x.com/h/9",
                 published=T0)
        b = news("B", title="Aynı haber", body="Kısa metin. " + BODY_TEXT,
                 url="https://x.com/h/9", published=T0)
        canonical, groups = d.dedupe([a, b])
        assert groups[0].canonical_news_id == "B"

    def test_65_uclu_zincir_tek_canonical(self):
        d = DedupeEngine()
        a = news("A", title="Başlık bir", body="Metin bir", url="https://x.com/u",
                 published=T0)
        b = news("B", title="Garanti rekor temettü dağıttı", body=BODY_TEXT,
                 url="https://x.com/u", published=T0 + timedelta(minutes=10))
        c = news("C", title="Garanti rekor temettü dağıttı", body=BODY_TEXT,
                 url="https://y.com/v", published=T0 + timedelta(minutes=20))
        canonical, groups = d.dedupe([a, b, c])
        assert len(groups) == 1
        assert groups[0].canonical_news_id == "A"
        assert set(groups[0].duplicates) == {"B", "C"}
        assert len(canonical) == 1

    def test_66_dedupe_result_alanlari(self):
        d = DedupeEngine()
        a = news("A", title="THY rekor yolcu sayısına ulaştı", body=BODY_TEXT,
                 url="https://a.com/1", published=T0)
        b = news("B", title="THY rekor yolcu sayısına ulaştı", body=BODY_TEXT,
                 url="https://b.com/2", published=T0 + timedelta(minutes=40))
        _, groups = d.dedupe([a, b])
        g = groups[0]
        assert isinstance(g.canonical_news_id, str)
        assert isinstance(g.duplicates, list)
        assert isinstance(g.reason_codes, list)
        assert g.canonical_news_id == "A"
        assert g.duplicates == ["B"]
        assert g.reason_codes == [DUPLICATE_TEXT]

    def test_67_kopya_yoksa_hepsi_canonical(self):
        d = DedupeEngine()
        recs = [
            news("A", title="Garanti temettü dağıttı", body="Banka kârını artırdı.",
                 published=T0),
            news("B", title="Dolar kurunda sert yükseliş",
                 body="Küresel piyasalar dalgalanıyor.",
                 published=T0 + timedelta(minutes=5)),
            news("C", title="Altın fiyatları rekor kırdı",
                 body="Ons altın tarihi zirvede.",
                 published=T0 + timedelta(minutes=10)),
        ]
        canonical, groups = d.dedupe(recs)
        assert groups == []
        assert len(canonical) == 3
        assert all(d.confirmation_credits[r.news_id] is True for r in recs)

    def test_68_oto_fiyat_tablosu_dedupe_disi(self):
        d = DedupeEngine()
        p = news("P", title="BIST 100 Günlük Kapanış Fiyatları", body="THYAO 245,50",
                 url="https://x.com/same", published=T0)
        p.content_type = ContentType.AUTO_PRICE_TABLE
        n = news("N", title="BIST 100 Günlük Kapanış Fiyatları", body="THYAO 245,50",
                 url="https://x.com/same", published=T0)
        canonical, groups = d.dedupe([p, n])
        assert groups == []  # tablo dedupe'a katilmaz
        assert len(canonical) == 2
        assert d.confirmation_credits["N"] is True
        assert "P" not in d.confirmation_credits  # dogrulama kredisine katilmaz


# ===========================================================================
# 6. AJANS KOPYASI (12)
# ===========================================================================
class TestAjansKopyasi:
    def test_69_ajans_kopyasi_reason(self):
        d = DedupeEngine()
        a = news("AA1", title="Garanti temettü açıkladı", body=BODY_TEXT,
                 source="Anadolu Ajansı", published=T0)
        b = news("S1", title="Garanti temettü açıkladı", body=BODY_TEXT,
                 source="HaberX", published=T0 + timedelta(minutes=10))
        _, groups = d.dedupe([a, b])
        assert len(groups) == 1
        assert AGENCY_COPY in groups[0].reason_codes

    def test_70_ajans_canonical_kopya_daha_erken_olsa_bile(self):
        d = DedupeEngine()
        a = news("AA1", title="Garanti temettü açıkladı", body=BODY_TEXT,
                 source="AA", published=T0)
        b = news("S1", title="Garanti temettü açıkladı", body=BODY_TEXT,
                 source="HaberX", published=T0 - timedelta(minutes=30))
        canonical, groups = d.dedupe([a, b])
        assert groups[0].canonical_news_id == "AA1"
        assert canonical[0].news_id == "AA1"

    def test_71_kopya_site_bagimsiz_dogrulama_degil(self):
        d = DedupeEngine()
        a = news("AA1", title="Garanti temettü açıkladı", body=BODY_TEXT,
                 source="AA", published=T0)
        b = news("S1", title="Garanti temettü açıkladı", body=BODY_TEXT,
                 source="HaberX", published=T0 + timedelta(minutes=10))
        d.dedupe([a, b])
        assert d.confirmation_credits["AA1"] is True
        assert d.confirmation_credits["S1"] is False

    def test_72_iki_ajans_en_erken_canonical(self):
        d = DedupeEngine()
        a = news("AA1", title="Garanti temettü açıkladı", body=BODY_TEXT,
                 source="Anadolu Ajansı", published=T0 + timedelta(minutes=5))
        b = news("DHA1", title="Garanti temettü açıkladı", body=BODY_TEXT,
                 source="DHA", published=T0)
        _, groups = d.dedupe([a, b])
        assert groups[0].canonical_news_id == "DHA1"

    def test_73_ajans_ajans_kopyasi_kredi_korunur(self):
        d = DedupeEngine()
        a = news("AA1", title="Garanti temettü açıkladı", body=BODY_TEXT,
                 source="Anadolu Ajansı", published=T0 + timedelta(minutes=5))
        b = news("DHA1", title="Garanti temettü açıkladı", body=BODY_TEXT,
                 source="DHA", published=T0)
        _, groups = d.dedupe([a, b])
        assert AGENCY_COPY not in groups[0].reason_codes
        assert d.confirmation_credits["AA1"] is True
        assert d.confirmation_credits["DHA1"] is True

    def test_74_reason_codes_text_ve_agency_birlikte(self):
        d = DedupeEngine()
        a = news("AA1", title="Garanti temettü açıkladı", body=BODY_TEXT,
                 source="AA", published=T0)
        b = news("S1", title="Garanti temettü açıkladı", body=BODY_TEXT,
                 source="HaberX", published=T0 + timedelta(minutes=40))
        _, groups = d.dedupe([a, b])
        assert DUPLICATE_TEXT in groups[0].reason_codes
        assert AGENCY_COPY in groups[0].reason_codes

    def test_75_ajans_listesi_ayarlanabilir(self):
        d = DedupeEngine(DedupeConfig(agency_sources=("ozel ajans",)))
        a = news("OA1", title="Garanti temettü açıkladı", body=BODY_TEXT,
                 source="Özel Ajans", published=T0 + timedelta(minutes=10))
        b = news("S1", title="Garanti temettü açıkladı", body=BODY_TEXT,
                 source="HaberX", published=T0)
        _, groups = d.dedupe([a, b])
        assert groups[0].canonical_news_id == "OA1"
        assert AGENCY_COPY in groups[0].reason_codes

    def test_76_ilgisiz_site_gruplanmaz(self):
        d = DedupeEngine()
        a = news("AA1", title="Garanti temettü açıkladı", body=BODY_TEXT,
                 source="AA", published=T0)
        b = news("S1", title="Dolar kurunda yeni rekor denemesi",
                 body="Küresel piyasalarda dalgalanma sürüyor ve altın yükseliyor.",
                 source="HaberX", published=T0 + timedelta(minutes=5))
        _, groups = d.dedupe([a, b])
        assert groups == []

    def test_77_ajans_olmayan_kopyalar_kredi_korur(self):
        d = DedupeEngine()
        a = news("A", title="Garanti temettü açıkladı", body=BODY_TEXT,
                 source="SiteBir", published=T0)
        b = news("B", title="Garanti temettü açıkladı", body=BODY_TEXT,
                 source="SiteIki", published=T0 + timedelta(minutes=40))
        _, groups = d.dedupe([a, b])
        assert AGENCY_COPY not in groups[0].reason_codes
        assert d.confirmation_credits["A"] is True
        assert d.confirmation_credits["B"] is True

    def test_78_hafif_duzenlenmis_kopya_yakalanir(self):
        d = DedupeEngine()
        edited = BODY_TEXT.replace("duyurdu", "açıkladı").replace("planlıyor", "hedefliyor")
        a = news("AA1", title="Garanti temettü açıkladı", body=BODY_TEXT,
                 source="AA", published=T0)
        b = news("S1", title="Garanti temettü açıkladı", body=edited,
                 source="HaberX", published=T0 + timedelta(minutes=15))
        _, groups = d.dedupe([a, b])
        assert len(groups) == 1
        assert groups[0].canonical_news_id == "AA1"
        assert AGENCY_COPY in groups[0].reason_codes

    def test_79_collector_ajans_kredi_ve_eslesme_aktarimi(self):
        matcher = make_matcher()
        collector = NewsCollector(matcher, DedupeEngine(), ContentTagger(), clock=fixed_clock)
        aa = news(
            "AA1",
            title="Garanti temettü açıkladı",
            body="Garanti Bankası 2025 temettü ödemelerini duyurdu. Dağıtım tarihi belli oldu.",
            source="AA",
            published=T0,
        )
        copy = news(
            "S1",
            title="Garanti temettü açıkladı",
            body=(
                "Garanti Bankası 2025 temettü ödemelerini duyurdu. Dağıtım tarihi belli oldu. "
                "Analistler Türkiye İş Bankası A.Ş. hisselerini de öneriyor."
            ),
            source="HaberX",
            published=T0 + timedelta(minutes=5),
        )
        result = collector.process([aa, copy])
        assert result.confirmation_credits["S1"] is False
        assert result.confirmation_credits["AA1"] is True
        # Kopyanin eslesmeleri kanonik habere aktarilir.
        canon_matches = result.canonical_matches["AA1"]
        assert by_stock(canon_matches, "STK-IS") is not None
        assert by_stock(canon_matches, "STK-GAR") is not None

    def test_80_ajans_tespiti_cesitleri(self):
        d = DedupeEngine()
        assert d.is_agency("Anadolu Ajansı") is True
        assert d.is_agency("AA") is True
        assert d.is_agency("Reuters") is True
        assert d.is_agency("DHA") is True
        assert d.is_agency("IHA") is True
        assert d.is_agency("HaberTürk") is False
        assert d.is_agency("HaberX") is False
        assert d.is_agency("") is False


# ===========================================================================
# 7. ETIKETLEME (10)
# ===========================================================================
PRICE_BODY = "THYAO 245,50 %2,3\nGARAN 88,20 %-1,1\nISCTR 14,05 %0,8\nAKBNK 52,10 %1,2"


class TestEtiketleme:
    def test_81_reklam_advertisement(self):
        t = ContentTagger()
        r = t.tag(news("T1", title="Yeni kampanya duyurusu",
                       body="Bu haber bir reklam içeriğidir."))
        assert r.content_type == ContentType.ADVERTISEMENT
        assert any("AD_KEYWORD:reklam" in reason for reason in r.tag_reasons)

    def test_82_sponsorlu(self):
        t = ContentTagger()
        r = t.tag(news("T2", title="Kampanya detayları",
                       body="Bu içerik sponsorlu bir yayındır."))
        assert r.content_type == ContentType.SPONSORED
        assert ContentType.SPONSORED in r.tags

    def test_83_tanitim_yazisi(self):
        t = ContentTagger()
        r = t.tag(news("T3", title="Sektörden haberler",
                       body="Aşağıdaki metin tanıtım yazısı içerir."))
        assert r.content_type == ContentType.ADVERTISEMENT

    def test_84_advertorial(self):
        t = ContentTagger()
        r = t.tag(news("T4", title="Advertorial: yeni ürün tanıtımı"))
        assert r.content_type == ContentType.ADVERTISEMENT

    def test_85_forum_url_deseni(self):
        t = ContentTagger()
        r = t.tag(news("T5", title="Kullanıcı yorumu",
                       url="https://forum.donanimhaber.com/konu/123456"))
        assert r.content_type == ContentType.FORUM
        assert "FORUM_URL" in r.tag_reasons

    def test_86_forum_kaynak_adi(self):
        t = ContentTagger()
        r = t.tag(news("T6", title="Başlık tartışması", source="Ekşi Sözlük"))
        assert r.content_type == ContentType.FORUM
        assert any(r2.startswith("FORUM_SOURCE") for r2 in r.tag_reasons)

    def test_87_oto_fiyat_tablosu(self):
        t = ContentTagger()
        r = t.tag(news("T7", title="BIST 100 Günlük Kapanış Fiyatları",
                       body=PRICE_BODY))
        assert r.content_type == ContentType.AUTO_PRICE_TABLE
        assert any(r2.startswith("PRICE_ROW_RATIO") for r2 in r.tag_reasons)
        assert any(r2.startswith("PRICE_TITLE_TEMPLATE") for r2 in r.tag_reasons)

    def test_88_fiyat_satirlari_sablonsuz_news(self):
        t = ContentTagger()
        r = t.tag(news("T8", title="Piyasalarda son durum", body=PRICE_BODY))
        assert r.content_type == ContentType.NEWS
        assert r.tag_reasons == []

    def test_89_coklu_etiket(self):
        t = ContentTagger()
        r = t.tag(news("T9", title="Sponsorlu içerik: kampanya detayları",
                       body="Bu içerik sponsorlu bir yayındır.",
                       url="https://forum.example.com/konu/99"))
        assert ContentType.SPONSORED in r.tags
        assert ContentType.FORUM in r.tags
        assert r.content_type == ContentType.SPONSORED  # birincil oncelik

    def test_90_duzyazi_news(self):
        t = ContentTagger()
        r = t.tag(news("T10", title="Merkez Bankası faiz kararını açıkladı",
                       body="Piyasalar kararı olumlu karşıladı.",
                       source="HaberTürk"))
        assert r.content_type == ContentType.NEWS
        assert r.tags == [ContentType.NEWS]
        assert r.tag_reasons == []


# ===========================================================================
# 8. AI KAPALI + AI HATA + BELIRSIZ ESLESTIRME + PUAN KILIDI (10)
# ===========================================================================
class DummyAiClient:
    """Mock AI istemcisi (gercek ag YOK)."""

    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc

    def match_news(self, news_record, candidate):
        if self.exc is not None:
            raise self.exc
        return self.response


UNCERTAIN_NEWS = ("U1", "THYAO bugün prim yaptı")  # skor 70 -> belirsiz bant


class TestAiVePuanKilidi:
    def test_91_ai_kapali_assess_none(self):
        adapter = AiMatcherAdapter(None)
        assert adapter.enabled is False
        assert adapter.assess(news("X"), MatchResult()) is None
        assert adapter.call_count == 0

    def test_92_ai_kapali_tarama_devam_eder(self):
        matcher = make_matcher()  # ai=None
        collector = NewsCollector(matcher, DedupeEngine(), ContentTagger(), clock=fixed_clock)
        nid, title = UNCERTAIN_NEWS
        result = collector.process([news(nid, title=title, published=T0)])
        assert isinstance(result, NewsProcessResult)
        items = [q for q in result.review_queue if q.news_id == nid]
        assert len(items) == 1
        assert items[0].reason == REASON_LOW_CONFIDENCE

    def test_93_ai_confirmed_eslesmeye_cagrilmaz(self):
        store = AliasStore()
        store.register("STK-IS", code="ISCTR",
                       full_name="Türkiye İş Bankası A.Ş.", short_name="İş Bankası")
        adapter = AiMatcherAdapter(DummyAiClient({"stock_id": "STK-IS", "score": 90}))
        matcher = NewsMatcher(store, ai=adapter)
        matcher.match(news("C1", title="Türkiye İş Bankası A.Ş. kâr açıkladı"))
        assert adapter.call_count == 0

    def test_94_ai_belirsiz_eslesmeye_cagrilir(self):
        adapter = AiMatcherAdapter(DummyAiClient({"stock_id": "STK-THY", "score": 72}))
        matcher = make_matcher(ai=adapter)
        nid, title = UNCERTAIN_NEWS
        matcher.match(news(nid, title=title))
        assert adapter.call_count == 1

    def test_95_ai_hata_loglanir_tarama_durmaz(self):
        adapter = AiMatcherAdapter(DummyAiClient(exc=RuntimeError("servis yok")))
        matcher = make_matcher(ai=adapter)
        nid, title = UNCERTAIN_NEWS
        res = matcher.match(news(nid, title=title))  # exception FIRLATILMAZ
        assert any(e.startswith(AI_SERVICE_ERROR) for e in adapter.errors)
        r = by_stock(res, "STK-THY")
        assert r is not None and r.needs_review is True

    def test_96_ai_gecersiz_yanit_yok_sayilir(self):
        adapter = AiMatcherAdapter(
            DummyAiClient({"stock_id": 123, "score": "yüksek"})
        )
        matcher = make_matcher(ai=adapter)
        nid, title = UNCERTAIN_NEWS
        res = matcher.match(news(nid, title=title))
        assert any(e.startswith(AI_INVALID_RESPONSE) for e in adapter.errors)
        r = by_stock(res, "STK-THY")
        assert r is not None
        assert r.match_score == 70  # degismedi
        assert r.match_method == MatchMethod.CODE

    def test_97_ai_gecerli_yanit_uygulanir(self):
        adapter = AiMatcherAdapter(
            DummyAiClient({"stock_id": "STK-IS", "score": 88, "reason": "baglam uyumlu"})
        )
        matcher = make_matcher(ai=adapter)
        nid, title = UNCERTAIN_NEWS
        res = matcher.match(news(nid, title=title))
        r = res[0]
        assert r.stock_id == "STK-IS"
        assert r.match_score == 88
        assert r.match_method == MatchMethod.AI_ASSISTED
        assert r.needs_review is True

    def test_98_ai_tek_basina_teyit_olamaz(self):
        adapter = AiMatcherAdapter(DummyAiClient({"stock_id": "STK-THY", "score": 95}))
        matcher = make_matcher(ai=adapter)
        nid, title = UNCERTAIN_NEWS
        res = matcher.match(news(nid, title=title))
        r = res[0]
        assert r.match_score == 95
        assert r.is_confirmed is False  # AI skoru teyit SAGLAMAZ
        assert r.needs_review is True

    def test_99_puan_kilidi_alanlar(self):
        banned = {"sentiment", "score", "impact", "tone", "puan", "onem", "etki"}
        for cls in (NewsRecord, NewsProcessResult, ReviewQueueItem):
            names = {f.name for f in dataclasses.fields(cls)}
            assert not (names & banned), f"{cls.__name__} yasakli alan iceriyor"
        # NewsRecord TAM 10 alan (SPEC bolum 3).
        expected = {
            "news_id", "title", "body", "source_name", "original_url",
            "published_at", "updated_at", "author", "content_type", "collected_at",
        }
        assert {f.name for f in dataclasses.fields(NewsRecord)} == expected
        assert len(dataclasses.fields(NewsRecord)) == 10
        # match_score SPEC bolum 3'te tanimli tek guven skoru alanidir.
        mr_names = {f.name for f in dataclasses.fields(MatchResult)}
        assert "match_score" in mr_names

    def test_100_puan_kilidi_fonksiyonlar_ve_ai_hata_akisi(self):
        func_names = [
            n for n, _ in inspect.getmembers(collector_module, inspect.isfunction)
        ]
        for n in func_names:
            assert "sentiment" not in n
            assert "impact" not in n
            assert "tone" not in n
            assert "puan" not in n
        assert not any(n == "score" or n.endswith("_score") for n in func_names)
        # Collector seviyesinde AI hatasi taramayi DURDURMAZ.
        adapter = AiMatcherAdapter(DummyAiClient(exc=RuntimeError("kapali")))
        matcher = make_matcher(ai=adapter)
        collector = NewsCollector(matcher, DedupeEngine(), ContentTagger(), clock=fixed_clock)
        nid, title = UNCERTAIN_NEWS
        result = collector.process([news(nid, title=title, published=T0)])
        assert isinstance(result, NewsProcessResult)
        assert len(result.review_queue) == 1
        assert any(e.startswith(AI_SERVICE_ERROR) for e in adapter.errors)
