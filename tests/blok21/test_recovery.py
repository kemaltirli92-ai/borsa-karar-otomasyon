"""BLOK 21 - test_recovery: VPS yeniden baslama guvenligi (6 test).

Kapsam: ACTIVE->ABORTED reason, terminal'e dokunmaz, should_start
cift-tarama engeli, ABORTED yeniden izin, PublishedStore save/load +
recover sonrasi korunur, verify_autostart units. Gercek repo systemd
dosyalarina DOKUNULMAZ; test kendi gecici units dizinini kurar.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.ops.recovery import (
    ABORT_REASON_VPS_RESTART,
    BootRecovery,
    FileRunStateStore,
    PublishedStore,
    verify_autostart,
)

FIXED = datetime(2025, 6, 3, 8, 0, 0, tzinfo=timezone.utc)


def _store(tmp_path):
    return FileRunStateStore(str(tmp_path / "runs.json"), clock=lambda: FIXED)


def test_active_run_aborted_reason_vps_restart(tmp_path):
    store = _store(tmp_path)
    store.upsert("run-1", "ACTIVE", {"day": "2025-06-03", "revision": 1})
    rapor = BootRecovery(store, clock=lambda: FIXED).recover()
    assert rapor["aborted"] == ["run-1"]
    run = [r for r in store.list_runs() if r["run_id"] == "run-1"][0]
    assert run["status"] == "ABORTED"
    assert run["reason"] == ABORT_REASON_VPS_RESTART


def test_terminal_durumlara_dokunulmaz(tmp_path):
    store = _store(tmp_path)
    store.upsert("run-ok", "COMPLETED", {"day": "2025-06-02"})
    store.upsert("run-fail", "FAILED", {"day": "2025-06-02"})
    store.upsert("run-abort", "ABORTED", {"day": "2025-06-02"})
    rapor = BootRecovery(store, clock=lambda: FIXED).recover()
    assert rapor["aborted"] == []
    assert rapor["already_terminal"] == 3
    durumlar = {r["run_id"]: r["status"] for r in store.list_runs()}
    assert durumlar == {"run-ok": "COMPLETED", "run-fail": "FAILED", "run-abort": "ABORTED"}


def test_should_start_scan_cift_tarama_engeli(tmp_path):
    store = _store(tmp_path)
    store.upsert("run-1", "COMPLETED", {"day": "2025-06-03", "revision": 1})
    recovery = BootRecovery(store, clock=lambda: FIXED)
    assert recovery.should_start_scan("2025-06-03", revision=1) is False
    assert recovery.should_start_scan("2025-06-04", revision=1) is True


def test_should_start_scan_aborted_yeniden_izin(tmp_path):
    store = _store(tmp_path)
    store.upsert("run-1", "ACTIVE", {"day": "2025-06-03", "revision": 1})
    recovery = BootRecovery(store, clock=lambda: FIXED)
    recovery.recover()  # run-1 artik ABORTED
    assert recovery.should_start_scan("2025-06-03", revision=1) is True
    # farkli revision COMPLETED, bu revision icin engel degil
    store.upsert("run-2", "COMPLETED", {"day": "2025-06-03", "revision": 2})
    assert recovery.should_start_scan("2025-06-03", revision=1) is True
    assert recovery.should_start_scan("2025-06-03", revision=2) is False


def test_published_store_save_load_restart_korur(tmp_path):
    path = str(tmp_path / "published.json")
    store = PublishedStore(path)
    assert store.load_last() is None
    zarf = {"day": "2025-06-03", "status": "PUBLISHED", "items": 100}
    store.save(zarf)
    # restart simulasyonu: yeni nesne, ayni dosya — recover bunu SILMEZ
    yeni = PublishedStore(path)
    assert yeni.load_last() == zarf
    # atomik yazim: tmp dosyasi artik kalmaz
    assert not (tmp_path / "published.json.tmp").exists()
    with open(path, "r", encoding="utf-8") as fh:
        assert json.load(fh) == zarf


def test_verify_autostart_units_gecici_dizin(tmp_path):
    birimler = tmp_path / "units"
    birimler.mkdir()
    (birimler / "xk100-backup.service").write_text(
        "[Service]\nType=oneshot\n\n[Install]\nWantedBy=multi-user.target\n",
        encoding="utf-8",
    )
    (birimler / "xk100-backup.timer").write_text(
        "[Timer]\nOnCalendar=*-*-* 23:30:00\n\n[Install]\nWantedBy=timers.target\n",
        encoding="utf-8",
    )
    (birimler / "eksik.service").write_text(
        "[Service]\nType=oneshot\n", encoding="utf-8"
    )
    rapor = verify_autostart(str(birimler))
    by_file = {u["file"]: u["autostart"] for u in rapor["units"]}
    assert by_file["xk100-backup.service"] is True
    assert by_file["xk100-backup.timer"] is True
    assert by_file["eksik.service"] is False
    assert rapor["all_ok"] is False
    # yalniz iyi birimler kaldiginda all_ok True
    (birimler / "eksik.service").unlink()
    assert verify_autostart(str(birimler))["all_ok"] is True
