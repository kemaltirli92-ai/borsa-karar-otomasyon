"""BLOK 15 - Veri Guveni ve Hazirlik Durumu (confidence paketi).

Her hisse icin 0-100 Tarama Veri Guveni (data_confidence) ve hazirlik
durumlarini hesaplayan modul. BU DEGER HISSE DEGERLENDIRMESI DEGILDIR,
yukselme ihtimali DEGILDIR, alim tavsiyesi DEGILDIR — verinin tamlik ve
dogrulama seviyesidir (kapsam kilidi).

Bilesenler (SPEC BLOK 15 bolum 2):
- models:     ComponentInput, ConfidenceResult, ReadyFlags, ConfidenceConfig,
              durum/yeterlilik sabitleri, hata siniflari.
- components: 12 bilesen degerlendirici + ComponentScanInputs +
              evaluate_components (girdiler enjekte: BLOK 6/8/9/10/11/12/13).
- readiness:  TAM 11 tam-hazirlik sarti (CONDITIONS), ReadinessInputs,
              ReadinessVerdict, evaluate_readiness.
- calculator: ConfidenceCalculator (agirlikli toplam + kati kurallar),
              katsayi tablosu, uyari metinleri.
- display:    DISCLAIMER_TEXT (sabit kural), DisclaimerLockedError.

KAPSAM KILIDI: hisse degerlendirmesine iliskin yasakli alan/fonksiyon
YOKTUR (SPEC bolum 3'teki yasakli adlar tanimlanmamistir; testlerle
kanitlanir).

BLOK 6-14'e DOKUNULMAZ — entegrasyonlar enjeksiyonladir. stdlib only;
gercek ag YOK; deterministik; saat enjekte.
"""
from .calculator import (
    COEFFICIENTS,
    WARNING_CRITICAL_DATA,
    WARNING_STALE_DATA,
    ConfidenceCalculator,
)
from .components import (
    ComponentScanInputs,
    evaluate_anomaly_count,
    evaluate_components,
    evaluate_corporate_check,
    evaluate_critical_fields,
    evaluate_data_freshness,
    evaluate_history_sufficiency,
    evaluate_kap_check,
    evaluate_news_check,
    evaluate_price_availability,
    evaluate_price_source_validation,
    evaluate_restriction_check,
    evaluate_symbol_verification,
    evaluate_volume_availability,
)
from .display import DISCLAIMER_TEXT, DisclaimerLockedError, get_disclaimer, set_disclaimer_text
from .models import (
    ALL_STATUSES,
    COMPONENT_NAMES,
    DEFAULT_WEIGHTS,
    FAILED,
    INSUFFICIENT_FOR_TECHNICAL,
    LIMITED_DATA,
    MISSING,
    NEW_LISTING,
    NEW_LISTING_NOTE,
    NOT_APPLICABLE,
    OK,
    PRICE_DATA_MISSING,
    REVIEW_REQUIRED,
    STALE,
    SUFFICIENT_DATA,
    UNVERIFIED,
    ComponentInput,
    ConfidenceConfig,
    ConfidenceError,
    ConfidenceResult,
    IncompleteWeightsError,
    InvalidWeightSumError,
    NegativeWeightError,
    ReadyFlags,
    UnknownComponentError,
)
from .readiness import (
    CONDITIONS,
    TRADING_HALT_NOTE,
    ReadinessInputs,
    ReadinessVerdict,
    evaluate_readiness,
)

__all__ = [
    # display
    "DISCLAIMER_TEXT",
    "DisclaimerLockedError",
    "get_disclaimer",
    "set_disclaimer_text",
    # models — durumlar
    "OK",
    "MISSING",
    "STALE",
    "UNVERIFIED",
    "FAILED",
    "NOT_APPLICABLE",
    "ALL_STATUSES",
    # models — yeterlilik etiketleri
    "SUFFICIENT_DATA",
    "LIMITED_DATA",
    "NEW_LISTING",
    "INSUFFICIENT_FOR_TECHNICAL",
    "PRICE_DATA_MISSING",
    "REVIEW_REQUIRED",
    "NEW_LISTING_NOTE",
    # models — bilesenler/agirliklar
    "COMPONENT_NAMES",
    "DEFAULT_WEIGHTS",
    # models — siniflar
    "ComponentInput",
    "ReadyFlags",
    "ConfidenceResult",
    "ConfidenceConfig",
    "ConfidenceError",
    "UnknownComponentError",
    "IncompleteWeightsError",
    "InvalidWeightSumError",
    "NegativeWeightError",
    # components
    "evaluate_price_availability",
    "evaluate_price_source_validation",
    "evaluate_volume_availability",
    "evaluate_history_sufficiency",
    "evaluate_kap_check",
    "evaluate_news_check",
    "evaluate_corporate_check",
    "evaluate_restriction_check",
    "evaluate_symbol_verification",
    "evaluate_data_freshness",
    "evaluate_anomaly_count",
    "evaluate_critical_fields",
    "ComponentScanInputs",
    "evaluate_components",
    # readiness
    "CONDITIONS",
    "TRADING_HALT_NOTE",
    "ReadinessInputs",
    "ReadinessVerdict",
    "evaluate_readiness",
    # calculator
    "COEFFICIENTS",
    "WARNING_CRITICAL_DATA",
    "WARNING_STALE_DATA",
    "ConfidenceCalculator",
]
