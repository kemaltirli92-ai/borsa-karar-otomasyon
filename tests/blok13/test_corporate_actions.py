"""BLOK 13 - Kurumsal Islemler ve Aktif Tedbirler: TAM 100 pytest testi.

Kategoriler (toplam = 100, SPEC BLOK 13 bolum 9):
1. Kurumsal islem kaydi: 11 tip, 11 alan, durum gecisleri (16).
2. Kurumsal islem surumu: duzeltilmis kayit, SUPERSEDED zinciri,
   eski surum korunur, data_version artisi (14).
3. Cift kayit engeli: kurumsal + tedbir dedupe (12).
4. Aktif tedbir: 7 tip kayit, is_active hesaplama, bayrak uyusmazligi (14).
5. Suresi biten tedbir: otomatik pasif, arsiv korunur (10).
6. Islem durdurma: taramadan silinmez, grafik korunur, normal gosterilmez,
   scoring_ready=False, bitince True (16).
7. Paket aktarimi: ham/dogrulanmis ayrimi, frozen paket, packet_version (10).
8. Collector: kaynak hatasi taramayi durdurmaz + puan kilidi (8).

Hicbir test gercek aga erismez: tum kaynaklar mock/enjekte edilir.
Saat enjekte edilir (deterministik). stdlib only.
"""
from __future__ import annotations

import dataclasses
import inspect
from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from app.services.stock_scanning.corporate_actions import collector as collector_module
from app.services.stock_scanning.corporate_actions.collector import (
    SOURCE_OK,
    SOURCE_UNAVAILABLE,
    CollectionReport,
    CorporateCollector,
)
from app.services.stock_scanning.corporate_actions.feed import CorporateFeed
from app.services.stock_scanning.corporate_actions.models import (
    ActionStatus,
    ActionType,
    CorporateActionRecord,
    FeedPacket,
    RestrictionType,
    ScanStatus,
    TradingRestriction,
)
from app.services.stock_scanning.corporate_actions.registry import (
    OUTCOME_CANCELLED,
    OUTCOME_DUPLICATE,
    OUTCOME_REJECTED,
    OUTCOME_REVISION,
    OUTCOME_STATUS_UPDATED,
    OUTCOME_STORED,
    REASON_CANCEL_TARGET_NOT_FOUND,
    REASON_INVALID_TRANSITION,
    VALID_TRANSITIONS,
    CorporateActionRegistry,
)
from app.services.stock_scanning.corporate_actions.restrictions import (
    REVIEW_REQUIRED,
    RestrictionRegistry,
    RestrictionResult,
)
from app.services.stock_scanning.corporate_actions.suspension import SuspensionPolicy

FIXED_NOW = date(2025, 6, 10)
FIXED_ISO = "2025-06-10T00:00:00Z"


def fixed_clock_str() -> str:
    return FIXED_ISO


class MutableClock:
    """Enjekte edilebilir degistirilebilir saat (deterministik testler icin)."""

    def __init__(self, current: date = FIXED_NOW):
        self.current = current

    def __call__(self) -> date:
        return self.current

    def set(self, value: date) -> None:
        self.current = value


def make_record(
    stock_id="STK-THY",
    action_type=ActionType.DIVIDEND,
    announcement_date="2025-05-01",
    effective_date="2025-06-01",
    ratio=None,
    amount=1.5,
    currency="TRY",
    status=ActionStatus.ANNOUNCED,
    source="KAP",
) -> CorporateActionRecord:
    return CorporateActionRecord(
        stock_id=stock_id,
        action_type=action_type,
        announcement_date=announcement_date,
        effective_date=effective_date,
        ratio=ratio,
        amount=amount,
        currency=currency,
        source=source,
        status=status,
    )


def make_restriction(
    restriction_type=RestrictionType.TRADING_HALT,
    start_date="2025-06-09",
    end_date="2025-06-12",
    is_active=True,
    source="BIST",
) -> TradingRestriction:
    return TradingRestriction(
        restriction_type=restriction_type,
        start_date=start_date,
        end_date=end_date,
        is_active=is_active,
        source=source,
    )


def build_stack(clock=None):
    """Registry + restriction + policy + feed zinciri (saat enjekte)."""
    clk = clock or MutableClock()
    actions = CorporateActionRegistry(clock=fixed_clock_str)
    restrictions = RestrictionRegistry(clock=clk)
    policy = SuspensionPolicy(restrictions)
    feed = CorporateFeed(actions, restrictions, policy)
    return actions, restrictions, policy, feed, clk


class FakeActionSource:
    """Enjekte kurumsal islem kaynagi (mock; gercek ag YOK)."""

    def __init__(self, data=None, fail_for=()):
        self.data = data or {}
        self.fail_for = set(fail_for)
        self.calls = []

    def fetch_actions(self, stock_id):
        self.calls.append(stock_id)
        if stock_id in self.fail_for:
            raise IOError("kurumsal kaynak kapali")
        return self.data.get(stock_id, [])


class FakeRestrictionSource:
    """Enjekte tedbir kaynagi (mock; gercek ag YOK)."""

    def __init__(self, data=None, fail_for=()):
        self.data = data or {}
        self.fail_for = set(fail_for)
        self.calls = []

    def fetch_restrictions(self, stock_id):
        self.calls.append(stock_id)
        if stock_id in self.fail_for:
            raise IOError("tedbir kaynagi kapali")
        return self.data.get(stock_id, [])


# ================================================================== #
# Kategori 1 — Kurumsal islem kaydi (16 test)
# ================================================================== #
class TestKurumsalIslemKaydi:
    """11 tip, 11 alan dogrulama, durum gecisleri."""

    def test_01_action_type_enum_tam_11(self):
        expected = {
            "DIVIDEND", "BONUS_ISSUE", "RIGHTS_ISSUE", "STOCK_SPLIT",
            "MERGER", "DEMERGER", "BUYBACK_PROGRAM", "BUYBACK_EXECUTION",
            "SHARE_SALE", "OWNERSHIP_CHANGE", "SYMBOL_CHANGE",
        }
        assert len(ActionType) == 11
        assert {t.name for t in ActionType} == expected

    def test_02_action_status_enum_5(self):
        assert len(ActionStatus) == 5
        assert {s.name for s in ActionStatus} == {
            "ANNOUNCED", "EFFECTIVE", "COMPLETED", "CANCELLED", "SUPERSEDED",
        }

    def test_03_restriction_type_enum_7(self):
        expected = {
            "TRADING_HALT", "GROSS_SETTLEMENT", "ORDER_PACKAGE",
            "SINGLE_PRICE", "MARGIN_TRADING_BAN", "SHORT_SELLING_BAN",
            "MARKET_CHANGE",
        }
        assert len(RestrictionType) == 7
        assert {t.name for t in RestrictionType} == expected

    def test_04_record_tam_11_alan(self):
        names = [f.name for f in dataclasses.fields(CorporateActionRecord)]
        assert names == [
            "stock_id", "action_type", "announcement_date", "effective_date",
            "ratio", "amount", "currency", "source", "official_url",
            "status", "data_version",
        ]
        assert len(names) == 11

    def test_05_restriction_tam_7_alan(self):
        names = [f.name for f in dataclasses.fields(TradingRestriction)]
        assert names == [
            "restriction_type", "start_date", "end_date", "is_active",
            "source", "official_url", "collected_at",
        ]
        assert len(names) == 7

    def test_06_kayit_stored_data_version_action_v1(self):
        reg = CorporateActionRegistry(clock=fixed_clock_str)
        rec = make_record()
        res = reg.register(rec, kap_notice_no="KAP-1")
        assert res.outcome == OUTCOME_STORED
        assert res.data_version == "action-v1"
        assert rec.status == ActionStatus.ANNOUNCED
        assert reg.get_actions("STK-THY") == [rec]

    def test_07_on_bir_tipin_tumu_kaydedilir(self):
        reg = CorporateActionRegistry(clock=fixed_clock_str)
        for i, atype in enumerate(ActionType):
            rec = make_record(action_type=atype, effective_date=f"2025-06-{i + 1:02d}")
            res = reg.register(rec, kap_notice_no=f"KAP-{i}")
            assert res.outcome == OUTCOME_STORED
        assert len(reg.get_actions("STK-THY")) == 11

    def test_08_gecis_announced_effective(self):
        reg = CorporateActionRegistry(clock=fixed_clock_str)
        reg.register(make_record(), kap_notice_no="KAP-1")
        res = reg.update_status(
            "STK-THY", ActionType.DIVIDEND, "2025-06-01", ActionStatus.EFFECTIVE
        )
        assert res.outcome == OUTCOME_STATUS_UPDATED
        assert reg.get_actions("STK-THY")[0].status == ActionStatus.EFFECTIVE

    def test_09_gecis_effective_completed(self):
        reg = CorporateActionRegistry(clock=fixed_clock_str)
        reg.register(make_record(), kap_notice_no="KAP-1")
        reg.update_status("STK-THY", ActionType.DIVIDEND, "2025-06-01", ActionStatus.EFFECTIVE)
        res = reg.update_status(
            "STK-THY", ActionType.DIVIDEND, "2025-06-01", ActionStatus.COMPLETED
        )
        assert res.outcome == OUTCOME_STATUS_UPDATED
        assert reg.get_actions("STK-THY")[0].status == ActionStatus.COMPLETED

    def test_10_gecersiz_gecis_completed_announced_reddedilir(self):
        reg = CorporateActionRegistry(clock=fixed_clock_str)
        reg.register(make_record(), kap_notice_no="KAP-1")
        reg.update_status("STK-THY", ActionType.DIVIDEND, "2025-06-01", ActionStatus.EFFECTIVE)
        reg.update_status("STK-THY", ActionType.DIVIDEND, "2025-06-01", ActionStatus.COMPLETED)
        res = reg.update_status(
            "STK-THY", ActionType.DIVIDEND, "2025-06-01", ActionStatus.ANNOUNCED
        )
        assert res.outcome == OUTCOME_REJECTED
        assert res.reason == REASON_INVALID_TRANSITION
        assert reg.get_actions("STK-THY")[0].status == ActionStatus.COMPLETED

    def test_11_gecersiz_gecis_announced_completed_reddedilir(self):
        reg = CorporateActionRegistry(clock=fixed_clock_str)
        reg.register(make_record(), kap_notice_no="KAP-1")
        res = reg.update_status(
            "STK-THY", ActionType.DIVIDEND, "2025-06-01", ActionStatus.COMPLETED
        )
        assert res.outcome == OUTCOME_REJECTED
        assert res.reason == REASON_INVALID_TRANSITION
        assert reg.get_actions("STK-THY")[0].status == ActionStatus.ANNOUNCED

    def test_12_superseded_terminal_gecis_yok(self):
        reg = CorporateActionRegistry(clock=fixed_clock_str)
        reg.register(make_record(), kap_notice_no="KAP-1")
        reg.register(make_record(amount=1.6), kap_notice_no="KAP-2")
        history = reg.get_history("STK-THY", (ActionType.DIVIDEND, "2025-06-01"))
        assert history[0].status == ActionStatus.SUPERSEDED
        assert VALID_TRANSITIONS[ActionStatus.SUPERSEDED] == set()
        # Guncel surum zincir disina itilemez: update sadece son surume
        # uygulanir; eski surum SUPERSEDED kalir.
        reg.update_status("STK-THY", ActionType.DIVIDEND, "2025-06-01", ActionStatus.EFFECTIVE)
        history = reg.get_history("STK-THY", (ActionType.DIVIDEND, "2025-06-01"))
        assert history[0].status == ActionStatus.SUPERSEDED

    def test_13_cancelled_terminal_ve_iptal_ayri_kayit(self):
        reg = CorporateActionRegistry(clock=fixed_clock_str)
        reg.register(make_record(), kap_notice_no="KAP-1")
        res = reg.update_status(
            "STK-THY", ActionType.DIVIDEND, "2025-06-01",
            ActionStatus.CANCELLED, kap_notice_no="KAP-C1",
        )
        assert res.outcome == OUTCOME_CANCELLED
        assert VALID_TRANSITIONS[ActionStatus.CANCELLED] == set()
        cancels = reg.get_cancellations("STK-THY", (ActionType.DIVIDEND, "2025-06-01"))
        assert len(cancels) == 1
        assert cancels[0].status == ActionStatus.CANCELLED
        # Hedef kayit korunur: status degismez.
        assert reg.get_actions("STK-THY")[0].status == ActionStatus.ANNOUNCED

    def test_14_get_actions_status_filtresi(self):
        reg = CorporateActionRegistry(clock=fixed_clock_str)
        reg.register(make_record(effective_date="2025-06-01"), kap_notice_no="KAP-1")
        reg.register(make_record(effective_date="2025-06-02"), kap_notice_no="KAP-2")
        reg.update_status("STK-THY", ActionType.DIVIDEND, "2025-06-01", ActionStatus.EFFECTIVE)
        effective = reg.get_actions("STK-THY", status=ActionStatus.EFFECTIVE)
        announced = reg.get_actions("STK-THY", status=ActionStatus.ANNOUNCED)
        assert len(effective) == 1 and effective[0].effective_date == "2025-06-01"
        assert len(announced) == 1 and announced[0].effective_date == "2025-06-02"

    def test_15_get_actions_bilinmeyen_hisse_bos(self):
        reg = CorporateActionRegistry(clock=fixed_clock_str)
        assert reg.get_actions("STK-YOK") == []
        assert reg.get_all_records("STK-YOK") == []
        assert reg.get_history("STK-YOK", (ActionType.DIVIDEND, "2025-06-01")) == []

    def test_16_symbol_change_notu_blok6_uyumu(self):
        symbol_history = object()  # BLOK 6 baglantisi enjekte
        reg = CorporateActionRegistry(clock=fixed_clock_str, symbol_history=symbol_history)
        rec = make_record(action_type=ActionType.SYMBOL_CHANGE, ratio="OLD->NEW")
        res = reg.register(rec, kap_notice_no="KAP-S1")
        assert res.outcome == OUTCOME_STORED
        assert len(reg.symbol_notes) == 1
        assert "eski kod silinmez" in reg.symbol_notes[0]
        # Baglanti sadece enjekte; registry tarafindan degistirilmez.
        assert reg.symbol_history is symbol_history


# ================================================================== #
# Kategori 2 — Kurumsal islem surumu (14 test)
# ================================================================== #
class TestSurumZinciri:
    """Duzeltilmis kayit, SUPERSEDED zinciri, eski surum korunur."""

    def test_17_duzeltilmis_kayit_revision_chain(self):
        reg = CorporateActionRegistry(clock=fixed_clock_str)
        reg.register(make_record(), kap_notice_no="KAP-1")
        res = reg.register(make_record(amount=1.6), kap_notice_no="KAP-2")
        assert res.outcome == OUTCOME_REVISION

    def test_18_eski_kayit_superseded_olur(self):
        reg = CorporateActionRegistry(clock=fixed_clock_str)
        old = make_record()
        reg.register(old, kap_notice_no="KAP-1")
        reg.register(make_record(amount=1.6), kap_notice_no="KAP-2")
        assert old.status == ActionStatus.SUPERSEDED

    def test_19_yeni_kayit_data_version_action_v2(self):
        reg = CorporateActionRegistry(clock=fixed_clock_str)
        reg.register(make_record(), kap_notice_no="KAP-1")
        new = make_record(amount=1.6)
        res = reg.register(new, kap_notice_no="KAP-2")
        assert new.data_version == "action-v2"
        assert res.data_version == "action-v2"
        assert res.superseded_version == "action-v1"

    def test_20_eski_surum_silinmez(self):
        reg = CorporateActionRegistry(clock=fixed_clock_str)
        reg.register(make_record(), kap_notice_no="KAP-1")
        reg.register(make_record(amount=1.6), kap_notice_no="KAP-2")
        history = reg.get_history("STK-THY", (ActionType.DIVIDEND, "2025-06-01"))
        assert len(history) == 2
        assert history[0].amount == 1.5  # eski surum korunur

    def test_21_ucuncu_revizyon_action_v3(self):
        reg = CorporateActionRegistry(clock=fixed_clock_str)
        reg.register(make_record(), kap_notice_no="KAP-1")
        reg.register(make_record(amount=1.6), kap_notice_no="KAP-2")
        third = make_record(amount=1.7)
        res = reg.register(third, kap_notice_no="KAP-3")
        assert res.outcome == OUTCOME_REVISION
        assert third.data_version == "action-v3"
        assert len(reg.get_history("STK-THY", (ActionType.DIVIDEND, "2025-06-01"))) == 3

    def test_22_get_history_zincir_sirali(self):
        reg = CorporateActionRegistry(clock=fixed_clock_str)
        reg.register(make_record(), kap_notice_no="KAP-1")
        reg.register(make_record(amount=1.6), kap_notice_no="KAP-2")
        reg.register(make_record(amount=1.7), kap_notice_no="KAP-3")
        history = reg.get_history("STK-THY", (ActionType.DIVIDEND, "2025-06-01"))
        assert [h.data_version for h in history] == ["action-v1", "action-v2", "action-v3"]
        assert [h.status for h in history] == [
            ActionStatus.SUPERSEDED, ActionStatus.SUPERSEDED, ActionStatus.ANNOUNCED,
        ]

    def test_23_get_actions_sadece_guncel_surum(self):
        reg = CorporateActionRegistry(clock=fixed_clock_str)
        reg.register(make_record(), kap_notice_no="KAP-1")
        reg.register(make_record(amount=1.6), kap_notice_no="KAP-2")
        actions = reg.get_actions("STK-THY")
        assert len(actions) == 1
        assert actions[0].data_version == "action-v2"
        assert actions[0].amount == 1.6

    def test_24_ayni_kap_notice_revizyon_degil_duplicate(self):
        reg = CorporateActionRegistry(clock=fixed_clock_str)
        reg.register(make_record(), kap_notice_no="KAP-1")
        res = reg.register(make_record(amount=9.9), kap_notice_no="KAP-1")
        assert res.outcome == OUTCOME_DUPLICATE
        assert len(reg.get_history("STK-THY", (ActionType.DIVIDEND, "2025-06-01"))) == 1

    def test_25_revision_yeni_kaydin_statusu_korunur(self):
        reg = CorporateActionRegistry(clock=fixed_clock_str)
        reg.register(make_record(), kap_notice_no="KAP-1")
        new = make_record(amount=1.6, status=ActionStatus.EFFECTIVE)
        res = reg.register(new, kap_notice_no="KAP-2")
        assert res.outcome == OUTCOME_REVISION
        assert new.status == ActionStatus.EFFECTIVE

    def test_26_superseded_kayitlar_status_filtresiyle_okunur(self):
        reg = CorporateActionRegistry(clock=fixed_clock_str)
        reg.register(make_record(), kap_notice_no="KAP-1")
        reg.register(make_record(amount=1.6), kap_notice_no="KAP-2")
        superseded = reg.get_actions("STK-THY", status=ActionStatus.SUPERSEDED)
        assert len(superseded) == 1
        assert superseded[0].data_version == "action-v1"

    def test_27_revision_sonrasi_update_status_guncel_kayda(self):
        reg = CorporateActionRegistry(clock=fixed_clock_str)
        reg.register(make_record(), kap_notice_no="KAP-1")
        reg.register(make_record(amount=1.6), kap_notice_no="KAP-2")
        res = reg.update_status(
            "STK-THY", ActionType.DIVIDEND, "2025-06-01", ActionStatus.EFFECTIVE
        )
        assert res.outcome == OUTCOME_STATUS_UPDATED
        assert res.data_version == "action-v2"
        history = reg.get_history("STK-THY", (ActionType.DIVIDEND, "2025-06-01"))
        assert [h.status for h in history] == [
            ActionStatus.SUPERSEDED, ActionStatus.EFFECTIVE,
        ]

    def test_28_farkli_hisse_ayni_olay_ayri_zincir(self):
        reg = CorporateActionRegistry(clock=fixed_clock_str)
        reg.register(make_record(stock_id="STK-A"), kap_notice_no="KAP-1")
        res = reg.register(make_record(stock_id="STK-B"), kap_notice_no="KAP-1")
        assert res.outcome == OUTCOME_STORED
        assert res.data_version == "action-v1"
        assert len(reg.get_actions("STK-A")) == 1
        assert len(reg.get_actions("STK-B")) == 1

    def test_29_farkli_effective_date_ayri_olay(self):
        reg = CorporateActionRegistry(clock=fixed_clock_str)
        reg.register(make_record(effective_date="2025-06-01"), kap_notice_no="KAP-1")
        res = reg.register(make_record(effective_date="2025-07-01"), kap_notice_no="KAP-1")
        assert res.outcome == OUTCOME_STORED
        assert res.data_version == "action-v1"
        assert len(reg.get_actions("STK-THY")) == 2

    def test_30_kap_notice_baglamda_11_alan_korunur(self):
        reg = CorporateActionRegistry(clock=fixed_clock_str)
        reg.register(make_record(), kap_notice_no="KAP-1")
        reg.register(make_record(amount=1.6), kap_notice_no="KAP-2")
        assert reg.kap_notice_no_of(
            "STK-THY", ActionType.DIVIDEND, "2025-06-01", "action-v1"
        ) == "KAP-1"
        assert reg.kap_notice_no_of(
            "STK-THY", ActionType.DIVIDEND, "2025-06-01", "action-v2"
        ) == "KAP-2"
        # kap_notice_no kaydin 11 alani arasinda YOK.
        assert "kap_notice_no" not in {
            f.name for f in dataclasses.fields(CorporateActionRecord)
        }
        assert len(dataclasses.fields(CorporateActionRecord)) == 11


# ================================================================== #
# Kategori 3 — Cift kayit engeli (12 test)
# ================================================================== #
class TestCiftKayitEngeli:
    """Kurumsal islem + tedbir dedupe kurallari."""

    def test_31_ayni_kayit_ikinci_kez_duplicate(self):
        reg = CorporateActionRegistry(clock=fixed_clock_str)
        reg.register(make_record(), kap_notice_no="KAP-1")
        res = reg.register(make_record(), kap_notice_no="KAP-1")
        assert res.outcome == OUTCOME_DUPLICATE

    def test_32_duplicate_kayit_eklenmez(self):
        reg = CorporateActionRegistry(clock=fixed_clock_str)
        reg.register(make_record(), kap_notice_no="KAP-1")
        reg.register(make_record(), kap_notice_no="KAP-1")
        assert len(reg.get_all_records("STK-THY")) == 1
        assert len(reg.get_actions("STK-THY")) == 1

    def test_33_duplicate_sayaci_artar(self):
        reg = CorporateActionRegistry(clock=fixed_clock_str)
        reg.register(make_record(), kap_notice_no="KAP-1")
        reg.register(make_record(), kap_notice_no="KAP-1")
        reg.register(make_record(), kap_notice_no="KAP-1")
        assert reg.duplicate_count == 2

    def test_34_dedupe_dort_bilesenli_anahtar(self):
        reg = CorporateActionRegistry(clock=fixed_clock_str)
        reg.register(make_record(), kap_notice_no="KAP-1")
        # 1) ayni 4 bilesen -> duplicate
        assert reg.register(make_record(), kap_notice_no="KAP-1").outcome == OUTCOME_DUPLICATE
        # 2) kap_notice_no farkli -> revizyon (anahtarin kap bileseni)
        assert reg.register(make_record(), kap_notice_no="KAP-2").outcome == OUTCOME_REVISION
        # 3) effective_date farkli -> yeni olay
        assert reg.register(
            make_record(effective_date="2025-07-01"), kap_notice_no="KAP-1"
        ).outcome == OUTCOME_STORED
        # 4) action_type farkli -> yeni olay
        assert reg.register(
            make_record(action_type=ActionType.BONUS_ISSUE), kap_notice_no="KAP-1"
        ).outcome == OUTCOME_STORED
        # 5) stock_id farkli -> yeni olay
        assert reg.register(
            make_record(stock_id="STK-DIGER"), kap_notice_no="KAP-1"
        ).outcome == OUTCOME_STORED

    def test_35_farkli_kap_notice_duplicate_degil_revizyon(self):
        reg = CorporateActionRegistry(clock=fixed_clock_str)
        reg.register(make_record(), kap_notice_no="KAP-1")
        res = reg.register(make_record(amount=2.0), kap_notice_no="KAP-2")
        assert res.outcome == OUTCOME_REVISION
        assert reg.duplicate_count == 0

    def test_36_farkli_stock_ayni_kap_notice_duplicate_degil(self):
        reg = CorporateActionRegistry(clock=fixed_clock_str)
        reg.register(make_record(stock_id="STK-A"), kap_notice_no="KAP-9")
        res = reg.register(make_record(stock_id="STK-B"), kap_notice_no="KAP-9")
        assert res.outcome == OUTCOME_STORED
        assert reg.duplicate_count == 0

    def test_37_cancel_kaydi_tekrari_duplicate(self):
        reg = CorporateActionRegistry(clock=fixed_clock_str)
        reg.register(make_record(), kap_notice_no="KAP-1")
        first = reg.update_status(
            "STK-THY", ActionType.DIVIDEND, "2025-06-01",
            ActionStatus.CANCELLED, kap_notice_no="KAP-C1",
        )
        second = reg.update_status(
            "STK-THY", ActionType.DIVIDEND, "2025-06-01",
            ActionStatus.CANCELLED, kap_notice_no="KAP-C1",
        )
        assert first.outcome == OUTCOME_CANCELLED
        assert second.outcome == OUTCOME_DUPLICATE
        cancels = reg.get_cancellations("STK-THY", (ActionType.DIVIDEND, "2025-06-01"))
        assert len(cancels) == 1

    def test_38_tedbir_ayni_ucleme_duplicate(self):
        rreg = RestrictionRegistry(clock=MutableClock())
        rreg.register("STK-THY", make_restriction())
        res = rreg.register("STK-THY", make_restriction())
        assert res.outcome == OUTCOME_DUPLICATE

    def test_39_tedbir_duplicate_eklenmez(self):
        rreg = RestrictionRegistry(clock=MutableClock())
        rreg.register("STK-THY", make_restriction())
        rreg.register("STK-THY", make_restriction())
        assert len(rreg.restriction_history("STK-THY")) == 1
        assert rreg.duplicate_count == 1

    def test_40_tedbir_farkli_start_ayri_kayit(self):
        rreg = RestrictionRegistry(clock=MutableClock())
        rreg.register("STK-THY", make_restriction(start_date="2025-06-01"))
        res = rreg.register("STK-THY", make_restriction(start_date="2025-06-05"))
        assert res.outcome == OUTCOME_STORED
        assert len(rreg.restriction_history("STK-THY")) == 2

    def test_41_tedbir_farkli_tip_ayni_baslangic_ayri(self):
        rreg = RestrictionRegistry(clock=MutableClock())
        rreg.register("STK-THY", make_restriction())
        res = rreg.register(
            "STK-THY",
            make_restriction(restriction_type=RestrictionType.GROSS_SETTLEMENT),
        )
        assert res.outcome == OUTCOME_STORED
        assert len(rreg.restriction_history("STK-THY")) == 2

    def test_42_tedbir_farkli_hisse_ayni_tedbir_ayri(self):
        rreg = RestrictionRegistry(clock=MutableClock())
        rreg.register("STK-A", make_restriction())
        res = rreg.register("STK-B", make_restriction())
        assert res.outcome == OUTCOME_STORED
        assert rreg.duplicate_count == 0
        assert len(rreg.restriction_history("STK-A")) == 1
        assert len(rreg.restriction_history("STK-B")) == 1


# ================================================================== #
# Kategori 4 — Aktif tedbir (14 test)
# ================================================================== #
class TestAktifTedbir:
    """7 tip kayit, is_active hesaplama, bayrak uyusmazligi."""

    def test_43_tedbir_kaydi_stored(self):
        rreg = RestrictionRegistry(clock=MutableClock())
        res = rreg.register("STK-THY", make_restriction())
        assert res.outcome == OUTCOME_STORED
        assert res.review_required is False

    def test_44_yedi_tedbir_tipi_kaydedilir(self):
        rreg = RestrictionRegistry(clock=MutableClock())
        for i, rtype in enumerate(RestrictionType):
            res = rreg.register(
                "STK-THY",
                make_restriction(
                    restriction_type=rtype,
                    start_date=f"2025-06-0{i + 1}",
                    end_date="2025-06-28",
                ),
            )
            assert res.outcome == OUTCOME_STORED
        assert len(rreg.active_restrictions("STK-THY")) == 7

    def test_45_is_active_bugun_aralikta_true(self):
        rreg = RestrictionRegistry(clock=MutableClock())
        rec = make_restriction(start_date="2025-06-01", end_date="2025-06-30")
        rreg.register("STK-THY", rec)
        assert rec.is_active is True

    def test_46_is_active_end_none_acik_uclu(self):
        rreg = RestrictionRegistry(clock=MutableClock())
        rec = make_restriction(start_date="2025-06-01", end_date=None)
        rreg.register("STK-THY", rec)
        assert rec.is_active is True
        assert rreg.active_restrictions("STK-THY") == [rec]

    def test_47_is_active_baslangic_gelecekte_false(self):
        rreg = RestrictionRegistry(clock=MutableClock())
        rec = make_restriction(start_date="2025-07-01", end_date="2025-07-10")
        rreg.register("STK-THY", rec)
        assert rec.is_active is False
        assert rreg.active_restrictions("STK-THY") == []

    def test_48_is_active_bitis_bugun_dahil_true(self):
        rreg = RestrictionRegistry(clock=MutableClock())
        rec = make_restriction(start_date="2025-06-01", end_date="2025-06-10")
        rreg.register("STK-THY", rec)
        assert rec.is_active is True  # end_date bugune esit -> dahil

    def test_49_is_active_saat_enjekte_yeniden_hesap(self):
        clk = MutableClock(date(2025, 6, 1))
        rreg = RestrictionRegistry(clock=clk)
        rec = make_restriction(start_date="2025-06-10", end_date="2025-06-20")
        rreg.register("STK-THY", rec)
        assert rec.is_active is False
        clk.set(date(2025, 6, 10))
        assert rreg.active_restrictions("STK-THY") == [rec]
        assert rec.is_active is True

    def test_50_bayrak_uyusmazligi_review_required(self):
        rreg = RestrictionRegistry(clock=MutableClock())
        # Bayrak False ama hesaplanan True -> uyumsuzluk
        rec = make_restriction(start_date="2025-06-01", end_date="2025-06-30",
                               is_active=False)
        res = rreg.register("STK-THY", rec)
        assert res.review_required is True
        assert res.reason == REVIEW_REQUIRED
        # Hesaplanan deger esastir.
        assert rec.is_active is True

    def test_51_uyusmazlikta_kayit_yine_saklanir(self):
        rreg = RestrictionRegistry(clock=MutableClock())
        rec = make_restriction(is_active=False)
        res = rreg.register("STK-THY", rec)
        assert res.outcome == OUTCOME_STORED
        assert rec in rreg.restriction_history("STK-THY")
        assert rreg.review_items("STK-THY") == [rec]
        assert rreg.review_reason("STK-THY", rec) == REVIEW_REQUIRED

    def test_52_uyusan_bayrak_review_degil(self):
        rreg = RestrictionRegistry(clock=MutableClock())
        rec = make_restriction(is_active=True)
        res = rreg.register("STK-THY", rec)
        assert res.review_required is False
        assert rreg.review_items("STK-THY") == []

    def test_53_active_restrictions_sadece_aktifler(self):
        rreg = RestrictionRegistry(clock=MutableClock())
        aktif = make_restriction(start_date="2025-06-01", end_date="2025-06-30")
        bitmis = make_restriction(
            restriction_type=RestrictionType.GROSS_SETTLEMENT,
            start_date="2025-05-01", end_date="2025-05-31",
        )
        rreg.register("STK-THY", aktif)
        rreg.register("STK-THY", bitmis)
        active = rreg.active_restrictions("STK-THY")
        assert active == [aktif]
        assert active[0].restriction_type == RestrictionType.TRADING_HALT

    def test_54_restriction_history_tumu(self):
        rreg = RestrictionRegistry(clock=MutableClock())
        aktif = make_restriction(start_date="2025-06-01", end_date="2025-06-30")
        bitmis = make_restriction(
            restriction_type=RestrictionType.GROSS_SETTLEMENT,
            start_date="2025-05-01", end_date="2025-05-31",
        )
        rreg.register("STK-THY", aktif)
        rreg.register("STK-THY", bitmis)
        history = rreg.restriction_history("STK-THY")
        assert len(history) == 2
        assert {r.restriction_type for r in history} == {
            RestrictionType.TRADING_HALT, RestrictionType.GROSS_SETTLEMENT,
        }

    def test_55_market_change_7_alan_korunur(self):
        rreg = RestrictionRegistry(clock=MutableClock())
        rec = make_restriction(
            restriction_type=RestrictionType.MARKET_CHANGE,
            start_date="2025-06-10", end_date=None,
            source="BIST:YildizPazar->AnaPazar",
        )
        res = rreg.register("STK-THY", rec)
        assert res.outcome == OUTCOME_STORED
        # Hedef pazar source/official_url ile izlenir; ayri alan YOK (7 alan).
        assert len(dataclasses.fields(TradingRestriction)) == 7
        assert "YildizPazar" in rec.source
        assert not hasattr(rec, "target_market")

    def test_56_collected_at_enjekte_saat_damgasi(self):
        rreg = RestrictionRegistry(clock=MutableClock())
        rec = make_restriction()
        assert rec.collected_at == ""
        rreg.register("STK-THY", rec)
        assert rec.collected_at == FIXED_NOW.isoformat()


# ================================================================== #
# Kategori 5 — Suresi biten tedbir (10 test)
# ================================================================== #
class TestSuresiBitenTedbir:
    """Otomatik pasiflesme; arsiv korunur."""

    def test_57_suresi_biten_otomatik_pasif(self):
        rreg = RestrictionRegistry(clock=MutableClock())
        rec = make_restriction(start_date="2025-05-01", end_date="2025-05-31")
        rreg.register("STK-THY", rec)
        assert rec.is_active is False

    def test_58_suresi_biten_kayit_korunur(self):
        rreg = RestrictionRegistry(clock=MutableClock())
        rec = make_restriction(start_date="2025-05-01", end_date="2025-05-31")
        rreg.register("STK-THY", rec)
        assert rreg.restriction_history("STK-THY") == [rec]

    def test_59_suresi_biten_active_listesinde_yok(self):
        rreg = RestrictionRegistry(clock=MutableClock())
        rreg.register("STK-THY", make_restriction(
            start_date="2025-05-01", end_date="2025-05-31"))
        assert rreg.active_restrictions("STK-THY") == []

    def test_60_saat_ilerleyince_aktif_tedbir_pasiflesir(self):
        clk = MutableClock(date(2025, 6, 5))
        rreg = RestrictionRegistry(clock=clk)
        rec = make_restriction(start_date="2025-06-01", end_date="2025-06-10")
        rreg.register("STK-THY", rec)
        assert rec.is_active is True
        clk.set(date(2025, 6, 11))
        assert rreg.active_restrictions("STK-THY") == []
        assert rec.is_active is False

    def test_61_acik_uclu_tedbir_bitmez(self):
        clk = MutableClock()
        rreg = RestrictionRegistry(clock=clk)
        rec = make_restriction(start_date="2025-06-01", end_date=None)
        rreg.register("STK-THY", rec)
        clk.set(date(2030, 1, 1))
        assert rreg.active_restrictions("STK-THY") == [rec]
        assert rec.is_active is True

    def test_62_karisik_tedbirler_durum_korunur(self):
        clk = MutableClock(date(2025, 6, 5))
        rreg = RestrictionRegistry(clock=clk)
        kisa = make_restriction(start_date="2025-06-01", end_date="2025-06-10")
        uzun = make_restriction(
            restriction_type=RestrictionType.GROSS_SETTLEMENT,
            start_date="2025-06-01", end_date="2025-06-30",
        )
        rreg.register("STK-THY", kisa)
        rreg.register("STK-THY", uzun)
        assert len(rreg.active_restrictions("STK-THY")) == 2
        clk.set(date(2025, 6, 15))
        active = rreg.active_restrictions("STK-THY")
        assert active == [uzun]
        assert kisa.is_active is False
        assert uzun.is_active is True

    def test_63_history_is_active_guncel_durum(self):
        clk = MutableClock(date(2025, 6, 5))
        rreg = RestrictionRegistry(clock=clk)
        rec = make_restriction(start_date="2025-06-01", end_date="2025-06-10")
        rreg.register("STK-THY", rec)
        clk.set(date(2025, 6, 20))
        history = rreg.restriction_history("STK-THY")
        assert len(history) == 1
        assert history[0].is_active is False  # arsiv kaydi guncel hesapla

    def test_64_arsiv_kaydi_silinmez_tekrarli_okuma(self):
        clk = MutableClock(date(2025, 6, 5))
        rreg = RestrictionRegistry(clock=clk)
        rreg.register("STK-THY", make_restriction(
            start_date="2025-06-01", end_date="2025-06-10"))
        clk.set(date(2025, 6, 20))
        for _ in range(3):
            assert len(rreg.restriction_history("STK-THY")) == 1
            assert rreg.active_restrictions("STK-THY") == []
        assert rreg.duplicate_count == 0

    def test_65_suresi_biten_ve_aktif_ayni_hisse(self):
        rreg = RestrictionRegistry(clock=MutableClock())
        bitmis = make_restriction(start_date="2025-05-01", end_date="2025-05-31")
        aktif = make_restriction(
            restriction_type=RestrictionType.SHORT_SELLING_BAN,
            start_date="2025-06-01", end_date="2025-06-30",
        )
        rreg.register("STK-THY", bitmis)
        rreg.register("STK-THY", aktif)
        assert rreg.active_restrictions("STK-THY") == [aktif]
        assert len(rreg.restriction_history("STK-THY")) == 2

    def test_66_gelecekte_baslayan_tedbir_zamaninda_aktiflesir(self):
        clk = MutableClock(date(2025, 6, 1))
        rreg = RestrictionRegistry(clock=clk)
        rec = make_restriction(start_date="2025-06-15", end_date="2025-06-25")
        rreg.register("STK-THY", rec)
        assert rec.is_active is False
        clk.set(date(2025, 6, 16))
        assert rreg.active_restrictions("STK-THY") == [rec]
        clk.set(date(2025, 6, 26))
        assert rreg.active_restrictions("STK-THY") == []
        assert len(rreg.restriction_history("STK-THY")) == 1  # arsiv korunur


# ================================================================== #
# Kategori 6 — Islem durdurma (16 test)
# ================================================================== #
class TestIslemDurdurma:
    """TRADING_HALT: korunur ama skorlanamaz; bitince normale doner."""

    def test_67_halt_keep_in_scan_true(self):
        _, rreg, policy, _, _ = build_stack()
        rreg.register("STK-THY", make_restriction())
        assert policy.scan_status("STK-THY").keep_in_scan is True

    def test_68_halt_history_protected_true(self):
        _, rreg, policy, _, _ = build_stack()
        rreg.register("STK-THY", make_restriction())
        assert policy.scan_status("STK-THY").history_protected is True

    def test_69_halt_show_as_normal_false(self):
        _, rreg, policy, _, _ = build_stack()
        rreg.register("STK-THY", make_restriction())
        assert policy.scan_status("STK-THY").show_as_normal is False

    def test_70_halt_scoring_ready_false(self):
        _, rreg, policy, _, _ = build_stack()
        rreg.register("STK-THY", make_restriction())
        assert policy.scan_status("STK-THY").scoring_ready is False

    def test_71_halt_active_halts_listesi(self):
        _, rreg, policy, _, _ = build_stack()
        halt = make_restriction()
        rreg.register("STK-THY", halt)
        status = policy.scan_status("STK-THY")
        assert len(status.active_halts) == 1
        assert status.active_halts[0].restriction_type == RestrictionType.TRADING_HALT

    def test_72_halt_notlar_icerir(self):
        _, rreg, policy, _, _ = build_stack()
        rreg.register("STK-THY", make_restriction())
        status = policy.scan_status("STK-THY")
        assert any("TRADING_HALT" in note for note in status.notes)

    def test_73_halt_yokken_scoring_ready_true(self):
        _, _, policy, _, _ = build_stack()
        assert policy.scan_status("STK-THY").scoring_ready is True

    def test_74_halt_yokken_normal_gorunum(self):
        _, _, policy, _, _ = build_stack()
        status = policy.scan_status("STK-THY")
        assert status.show_as_normal is True
        assert status.keep_in_scan is True
        assert status.active_halts == ()

    def test_75_halt_bitince_scoring_ready_true(self):
        _, rreg, policy, _, clk = build_stack()
        rreg.register("STK-THY", make_restriction(
            start_date="2025-06-09", end_date="2025-06-12"))
        assert policy.scan_status("STK-THY").scoring_ready is False
        clk.set(date(2025, 6, 13))
        assert policy.scan_status("STK-THY").scoring_ready is True

    def test_76_halt_bitince_show_as_normal_true(self):
        _, rreg, policy, _, clk = build_stack()
        rreg.register("STK-THY", make_restriction(
            start_date="2025-06-09", end_date="2025-06-12"))
        clk.set(date(2025, 6, 13))
        status = policy.scan_status("STK-THY")
        assert status.show_as_normal is True
        assert status.keep_in_scan is True

    def test_77_halt_bitince_active_halts_bos(self):
        _, rreg, policy, _, clk = build_stack()
        rreg.register("STK-THY", make_restriction(
            start_date="2025-06-09", end_date="2025-06-12"))
        clk.set(date(2025, 6, 13))
        assert policy.scan_status("STK-THY").active_halts == ()

    def test_78_halt_kaydi_arsivde_kalir(self):
        _, rreg, policy, _, clk = build_stack()
        rreg.register("STK-THY", make_restriction(
            start_date="2025-06-09", end_date="2025-06-12"))
        clk.set(date(2025, 6, 13))
        history = rreg.restriction_history("STK-THY")
        assert len(history) == 1
        assert history[0].restriction_type == RestrictionType.TRADING_HALT
        assert history[0].is_active is False

    def test_79_gross_settlement_scoring_ready_kapatmaz(self):
        _, rreg, policy, _, _ = build_stack()
        rreg.register("STK-THY", make_restriction(
            restriction_type=RestrictionType.GROSS_SETTLEMENT,
            start_date="2025-06-01", end_date="2025-06-30"))
        status = policy.scan_status("STK-THY")
        assert status.scoring_ready is True
        assert status.show_as_normal is True

    def test_80_short_selling_ban_risk_notu(self):
        _, rreg, policy, _, _ = build_stack()
        rreg.register("STK-THY", make_restriction(
            restriction_type=RestrictionType.SHORT_SELLING_BAN,
            start_date="2025-06-01", end_date="2025-06-30"))
        status = policy.scan_status("STK-THY")
        assert status.scoring_ready is True
        assert "RISK_NOTE:SHORT_SELLING_BAN" in status.notes

    def test_81_halt_ve_diger_tedbir_birlikte(self):
        _, rreg, policy, _, clk = build_stack()
        rreg.register("STK-THY", make_restriction(
            start_date="2025-06-09", end_date="2025-06-12"))
        rreg.register("STK-THY", make_restriction(
            restriction_type=RestrictionType.GROSS_SETTLEMENT,
            start_date="2025-06-01", end_date="2025-06-30"))
        status = policy.scan_status("STK-THY")
        assert status.scoring_ready is False  # halt baskin
        # Halt bitince diger tedbir risk notu olarak kalir, skor acilir.
        clk.set(date(2025, 6, 13))
        status = policy.scan_status("STK-THY")
        assert status.scoring_ready is True
        assert "RISK_NOTE:GROSS_SETTLEMENT" in status.notes

    def test_82_halt_hicbir_durumda_taramadan_silinmez(self):
        _, rreg, policy, _, _ = build_stack()
        rreg.register("STK-THY", make_restriction(start_date="2025-06-09"))
        rreg.register("STK-THY", make_restriction(
            restriction_type=RestrictionType.MARGIN_TRADING_BAN,
            start_date="2025-06-01", end_date="2025-06-30"))
        status = policy.scan_status("STK-THY")
        assert status.keep_in_scan is True  # coklu tedbirde bile
        # Tedbirsiz hisse de taramada kalir (keep_in_scan her zaman True).
        assert policy.scan_status("STK-DIGER").keep_in_scan is True


# ================================================================== #
# Kategori 7 — Paket aktarimi (10 test)
# ================================================================== #
class TestPaketAktarimi:
    """Ham/dogrulanmis ayrimi, frozen paket, packet_version."""

    def _dolu_zincir(self):
        """v1(SUPERSEDED) + v2(ANNOUNCED) + iptal kaydi iceren zincir."""
        actions, rreg, policy, feed, clk = build_stack()
        actions.register(make_record(), kap_notice_no="KAP-1")
        actions.register(make_record(amount=1.6), kap_notice_no="KAP-2")
        actions.update_status(
            "STK-THY", ActionType.DIVIDEND, "2025-06-01",
            ActionStatus.CANCELLED, kap_notice_no="KAP-C1",
        )
        return actions, rreg, policy, feed, clk

    def test_83_actions_raw_tum_status(self):
        _, _, _, feed, _ = self._dolu_zincir()
        packet = feed.build_packet("STK-THY")
        assert len(packet.actions_raw) == 3
        statuses = {r.status for r in packet.actions_raw}
        assert statuses == {
            ActionStatus.SUPERSEDED, ActionStatus.ANNOUNCED, ActionStatus.CANCELLED,
        }

    def test_84_actions_validated_effective_completed(self):
        actions, _, _, feed, _ = build_stack()
        actions.register(make_record(effective_date="2025-06-01"), kap_notice_no="KAP-1")
        actions.register(make_record(effective_date="2025-06-02"), kap_notice_no="KAP-2")
        actions.register(make_record(effective_date="2025-06-03"), kap_notice_no="KAP-3")
        actions.update_status("STK-THY", ActionType.DIVIDEND, "2025-06-01", ActionStatus.EFFECTIVE)
        actions.update_status("STK-THY", ActionType.DIVIDEND, "2025-06-02", ActionStatus.EFFECTIVE)
        actions.update_status("STK-THY", ActionType.DIVIDEND, "2025-06-02", ActionStatus.COMPLETED)
        packet = feed.build_packet("STK-THY")
        validated_dates = {r.effective_date for r in packet.actions_validated}
        assert validated_dates == {"2025-06-01", "2025-06-02"}
        assert all(
            r.status in (ActionStatus.EFFECTIVE, ActionStatus.COMPLETED)
            for r in packet.actions_validated
        )
        assert len(packet.actions_raw) == 3  # ANNOUNCED ham listede kalir

    def test_85_validated_ids_isaretleme(self):
        actions, _, _, feed, _ = build_stack()
        actions.register(make_record(), kap_notice_no="KAP-1")
        packet = feed.build_packet("STK-THY")
        assert packet.actions_validated == ()  # ANNOUNCED -> dogrulanmis degil
        marked = feed.build_packet("STK-THY", validated_ids={"action-v1"})
        assert len(marked.actions_validated) == 1
        assert marked.actions_validated[0].status == ActionStatus.ANNOUNCED
        # (action_type, effective_date) cifti ile isaretleme de calisir.
        marked2 = feed.build_packet(
            "STK-THY", validated_ids={(ActionType.DIVIDEND, "2025-06-01")}
        )
        assert len(marked2.actions_validated) == 1

    def test_86_restrictions_active_ve_history(self):
        _, rreg, _, feed, _ = build_stack()
        rreg.register("STK-THY", make_restriction(
            start_date="2025-06-01", end_date="2025-06-30"))
        rreg.register("STK-THY", make_restriction(
            restriction_type=RestrictionType.GROSS_SETTLEMENT,
            start_date="2025-05-01", end_date="2025-05-31"))
        packet = feed.build_packet("STK-THY")
        assert len(packet.restrictions_active) == 1
        assert len(packet.restrictions_history) == 2
        assert packet.restrictions_active[0].restriction_type == RestrictionType.TRADING_HALT

    def test_87_scoring_ready_ve_suspension_flag_halt_yok(self):
        _, _, _, feed, _ = build_stack()
        packet = feed.build_packet("STK-THY")
        assert packet.scoring_ready is True
        assert packet.suspension_flag is False

    def test_88_packet_frozen_degistirilemez(self):
        _, _, _, feed, _ = self._dolu_zincir()
        packet = feed.build_packet("STK-THY")
        with pytest.raises(FrozenInstanceError):
            packet.stock_id = "STK-X"
        assert isinstance(packet.actions_raw, tuple)
        with pytest.raises(AttributeError):
            packet.actions_raw.append(make_record())

    def test_89_packet_registry_degisiminden_etkilenmez(self):
        actions, _, _, feed, _ = build_stack()
        actions.register(make_record(), kap_notice_no="KAP-1")
        packet = feed.build_packet("STK-THY")
        assert len(packet.actions_raw) == 1
        assert packet.actions_raw[0].status == ActionStatus.ANNOUNCED
        # Paket uretiminden SONRA registry degisir.
        actions.register(make_record(amount=1.6), kap_notice_no="KAP-2")
        actions.update_status(
            "STK-THY", ActionType.DIVIDEND, "2025-06-01", ActionStatus.EFFECTIVE
        )
        # Eski paket sessizce degismez.
        assert len(packet.actions_raw) == 1
        assert packet.actions_raw[0].status == ActionStatus.ANNOUNCED

    def test_90_packet_version_her_uretimde_artar(self):
        _, _, _, feed, _ = build_stack()
        p1 = feed.build_packet("STK-THY")
        p2 = feed.build_packet("STK-DIGER")
        p3 = feed.build_packet("STK-THY")
        assert (p1.packet_version, p2.packet_version, p3.packet_version) == (1, 2, 3)

    def test_91_halt_durumunda_packet_bayraklari(self):
        _, rreg, _, feed, _ = build_stack()
        rreg.register("STK-THY", make_restriction(
            start_date="2025-06-09", end_date="2025-06-12"))
        packet = feed.build_packet("STK-THY")
        assert packet.scoring_ready is False
        assert packet.suspension_flag is True
        assert len(packet.restrictions_active) == 1

    def test_92_bos_hisse_paketi(self):
        _, _, _, feed, _ = build_stack()
        packet = feed.build_packet("STK-YOK")
        assert packet.stock_id == "STK-YOK"
        assert packet.actions_raw == ()
        assert packet.actions_validated == ()
        assert packet.restrictions_active == ()
        assert packet.restrictions_history == ()
        assert packet.scoring_ready is True
        assert packet.suspension_flag is False


# ================================================================== #
# Kategori 8 — Collector + puan kilidi (8 test)
# ================================================================== #
class TestCollectorPuanKilidi:
    """Kaynak hatasi taramayi durdurmaz; puan uretme YOK."""

    def test_93_collect_kaynaklardan_yuklenir(self):
        action_source = FakeActionSource(data={
            "STK-1": [
                {"stock_id": "STK-1", "action_type": ActionType.DIVIDEND,
                 "announcement_date": "2025-05-01", "effective_date": "2025-06-01",
                 "amount": 1.2, "currency": "TRY", "source": "KAP",
                 "kap_notice_no": "KAP-1"},
                {"stock_id": "STK-1", "action_type": ActionType.BONUS_ISSUE,
                 "announcement_date": "2025-05-02", "effective_date": "2025-06-05",
                 "ratio": "0.20", "source": "KAP", "kap_notice_no": "KAP-2"},
            ],
        })
        restriction_source = FakeRestrictionSource(data={
            "STK-1": [
                {"restriction_type": RestrictionType.GROSS_SETTLEMENT,
                 "start_date": "2025-06-01", "end_date": "2025-06-30",
                 "source": "BIST"},
            ],
        })
        collector = CorporateCollector(
            action_source=action_source,
            restriction_source=restriction_source,
            clock=MutableClock(),
        )
        report = collector.collect(["STK-1"])
        assert report.collected == 3
        assert report.deduped == 0
        assert report.source_status == {"STK-1": SOURCE_OK}
        assert report.errors == []
        assert action_source.calls == ["STK-1"]
        assert restriction_source.calls == ["STK-1"]

    def test_94_collect_dedupe_sayilari(self):
        rec_dict = {"stock_id": "STK-1", "action_type": ActionType.DIVIDEND,
                    "announcement_date": "2025-05-01", "effective_date": "2025-06-01",
                    "source": "KAP", "kap_notice_no": "KAP-1"}
        action_source = FakeActionSource(data={"STK-1": [rec_dict, dict(rec_dict)]})
        collector = CorporateCollector(
            action_source=action_source,
            restriction_source=FakeRestrictionSource(),
            clock=MutableClock(),
        )
        report = collector.collect(["STK-1"])
        assert report.collected == 1
        assert report.deduped == 1  # ayni kap_notice_no ile ikinci kayit
        # Ikinci calistirma: hepsi duplicate sayilir.
        report2 = collector.collect(["STK-1"])
        assert report2.collected == 0
        assert report2.deduped == 2

    def test_95_kaynak_yok_source_unavailable_tarama_durmaz(self):
        collector = CorporateCollector(clock=MutableClock())  # kaynak enjekte yok
        report = collector.collect(["STK-A", "STK-B"])
        assert report.source_status == {
            "STK-A": SOURCE_UNAVAILABLE, "STK-B": SOURCE_UNAVAILABLE,
        }
        assert len(report.errors) == 4  # 2 hisse x 2 kaynak
        # Tarama DURMAZ: eksik hisselere bos paket uretilir.
        assert set(report.packets.keys()) == {"STK-A", "STK-B"}
        assert report.packets["STK-A"].actions_raw == ()
        assert report.packets["STK-A"].scoring_ready is True

    def test_96_kaynak_hatasi_eksik_hisseye_bos_paket(self):
        action_source = FakeActionSource(
            data={"STK-OK": [
                {"stock_id": "STK-OK", "action_type": ActionType.DIVIDEND,
                 "announcement_date": "2025-05-01", "effective_date": "2025-06-01",
                 "source": "KAP", "kap_notice_no": "KAP-1"},
            ]},
            fail_for={"STK-FAIL"},
        )
        restriction_source = FakeRestrictionSource(fail_for={"STK-FAIL"})
        collector = CorporateCollector(
            action_source=action_source,
            restriction_source=restriction_source,
            clock=MutableClock(),
        )
        report = collector.collect(["STK-FAIL", "STK-OK"])
        assert report.source_status["STK-FAIL"] == SOURCE_UNAVAILABLE
        assert report.source_status["STK-OK"] == SOURCE_OK
        assert report.collected == 1
        # Eksik hisseye bos paket; kayit icermez.
        packet = report.packets["STK-FAIL"]
        assert packet.actions_raw == ()
        assert packet.restrictions_history == ()
        assert any("STK-FAIL" in e for e in report.errors)

    def test_97_kismi_hata_diger_hisseler_devam(self):
        action_source = FakeActionSource(
            data={"STK-B": [
                {"stock_id": "STK-B", "action_type": ActionType.MERGER,
                 "announcement_date": "2025-05-01", "effective_date": "2025-07-01",
                 "source": "KAP", "kap_notice_no": "KAP-9"},
            ]},
            fail_for={"STK-A"},
        )
        collector = CorporateCollector(
            action_source=action_source,
            restriction_source=FakeRestrictionSource(),
            clock=MutableClock(),
        )
        report = collector.collect(["STK-A", "STK-B", "STK-C"])
        # STK-A haric tum hisseler islendi: tarama durmadi.
        assert report.source_status == {
            "STK-A": SOURCE_UNAVAILABLE,
            "STK-B": SOURCE_OK,
            "STK-C": SOURCE_OK,
        }
        assert report.collected == 1
        assert set(report.packets.keys()) == {"STK-A"}

    def test_98_puan_kilidi_alanlar(self):
        banned = {"sentiment", "score", "impact", "tone", "puan"}
        for cls in (CorporateActionRecord, TradingRestriction, CollectionReport,
                    FeedPacket, ScanStatus, RestrictionResult):
            names = {f.name for f in dataclasses.fields(cls)}
            assert not (names & banned), f"{cls.__name__} yasakli alan iceriyor"
        # Alan sayilari korunur.
        assert len(dataclasses.fields(CorporateActionRecord)) == 11
        assert len(dataclasses.fields(TradingRestriction)) == 7

    def test_99_puan_kilidi_fonksiyonlar(self):
        func_names = [
            n for n, _ in inspect.getmembers(collector_module, inspect.isfunction)
        ]
        method_names = [
            n for n, _ in inspect.getmembers(CorporateCollector, inspect.isfunction)
        ]
        for n in func_names + method_names:
            lowered = n.lower()
            assert "sentiment" not in lowered
            assert "impact" not in lowered
            assert "tone" not in lowered
            assert "puan" not in lowered
            assert lowered != "score" and not lowered.endswith("_score")

    def test_100_deterministik_zincir_saat_enjekte(self):
        def build():
            data = {"STK-1": [
                {"stock_id": "STK-1", "action_type": ActionType.DIVIDEND,
                 "announcement_date": "2025-05-01", "effective_date": "2025-06-01",
                 "source": "KAP", "kap_notice_no": "KAP-1"},
            ]}
            rdata = {"STK-1": [
                {"restriction_type": RestrictionType.TRADING_HALT,
                 "start_date": "2025-06-09", "end_date": "2025-06-12",
                 "source": "BIST"},
            ]}
            return CorporateCollector(
                action_source=FakeActionSource(data=data),
                restriction_source=FakeRestrictionSource(data=rdata),
                clock=MutableClock(),
            )

        r1 = build().collect(["STK-1"])
        r2 = build().collect(["STK-1"])
        assert (r1.collected, r1.deduped) == (r2.collected, r2.deduped) == (2, 0)
        assert r1.source_status == r2.source_status == {"STK-1": SOURCE_OK}
        # Saat enjekte: tedbir collected_at damgasi deterministik.
        c = build()
        c.collect(["STK-1"])
        history = c.restriction_registry.restriction_history("STK-1")
        assert history[0].collected_at == FIXED_NOW.isoformat()
        assert history[0].is_active is True
