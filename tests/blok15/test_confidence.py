"""BLOK 15 - Veri Guveni ve Hazirlik Durumu: TAM 100 pytest testi.

Kategoriler (toplam = 100, SPEC BLOK 15 bolum 10):
1. Tam veri: 12 bilesen OK -> confidence 100, tum ready'ler True (14)
2. Kismi veri: bazi bilesenler MISSING/UNVERIFIED -> confidence araligi,
   missing_fields (16)
3. Kritik eksik: critical FAILED -> ust sinir + uyari + favorite False (14)
4. Eski veri: STALE -> uyari + favorite False, technical_ready etkilenmez (12)
5. Aktif tedbir: TRADING_HALT -> scoring_ready False, technical_ready True
   kalabilir (12)
6. Yeni halka arz: NEW_LISTING -> sinirli gecmis, favorite False, not (10)
7. Agirlik yonetimi: set_weights, toplam dogrulama, bilinmeyen bilesen
   reddi, NOT_APPLICABLE dagitimi (12)
8. Kapsam kilidi + disclaimer: yasakli alan yok, metin sabit (10)

Hicbir test ag erisimi yapmaz: tum girdiler mock/enjekte, saat enjekte
(sabit 2024-06-28). BLOK 6-14'e DOKUNULMAZ; entegrasyonlar enjeksiyonla.
"""
from __future__ import annotations

import inspect
from dataclasses import fields
from datetime import date

import pytest

from app.services.stock_scanning.confidence import (
    ALL_STATUSES,
    COEFFICIENTS,
    COMPONENT_NAMES,
    CONDITIONS,
    DEFAULT_WEIGHTS,
    DISCLAIMER_TEXT,
    FAILED,
    LIMITED_DATA,
    MISSING,
    NEW_LISTING,
    NEW_LISTING_NOTE,
    NOT_APPLICABLE,
    OK,
    PRICE_DATA_MISSING,
    SUFFICIENT_DATA,
    STALE,
    UNVERIFIED,
    ComponentInput,
    ComponentScanInputs,
    ConfidenceCalculator,
    ConfidenceConfig,
    ConfidenceResult,
    DisclaimerLockedError,
    IncompleteWeightsError,
    InvalidWeightSumError,
    NegativeWeightError,
    ReadinessInputs,
    ReadyFlags,
    UnknownComponentError,
    evaluate_anomaly_count,
    evaluate_components,
    evaluate_corporate_check,
    evaluate_critical_fields,
    evaluate_data_freshness,
    evaluate_history_sufficiency,
    evaluate_kap_check,
    evaluate_news_check,
    evaluate_readiness,
    evaluate_restriction_check,
    evaluate_symbol_verification,
    evaluate_volume_availability,
    set_disclaimer_text,
)
from app.services.stock_scanning.confidence import (
    calculator as calculator_mod,
    components as components_mod,
    display as display_mod,
    models as models_mod,
    readiness as readiness_mod,
)
from app.services.stock_scanning import confidence as confidence_pkg

# ---------------------------------------------------------------------- #
# Sabitler + yardimcilar
# ---------------------------------------------------------------------- #
STOCK = "STK-000001"
FIXED_TODAY = date(2024, 6, 28)  # enjekte sabit saat

# Kapsam kilidi: yasakli token'lar (kaynak taramasi + alan adi taramasi)
FORBIDDEN = ["hisse_skoru", "stock_score", "signal", "puan", "buy_sell"]


def fixed_clock():
    """Deterministik 'bugun' (data_freshness icin)."""
    return FIXED_TODAY


def ok_scan(**over) -> ComponentScanInputs:
    """Tum girdileri saglikli tarama paketi (override destekli)."""
    base = dict(
        last_price=123.45,
        source_validation="VALIDATED",
        volume=1_000_000,
        sufficiency_label=SUFFICIENT_DATA,
        kap_status="COMPLETED",
        news_status="COMPLETED",
        corporate_status="COMPLETED",
        restriction_status="COMPLETED",
        trading_halt_active=False,
        verification_status="VERIFIED",
        last_data_date="2024-06-27",
        anomaly_count=0,
        critical_missing=[],
    )
    base.update(over)
    return ComponentScanInputs(**base)


def ok_readiness(**over) -> ReadinessInputs:
    """11 sarti saglanmis hazirlik girdisi (override destekli)."""
    base = dict(
        symbol_verified=True,
        xk100_member=True,
        has_valid_price=True,
        has_valid_volume=True,
        has_last_trade_date=True,
        kap_check_ok=True,
        news_check_ok=True,
        corporate_check_ok=True,
        restriction_check_ok=True,
        source_validation_ok=True,
        sufficiency_label_present=True,
        trading_halt_active=False,
        critical_missing=[],
        stale_present=False,
        sufficiency_label=SUFFICIENT_DATA,
    )
    base.update(over)
    return ReadinessInputs(**base)


def assess(scan=None, ready=None, config=None) -> ConfidenceResult:
    """Uctan uca enjekte hatt: bilesenler + hazirlik -> ConfidenceResult."""
    scan = scan if scan is not None else ok_scan()
    ready = ready if ready is not None else ok_readiness()
    cfg = config or ConfidenceConfig()
    comps = evaluate_components(
        scan, clock=fixed_clock, stale_days_limit=cfg.stale_days_limit
    )
    verdict = evaluate_readiness(ready)
    return ConfidenceCalculator(cfg).calculate(STOCK, comps, verdict)


def all_ok_components() -> dict:
    """12 bileseni dogrudan OK ComponentInput olarak uretir."""
    return {name: ComponentInput(OK, "test") for name in COMPONENT_NAMES}


# ====================================================================== #
# 1. TAM VERI (14 test)
# ====================================================================== #
class TestTamVeri:
    """12 bilesen OK -> confidence 100, tum hazirlik bayraklari True."""

    def test_all_components_ok_confidence_100(self):
        r = assess()
        assert r.data_confidence == 100

    def test_all_ready_flags_true(self):
        r = assess()
        assert r.technical_ready is True
        assert r.scoring_ready is True
        assert r.favorite_eligible is True

    def test_no_warnings_no_missing(self):
        r = assess()
        assert r.warnings == []
        assert r.missing_fields == []

    def test_component_scores_all_ok(self):
        r = assess()
        assert len(r.component_scores) == 12
        for name, info in r.component_scores.items():
            assert info["status"] == OK, name
            assert info["coefficient"] == 1.0, name
            assert info["active"] is True, name

    def test_disclaimer_in_result(self):
        r = assess()
        assert r.disclaimer == DISCLAIMER_TEXT

    def test_confidence_is_int(self):
        r = assess()
        assert isinstance(r.data_confidence, int)
        assert r.data_confidence == 100

    def test_exactly_11_conditions(self):
        assert len(CONDITIONS) == 11

    def test_verdict_failing_conditions_empty(self):
        v = evaluate_readiness(ok_readiness())
        assert v.failing_conditions == []
        assert v.technical_ready is True

    def test_all_12_evaluators_ok(self):
        comps = evaluate_components(ok_scan(), clock=fixed_clock)
        assert len(comps) == 12
        for name in COMPONENT_NAMES:
            assert comps[name].status == OK, name

    def test_result_stock_id_passthrough(self):
        r = assess()
        assert r.stock_id == STOCK

    def test_contributions_sum_to_100(self):
        r = assess()
        total = sum(info["contribution"] for info in r.component_scores.values())
        assert abs(total - 100.0) < 1e-6

    def test_ready_flags_property(self):
        r = assess()
        flags = r.ready_flags
        assert isinstance(flags, ReadyFlags)
        assert (flags.technical_ready, flags.scoring_ready, flags.favorite_eligible) == (
            True,
            True,
            True,
        )

    def test_result_field_set(self):
        names = {f.name for f in fields(ConfidenceResult)}
        assert names == {
            "stock_id",
            "data_confidence",
            "technical_ready",
            "scoring_ready",
            "favorite_eligible",
            "missing_fields",
            "component_scores",
            "warnings",
            "disclaimer",
        }

    def test_verdict_notes_empty(self):
        v = evaluate_readiness(ok_readiness())
        assert v.notes == []


# ====================================================================== #
# 2. KISMI VERI (16 test)
# ====================================================================== #
class TestKismiVeri:
    """Bazi bilesenler MISSING/UNVERIFIED -> confidence araligi, missing_fields."""

    def test_missing_price_confidence_85(self):
        # price_availability agirligi 15 -> 100 - 15 = 85
        r = assess(scan=ok_scan(last_price=None))
        assert r.data_confidence == 85

    def test_missing_fields_contains_price(self):
        r = assess(scan=ok_scan(last_price=None))
        assert "price_availability" in r.missing_fields

    def test_unverified_symbol_halves_weight(self):
        # symbol_verification agirligi 8, katsayi 0.5 -> 100 - 4 = 96
        r = assess(scan=ok_scan(verification_status="SYMBOL_VERIFICATION_PENDING"))
        assert r.data_confidence == 96

    def test_two_missing_components(self):
        # price(15) + volume(10) MISSING -> 75
        r = assess(scan=ok_scan(last_price=None, volume=None))
        assert r.data_confidence == 75
        assert set(r.missing_fields) == {"price_availability", "volume_availability"}

    def test_missing_news_confidence_94(self):
        # news_check agirligi 6 -> 94
        r = assess(scan=ok_scan(news_status=None))
        assert r.data_confidence == 94

    def test_missing_fields_canonical_order(self):
        r = assess(scan=ok_scan(volume=None, last_price=None))
        assert r.missing_fields == ["price_availability", "volume_availability"]

    def test_symbol_pending_evaluator(self):
        comp = evaluate_symbol_verification("SYMBOL_VERIFICATION_PENDING")
        assert comp.status == UNVERIFIED

    def test_symbol_verified_evaluator(self):
        assert evaluate_symbol_verification("VERIFIED").status == OK

    def test_missing_volume_evaluator(self):
        assert evaluate_volume_availability(None).status == MISSING

    def test_zero_volume_is_not_ok(self):
        # gercek sifir hacim OK DEGIL (SPEC bolum 4, madde 3)
        comp = evaluate_volume_availability(0)
        assert comp.status != OK
        assert comp.status == UNVERIFIED

    def test_negative_volume_failed(self):
        assert evaluate_volume_availability(-5).status == FAILED

    def test_limited_data_unverified(self):
        comp = evaluate_history_sufficiency(LIMITED_DATA)
        assert comp.status == UNVERIFIED

    def test_kap_pending_unverified(self):
        assert evaluate_kap_check("PENDING").status == UNVERIFIED

    def test_news_pending_unverified(self):
        assert evaluate_news_check("IN_PROGRESS").status == UNVERIFIED

    def test_corporate_pending_unverified(self):
        assert evaluate_corporate_check(False).status == UNVERIFIED

    def test_confidence_never_100_with_missing(self):
        # en kucuk agirlikli bilesen (critical_fields=5) MISSING olsa bile
        # confidence otomatik 100 OLAMAZ (SPEC bolum 6)
        r = assess(scan=ok_scan(critical_missing=None))
        assert "critical_fields" in r.missing_fields
        assert r.data_confidence < 100


# ====================================================================== #
# 3. KRITIK EKSIK (14 test)
# ====================================================================== #
class TestKritikEksik:
    """critical FAILED -> ust sinir + uyari + favorite_eligible False."""

    def test_critical_evaluator_failed(self):
        comp = evaluate_critical_fields(["isin", "company_name"])
        assert comp.status == FAILED

    def test_critical_detail_lists_fields(self):
        comp = evaluate_critical_fields(["isin", "company_name"])
        assert "isin" in comp.detail
        assert "company_name" in comp.detail

    def test_critical_ok_when_empty(self):
        assert evaluate_critical_fields([]).status == OK

    def test_critical_none_is_missing(self):
        assert evaluate_critical_fields(None).status == MISSING

    def test_confidence_capped_at_60(self):
        # ham skor 95 (critical agirligi 5) -> ust sinir 60
        r = assess(scan=ok_scan(critical_missing=["isin"]))
        assert r.data_confidence == 60

    def test_kritik_warning(self):
        r = assess(scan=ok_scan(critical_missing=["isin"]))
        assert "KRITIK VERI EKSIK" in r.warnings

    def test_favorite_false_hard(self):
        # verdict kritik eksikten habersiz olsa bile calculator kati uygular
        r = assess(scan=ok_scan(critical_missing=["isin"]))
        assert r.favorite_eligible is False

    def test_scoring_false_with_critical_component(self):
        r = assess(scan=ok_scan(critical_missing=["isin"]))
        assert r.scoring_ready is False

    def test_technical_ready_unaffected(self):
        # kritik eksik 11 sart arasinda degil -> technical_ready True kalabilir
        r = assess(scan=ok_scan(critical_missing=["isin"]))
        assert r.technical_ready is True

    def test_cap_configurable(self):
        cfg = ConfidenceConfig(critical_cap=50)
        r = assess(scan=ok_scan(critical_missing=["isin"]), config=cfg)
        assert r.data_confidence == 50

    def test_cap_not_applied_when_raw_below(self):
        # ham skor zaten kap altinda: 5 eksik bilesen (15+10+8+8+8=49) +
        # critical FAILED (5) -> 100 - 54 = 46 (< 60, kap degistirmez)
        r = assess(
            scan=ok_scan(
                last_price=None,
                volume=None,
                last_data_date=None,
                anomaly_count=None,
                verification_status=None,
                critical_missing=["isin"],
            )
        )
        assert r.data_confidence == 46

    def test_critical_and_stale_both_warnings(self):
        r = assess(scan=ok_scan(critical_missing=["isin"], last_data_date="2024-06-01"))
        assert "KRITIK VERI EKSIK" in r.warnings
        assert "ESKI VERI" in r.warnings
        assert r.favorite_eligible is False

    def test_readiness_critical_blocks_scoring(self):
        v = evaluate_readiness(ok_readiness(critical_missing=["isin"]))
        assert v.technical_ready is True
        assert v.scoring_ready is False
        assert v.favorite_eligible is False

    def test_cap_boundary_with_other_missing(self):
        # news MISSING (6) + critical FAILED (5): ham 89 -> kap 60
        r = assess(scan=ok_scan(critical_missing=["isin"], news_status=None))
        assert r.data_confidence == 60
        assert "news_check" in r.missing_fields


# ====================================================================== #
# 4. ESKI VERI (12 test)
# ====================================================================== #
class TestEskiVeri:
    """STALE -> ESKI VERI uyarisi + favorite False; technical_ready etkilenmez."""

    def test_fresh_data_ok(self):
        comp = evaluate_data_freshness("2024-06-27", clock=fixed_clock, stale_days_limit=5)
        assert comp.status == OK

    def test_stale_data_status(self):
        comp = evaluate_data_freshness("2024-06-01", clock=fixed_clock, stale_days_limit=5)
        assert comp.status == STALE

    def test_boundary_exactly_limit_ok(self):
        # 2024-06-25 -> tam 3 gun (sinir 3) -> OK
        comp = evaluate_data_freshness("2024-06-25", clock=fixed_clock, stale_days_limit=3)
        assert comp.status == OK

    def test_boundary_limit_plus_one_stale(self):
        # 2024-06-24 -> 4 gun (sinir 3) -> STALE
        comp = evaluate_data_freshness("2024-06-24", clock=fixed_clock, stale_days_limit=3)
        assert comp.status == STALE

    def test_missing_date_is_missing(self):
        assert evaluate_data_freshness(None, clock=fixed_clock).status == MISSING

    def test_future_date_ok(self):
        comp = evaluate_data_freshness("2024-07-05", clock=fixed_clock, stale_days_limit=5)
        assert comp.status == OK

    def test_stale_warning_eski_veri(self):
        r = assess(scan=ok_scan(last_data_date="2024-06-01"))
        assert "ESKI VERI" in r.warnings

    def test_stale_favorite_false(self):
        r = assess(
            scan=ok_scan(last_data_date="2024-06-01"),
            ready=ok_readiness(stale_present=True),
        )
        assert r.favorite_eligible is False

    def test_stale_technical_ready_unaffected(self):
        r = assess(scan=ok_scan(last_data_date="2024-06-01"))
        assert r.technical_ready is True

    def test_stale_scoring_ready_stays_true(self):
        # scoring_ready = technical AND halt yok AND kritik yok — STALE engellemez
        r = assess(scan=ok_scan(last_data_date="2024-06-01"))
        assert r.scoring_ready is True

    def test_stale_confidence_half_penalty(self):
        # data_freshness agirligi 8, katsayi 0.5 -> 100 - 4 = 96
        r = assess(scan=ok_scan(last_data_date="2024-06-01"))
        assert r.data_confidence == 96

    def test_stale_hard_enforcement_despite_verdict(self):
        # verdict stale_present=False dese bile calculator STALE bileseni yakalar
        r = assess(
            scan=ok_scan(last_data_date="2024-06-01"),
            ready=ok_readiness(stale_present=False),
        )
        assert r.favorite_eligible is False
        assert "ESKI VERI" in r.warnings


# ====================================================================== #
# 5. AKTIF TEDBIR (12 test)
# ====================================================================== #
class TestAktifTedbir:
    """TRADING_HALT -> scoring_ready False; technical_ready True kalabilir."""

    def test_halt_restriction_failed(self):
        comp = evaluate_restriction_check("COMPLETED", trading_halt_active=True)
        assert comp.status == FAILED

    def test_halt_detail_mentions_halt(self):
        comp = evaluate_restriction_check("COMPLETED", trading_halt_active=True)
        assert "TRADING_HALT" in comp.detail

    def test_no_halt_restriction_ok(self):
        comp = evaluate_restriction_check("COMPLETED", trading_halt_active=False)
        assert comp.status == OK

    def test_restriction_missing(self):
        assert evaluate_restriction_check(None).status == MISSING

    def test_restriction_pending(self):
        assert evaluate_restriction_check("PENDING").status == UNVERIFIED

    def test_restriction_error(self):
        assert evaluate_restriction_check("ERROR").status == FAILED

    def test_scoring_false_with_halt(self):
        r = assess(
            scan=ok_scan(trading_halt_active=True),
            ready=ok_readiness(trading_halt_active=True),
        )
        assert r.scoring_ready is False

    def test_scoring_false_via_component_hard_rule(self):
        # verdict halt bayragini tasimasa bile restriction_check FAILED
        # calculator tarafindan scoring_ready=False yapilir (SPEC bolum 9)
        r = assess(
            scan=ok_scan(trading_halt_active=True),
            ready=ok_readiness(trading_halt_active=False),
        )
        assert r.scoring_ready is False

    def test_technical_ready_true_with_halt(self):
        r = assess(
            scan=ok_scan(trading_halt_active=True),
            ready=ok_readiness(trading_halt_active=True),
        )
        assert r.technical_ready is True

    def test_favorite_false_with_halt(self):
        r = assess(
            scan=ok_scan(trading_halt_active=True),
            ready=ok_readiness(trading_halt_active=True),
        )
        assert r.favorite_eligible is False

    def test_halt_confidence_impact_93(self):
        # restriction_check agirligi 7 -> 100 - 7 = 93
        r = assess(
            scan=ok_scan(trading_halt_active=True),
            ready=ok_readiness(trading_halt_active=True),
        )
        assert r.data_confidence == 93

    def test_halt_verdict_notes_and_failing(self):
        v = evaluate_readiness(ok_readiness(trading_halt_active=True))
        assert v.failing_conditions == []
        assert v.technical_ready is True
        assert v.scoring_ready is False
        assert v.favorite_eligible is False
        assert any("TRADING_HALT" in note for note in v.notes)


# ====================================================================== #
# 6. YENI HALKA ARZ (10 test)
# ====================================================================== #
class TestYeniHalkaArz:
    """NEW_LISTING -> LIMITED sayilir, favorite False, ozel not."""

    def test_new_listing_status_unverified(self):
        comp = evaluate_history_sufficiency(NEW_LISTING)
        assert comp.status == UNVERIFIED

    def test_new_listing_not_not_applicable(self):
        # SPEC bolum 9: history_sufficiency NOT_APPLICABLE DEGIL, LIMITED sayilir
        comp = evaluate_history_sufficiency(NEW_LISTING)
        assert comp.status != NOT_APPLICABLE

    def test_new_listing_detail_note(self):
        comp = evaluate_history_sufficiency(NEW_LISTING)
        assert NEW_LISTING_NOTE == "Yeni halka arz — sinirli gecmis"
        assert NEW_LISTING_NOTE in comp.detail

    def test_new_listing_verdict_note(self):
        v = evaluate_readiness(ok_readiness(sufficiency_label=NEW_LISTING))
        assert v.new_listing is True
        assert NEW_LISTING_NOTE in v.notes

    def test_new_listing_favorite_false(self):
        r = assess(
            scan=ok_scan(sufficiency_label=NEW_LISTING),
            ready=ok_readiness(sufficiency_label=NEW_LISTING),
        )
        assert r.favorite_eligible is False

    def test_new_listing_note_in_warnings(self):
        r = assess(
            scan=ok_scan(sufficiency_label=NEW_LISTING),
            ready=ok_readiness(sufficiency_label=NEW_LISTING),
        )
        assert NEW_LISTING_NOTE in r.warnings

    def test_new_listing_confidence_not_zeroed(self):
        # eksik gecmis "sifir veri" yapilmaz: 8 * 0.5 = 4 kayip -> 96
        r = assess(
            scan=ok_scan(sufficiency_label=NEW_LISTING),
            ready=ok_readiness(sufficiency_label=NEW_LISTING),
        )
        assert r.data_confidence == 96
        assert "history_sufficiency" not in r.missing_fields

    def test_new_listing_technical_and_scoring_ready(self):
        # etiket mevcut (sart 11) -> technical_ready True; halt/kritik yok
        # -> scoring_ready True (favorite ayri kural)
        r = assess(
            scan=ok_scan(sufficiency_label=NEW_LISTING),
            ready=ok_readiness(sufficiency_label=NEW_LISTING),
        )
        assert r.technical_ready is True
        assert r.scoring_ready is True

    def test_new_listing_vs_price_data_missing(self):
        comp = evaluate_history_sufficiency(PRICE_DATA_MISSING)
        assert comp.status == MISSING
        r = assess(
            scan=ok_scan(sufficiency_label=PRICE_DATA_MISSING),
            ready=ok_readiness(
                sufficiency_label_present=False, sufficiency_label=PRICE_DATA_MISSING
            ),
        )
        assert "history_sufficiency" in r.missing_fields
        assert r.data_confidence == 92  # 100 - 8
        assert r.technical_ready is False  # sart 11: etiket mevcut degil
        assert "SUFFICIENCY_LABEL_MISSING" in evaluate_readiness(
            ok_readiness(sufficiency_label_present=False)
        ).failing_conditions

    def test_limited_data_same_treatment_confidence(self):
        # LIMITED_DATA da UNVERIFIED katsayisi (0.5) alir; favorite'i engellemez
        r_limited = assess(
            scan=ok_scan(sufficiency_label=LIMITED_DATA),
            ready=ok_readiness(sufficiency_label=LIMITED_DATA),
        )
        r_new = assess(
            scan=ok_scan(sufficiency_label=NEW_LISTING),
            ready=ok_readiness(sufficiency_label=NEW_LISTING),
        )
        assert r_limited.data_confidence == r_new.data_confidence == 96
        assert r_limited.favorite_eligible is True
        assert r_new.favorite_eligible is False


# ====================================================================== #
# 7. AGIRLIK YONETIMI (12 test)
# ====================================================================== #
class TestAgirlikYonetimi:
    """set_weights, toplam dogrulama, bilinmeyen bilesen reddi, N/A dagitimi."""

    def test_default_weights_sum_100(self):
        cfg = ConfidenceConfig()
        assert cfg.total_weight == 100.0

    def test_default_weights_exact(self):
        assert DEFAULT_WEIGHTS == {
            "price_availability": 15,
            "price_source_validation": 10,
            "volume_availability": 10,
            "history_sufficiency": 8,
            "kap_check": 8,
            "news_check": 6,
            "corporate_check": 7,
            "restriction_check": 7,
            "symbol_verification": 8,
            "data_freshness": 8,
            "anomaly_count": 8,
            "critical_fields": 5,
        }

    def test_set_weights_updates_and_version(self):
        cfg = ConfidenceConfig()
        assert cfg.config_version == 1
        new = dict(DEFAULT_WEIGHTS)
        new["price_availability"] = 20
        new["news_check"] = 1  # toplam yine 100
        cfg.set_weights(new)
        assert cfg.weights["price_availability"] == 20.0
        assert cfg.config_version == 2
        # yeni agirlikla hesap: price MISSING -> 100 - 20 = 80
        comps = all_ok_components()
        comps["price_availability"] = ComponentInput(MISSING, "yok")
        r = ConfidenceCalculator(cfg).calculate(
            STOCK, comps, evaluate_readiness(ok_readiness())
        )
        assert r.data_confidence == 80

    def test_unknown_component_rejected(self):
        cfg = ConfidenceConfig()
        bad = dict(DEFAULT_WEIGHTS)
        bad["hayali_bilesen"] = 5
        with pytest.raises(UnknownComponentError):
            cfg.set_weights(bad)
        assert cfg.config_version == 1  # basarisiz deneme versiyonu artirmaz

    def test_incomplete_weights_rejected(self):
        cfg = ConfidenceConfig()
        partial = dict(DEFAULT_WEIGHTS)
        del partial["news_check"]
        with pytest.raises(IncompleteWeightsError):
            cfg.set_weights(partial)

    def test_sum_not_100_raises(self):
        cfg = ConfidenceConfig()
        bad = dict(DEFAULT_WEIGHTS)
        bad["news_check"] = 10  # toplam 104
        with pytest.raises(InvalidWeightSumError):
            cfg.set_weights(bad)
        assert cfg.config_version == 1

    def test_normalize_scales_to_100(self):
        cfg = ConfidenceConfig()
        w = {name: 5.0 for name in COMPONENT_NAMES}  # toplam 60
        cfg.set_weights(w, normalize=True)
        assert abs(cfg.total_weight - 100.0) < 1e-9
        assert abs(cfg.weights["price_availability"] - (5.0 * 100.0 / 60.0)) < 1e-9
        assert cfg.audit_log[-1]["normalized"] is True

    def test_validate_weights_flag(self):
        cfg = ConfidenceConfig()
        assert cfg.validate_weights(dict(DEFAULT_WEIGHTS)) is True
        bad = dict(DEFAULT_WEIGHTS)
        bad["news_check"] = 10
        assert cfg.validate_weights(bad) is False

    def test_audit_note_recorded(self):
        cfg = ConfidenceConfig()
        cfg.set_weights(dict(DEFAULT_WEIGHTS))
        assert len(cfg.audit_log) == 1
        entry = cfg.audit_log[0]
        assert entry["action"] == "set_weights"
        assert entry["version"] == cfg.config_version == 2

    def test_negative_weight_rejected(self):
        cfg = ConfidenceConfig()
        bad = dict(DEFAULT_WEIGHTS)
        bad["news_check"] = -1
        bad["kap_check"] = 9
        with pytest.raises(NegativeWeightError):
            cfg.set_weights(bad)

    def test_not_applicable_redistributes_weight(self):
        # news N/A (6) + symbol UNVERIFIED (8, 0.5):
        # aktif toplam 94, katki 90 -> 90/94*100 = 95.74 -> 96
        comps = all_ok_components()
        comps["news_check"] = ComponentInput(NOT_APPLICABLE, "uygulanamaz")
        comps["symbol_verification"] = ComponentInput(UNVERIFIED, "bekliyor")
        r = ConfidenceCalculator().calculate(
            STOCK, comps, evaluate_readiness(ok_readiness())
        )
        assert r.data_confidence == 96
        assert r.component_scores["news_check"]["active"] is False
        assert r.component_scores["news_check"]["contribution"] == 0.0

    def test_not_applicable_all_active_ok_100(self):
        # NOT_APPLICABLE=1.0 katsayi; kalan agirliklar orantili dagitilir
        comps = all_ok_components()
        comps["kap_check"] = ComponentInput(NOT_APPLICABLE, "uygulanamaz")
        comps["news_check"] = ComponentInput(NOT_APPLICABLE, "uygulanamaz")
        r = ConfidenceCalculator().calculate(
            STOCK, comps, evaluate_readiness(ok_readiness())
        )
        assert r.data_confidence == 100
        total = sum(info["contribution"] for info in r.component_scores.values())
        assert abs(total - 100.0) < 0.01  # gosterim alani 4 basamak yuvarlanir


# ====================================================================== #
# 8. KAPSAM KILIDI + DISCLAIMER (10 test)
# ====================================================================== #
class TestKapsamKilidiVeDisclaimer:
    """Yasakli alan/fonksiyon YOK; aciklama metni sabit ve kilitli."""

    def test_disclaimer_text_exact(self):
        assert (
            DISCLAIMER_TEXT
            == "Bu oran verinin tamlik ve dogrulama seviyesidir, "
            "hissenin yukselme ihtimali degil."
        )

    def test_disclaimer_in_result(self):
        r = assess()
        assert r.disclaimer == DISCLAIMER_TEXT

    def test_disclaimer_change_attempt_raises(self):
        with pytest.raises(DisclaimerLockedError):
            set_disclaimer_text("yeni metin")
        # metin degismedi
        assert display_mod.DISCLAIMER_TEXT == DISCLAIMER_TEXT

    def test_no_forbidden_fields_in_result(self):
        for f in fields(ConfidenceResult):
            low = f.name.lower()
            for token in FORBIDDEN:
                assert token not in low, f.name
        for attr in dir(ConfidenceResult):
            low = attr.lower()
            for token in FORBIDDEN:
                assert token not in low, attr

    def test_no_forbidden_in_models_source(self):
        src = inspect.getsource(models_mod).lower()
        for token in FORBIDDEN:
            assert token not in src, token

    def test_no_forbidden_in_calculator_source(self):
        src = inspect.getsource(calculator_mod).lower()
        for token in FORBIDDEN:
            assert token not in src, token

    def test_no_forbidden_in_components_source(self):
        src = inspect.getsource(components_mod).lower()
        for token in FORBIDDEN:
            assert token not in src, token

    def test_no_forbidden_in_readiness_source(self):
        src = inspect.getsource(readiness_mod).lower()
        for token in FORBIDDEN:
            assert token not in src, token

    def test_no_forbidden_in_display_and_init_source(self):
        src = (
            inspect.getsource(display_mod) + inspect.getsource(confidence_pkg)
        ).lower()
        for token in FORBIDDEN:
            assert token not in src, token

    def test_component_input_and_ready_flags_scope(self):
        ci_names = {f.name for f in fields(ComponentInput)}
        assert ci_names == {"status", "detail"}
        rf_names = {f.name for f in fields(ReadyFlags)}
        assert rf_names == {"technical_ready", "scoring_ready", "favorite_eligible"}
        # durum sozlugu tam 6 deger
        assert set(ALL_STATUSES) == {
            OK,
            MISSING,
            STALE,
            UNVERIFIED,
            FAILED,
            NOT_APPLICABLE,
        }
        # katsayi tablosu SPEC bolum 6 ile birebir
        assert COEFFICIENTS == {
            OK: 1.0,
            NOT_APPLICABLE: 1.0,
            UNVERIFIED: 0.5,
            STALE: 0.5,
            MISSING: 0.0,
            FAILED: 0.0,
        }
