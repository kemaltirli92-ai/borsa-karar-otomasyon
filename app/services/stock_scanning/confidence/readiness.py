"""BLOK 15 - Hazirlik sartlari (readiness.py).

Tam hazirlik (technical_ready=True) icin TAM 11 sart (SPEC BLOK 15 bolum 7):

1.  stock_id VERIFIED                 (BLOK 6)
2.  aktif XK100 uyeligi
3.  gecerli son fiyat                 (BLOK 8)
4.  gecerli hacim                     (BLOK 10)
5.  son islem tarihi mevcut
6.  KAP kontrol OK                    (BLOK 11)
7.  haber kontrol OK                  (BLOK 12)
8.  kurumsal islem kontrol OK         (BLOK 13)
9.  tedbir kontrol OK (kontrol tamam) (BLOK 13)
10. fiyat kaynak dogrulamasi OK       (BLOK 8)
11. veri yeterlilik etiketi mevcut    (BLOK 9)

Turev bayraklar:
- scoring_ready    = technical_ready AND aktif TRADING_HALT YOK (BLOK 13)
                     AND kritik eksik yok
- favorite_eligible = scoring_ready AND STALE yok AND kritik eksik yok
                     AND yeni halka arz (NEW_LISTING) degil
  (nihai favori SECIMI Bolum 4'te — bu blok sadece uygunluk etiketi uretir)

ReadinessVerdict: technical_ready, failing_conditions (list), notes +
kolaylik alanlari (scoring_ready, favorite_eligible, new_listing).

Ozel senaryolar (SPEC bolum 9):
- Aktif tedbir: TRADING_HALT -> scoring_ready=False; technical_ready
  ETKILENMEZ (sart 9 kontrolun tamamlanmasina bakar, tedbir sonucuna degil).
- Yeni halka arz: NEW_LISTING -> favorite_eligible=False +
  "Yeni halka arz — sinirli gecmis" notu.

Tum girdiler ENJEKTEdir; gercek ag YOK; deterministik.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .models import NEW_LISTING, NEW_LISTING_NOTE

# Aktif islem durdurma notu (bilgilendirme)
TRADING_HALT_NOTE = "Aktif islem durdurma tedbiri (TRADING_HALT)"

# ---------------------------------------------------------------------------
# TAM 11 sart: (basarisizlik kodu, ReadinessInputs alan adi)
# ---------------------------------------------------------------------------
CONDITIONS = (
    ("SYMBOL_NOT_VERIFIED", "symbol_verified"),
    ("NOT_XK100_MEMBER", "xk100_member"),
    ("VALID_PRICE_MISSING", "has_valid_price"),
    ("VALID_VOLUME_MISSING", "has_valid_volume"),
    ("LAST_TRADE_DATE_MISSING", "has_last_trade_date"),
    ("KAP_CHECK_NOT_OK", "kap_check_ok"),
    ("NEWS_CHECK_NOT_OK", "news_check_ok"),
    ("CORPORATE_CHECK_NOT_OK", "corporate_check_ok"),
    ("RESTRICTION_CHECK_NOT_OK", "restriction_check_ok"),
    ("SOURCE_VALIDATION_NOT_OK", "source_validation_ok"),
    ("SUFFICIENCY_LABEL_MISSING", "sufficiency_label_present"),
)


@dataclass
class ReadinessInputs:
    """11 sart + turev bayraklar icin enjekte girdiler.

    ilk 11 alan: teknik hazirlik sartlari (bool).
    trading_halt_active: aktif TRADING_HALT bayragi (BLOK 13).
    critical_missing: kritik eksik alan adlari (varsa scoring/favorite False).
    stale_present: STALE bilesen var mi (varsa favorite False).
    sufficiency_label: BLOK 9 yeterlilik etiketi (NEW_LISTING tespiti).
    """

    symbol_verified: bool = False
    xk100_member: bool = False
    has_valid_price: bool = False
    has_valid_volume: bool = False
    has_last_trade_date: bool = False
    kap_check_ok: bool = False
    news_check_ok: bool = False
    corporate_check_ok: bool = False
    restriction_check_ok: bool = False
    source_validation_ok: bool = False
    sufficiency_label_present: bool = False
    trading_halt_active: bool = False
    critical_missing: List[str] = field(default_factory=list)
    stale_present: bool = False
    sufficiency_label: Optional[str] = None


@dataclass
class ReadinessVerdict:
    """Hazirlik karari (SPEC bolum 7).

    technical_ready: 11 sartin tamami saglandi mi.
    failing_conditions: basarisiz sart kodlari (CONDITIONS).
    notes: bilgilendirme notlari (yeni halka arz, aktif tedbir).
    scoring_ready / favorite_eligible: turev bayraklar.
    new_listing: NEW_LISTING etiketi tespit edildi mi.
    """

    technical_ready: bool
    failing_conditions: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    scoring_ready: bool = False
    favorite_eligible: bool = False
    new_listing: bool = False


def evaluate_readiness(inputs: ReadinessInputs) -> ReadinessVerdict:
    """11 sarti + turev bayraklari degerlendirir (deterministik)."""
    failing = [
        code for code, attr in CONDITIONS if not bool(getattr(inputs, attr))
    ]
    technical_ready = not failing

    new_listing = (
        inputs.sufficiency_label is not None
        and str(inputs.sufficiency_label).strip().upper() == NEW_LISTING
    )

    notes: List[str] = []
    if new_listing:
        notes.append(NEW_LISTING_NOTE)
    if inputs.trading_halt_active:
        notes.append(TRADING_HALT_NOTE)

    has_critical = bool(inputs.critical_missing)

    scoring_ready = (
        technical_ready and not inputs.trading_halt_active and not has_critical
    )
    favorite_eligible = (
        scoring_ready
        and not inputs.stale_present
        and not has_critical
        and not new_listing
    )

    return ReadinessVerdict(
        technical_ready=technical_ready,
        failing_conditions=failing,
        notes=notes,
        scoring_ready=scoring_ready,
        favorite_eligible=favorite_eligible,
        new_listing=new_listing,
    )
