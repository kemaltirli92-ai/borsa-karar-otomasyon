"""BLOK 13 - Kurumsal Islemler ve Aktif Tedbirler: veri modelleri (models.py).

11 kurumsal islem tipi (ActionType), TAM 11 alanli CorporateActionRecord,
5 kayit durumu (ActionStatus), 7 tedbir tipi (RestrictionType),
TAM 7 alanli TradingRestriction, FeedPacket (frozen) ve ScanStatus.

KAPSAM KILIDI: Bu modulde kurumsal islemin/tedbirin olumlu/olumsuz
etkisine iliskin hicbir alan veya hesaplama YOKTUR (sentiment/score/
impact alani tanimlanmamistir).

Dis bagimlilik yoktur (stdlib: dataclasses, enum, typing).
Dosya/identifier ASCII; docstring'ler Turkce.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple


class ActionType(str, Enum):
    """Kurumsal islem tipleri — TAM 11 (SPEC bolum 3)."""

    DIVIDEND = "DIVIDEND"                      # temettu
    BONUS_ISSUE = "BONUS_ISSUE"                # bedelsiz
    RIGHTS_ISSUE = "RIGHTS_ISSUE"              # bedelli
    STOCK_SPLIT = "STOCK_SPLIT"                # hisse bolunmesi
    MERGER = "MERGER"                          # birlesme
    DEMERGER = "DEMERGER"                      # bolunme
    BUYBACK_PROGRAM = "BUYBACK_PROGRAM"        # geri alim programi
    BUYBACK_EXECUTION = "BUYBACK_EXECUTION"    # gerceklesen geri alim
    SHARE_SALE = "SHARE_SALE"                  # pay satisi
    OWNERSHIP_CHANGE = "OWNERSHIP_CHANGE"      # ortaklik yapisi degisikligi
    SYMBOL_CHANGE = "SYMBOL_CHANGE"            # kod degisikligi


class ActionStatus(str, Enum):
    """Kurumsal islem kayit durumu (SPEC bolum 3).

    ANNOUNCED -> EFFECTIVE -> COMPLETED gecisleri gecerlidir; gecersiz
    gecisler registry tarafindan reddedilir. CANCELLED iptal kaydini,
    SUPERSEDED yerini yeni surume birakmis eski kaydi ifade eder.
    """

    ANNOUNCED = "ANNOUNCED"
    EFFECTIVE = "EFFECTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class RestrictionType(str, Enum):
    """Aktif tedbir tipleri — TAM 7 (SPEC bolum 3)."""

    TRADING_HALT = "TRADING_HALT"                  # islem durdurma
    GROSS_SETTLEMENT = "GROSS_SETTLEMENT"          # brut takas
    ORDER_PACKAGE = "ORDER_PACKAGE"                # emir paketi
    SINGLE_PRICE = "SINGLE_PRICE"                  # tek fiyat
    MARGIN_TRADING_BAN = "MARGIN_TRADING_BAN"      # kredili islem yasagi
    SHORT_SELLING_BAN = "SHORT_SELLING_BAN"        # aciga satis yasagi
    MARKET_CHANGE = "MARKET_CHANGE"                # pazar degisikligi


@dataclass
class CorporateActionRecord:
    """Kurumsal islem kaydi — TAM 11 alan (SPEC bolum 3).

    1. stock_id 2. action_type 3. announcement_date 4. effective_date
    5. ratio (str|None, "2:1"/"0.35") 6. amount (float|None)
    7. currency (str|None) 8. source 9. official_url
    10. status (ActionStatus) 11. data_version ("action-vN")

    Not: kap_notice_no, 11 alani birebir korumak icin kayit disinda
    registry'nin baglam alani olarak tutulur (BLOK 7/9 ile uyum).
    """

    stock_id: str
    action_type: ActionType
    announcement_date: str
    effective_date: str
    ratio: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    source: str = ""
    official_url: Optional[str] = None
    status: ActionStatus = ActionStatus.ANNOUNCED
    data_version: str = "action-v1"


@dataclass
class TradingRestriction:
    """Aktif tedbir kaydi — TAM 7 alan (SPEC bolum 3).

    1. restriction_type 2. start_date 3. end_date (None = acik uclu)
    4. is_active 5. source 6. official_url 7. collected_at

    stock_id baglami registry icinde tutulur (alan degildir).
    MARKET_CHANGE icin hedef pazar bilgisi source/official_url ile
    izlenir (ayri alan YOK — 7 alan korunur).
    is_active bayragi registry tarafindan enjekte saatle OTOMATIK
    yeniden hesaplanir.
    """

    restriction_type: RestrictionType
    start_date: str
    end_date: Optional[str] = None
    is_active: bool = True
    source: str = ""
    official_url: Optional[str] = None
    collected_at: str = ""


@dataclass
class ScanStatus:
    """SuspensionPolicy.scan_status ciktisi (SPEC bolum 6).

    keep_in_scan: hisse taramada KALIR (aktif islem durdurmada bile True;
    taramadan ASLA silinmez).
    history_protected: gecmis grafik verisi korunur.
    show_as_normal: normal hisse gibi gosterilsin mi.
    scoring_ready: skorlamaya hazir mi (aktif TRADING_HALT varsa False).
    active_halts: aktif TRADING_HALT kayitlari.
    notes: risk notlari (TRADING_HALT disindaki tedbirler scoring_ready'yi
    kapatmaz; sadece risk notu olarak tasir).
    """

    keep_in_scan: bool
    history_protected: bool
    show_as_normal: bool
    scoring_ready: bool
    active_halts: Tuple[TradingRestriction, ...] = ()
    notes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class FeedPacket:
    """Sonraki modullere aktarilan DEGISMEZ kurumsal veri paketi (SPEC bolum 7).

    actions_raw: ham kayitlar (tum status — ANNOUNCED/EFFECTIVE/COMPLETED/
    CANCELLED/SUPERSEDED).
    actions_validated: dogrulanmis kayitlar (EFFECTIVE/COMPLETED +
    validated_ids ile isaretlenenler).
    restrictions_active / restrictions_history: anlik aktif tedbirler ve
    arsiv dahil tum tedbir gecmisi.
    scoring_ready / suspension_flag: SuspensionPolicy ciktisi.
    packet_version: her uretimde artan surum numarasi.

    Paket frozen'dir ve listeler tuple kopyasidir: uretimden sonra
    registry degisse bile paket sessizce degismez (eski rapor verisi
    korunur ilkesi).
    """

    stock_id: str
    actions_raw: Tuple[CorporateActionRecord, ...] = ()
    actions_validated: Tuple[CorporateActionRecord, ...] = ()
    restrictions_active: Tuple[TradingRestriction, ...] = ()
    restrictions_history: Tuple[TradingRestriction, ...] = ()
    scoring_ready: bool = True
    suspension_flag: bool = False
    packet_version: int = 0
