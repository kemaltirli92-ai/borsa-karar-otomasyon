"""BLOK 21 - Guvenlik, Log, Izleme ve Yedekleme: VPS yeniden baslama guvenligi.

Kurallar ozeti:
- stdlib only (json, os, pathlib); gercek ag/subprocess YOK.
- Deterministik: clock enjekte edilir; durum dosyalari enjekte yollarda
  tutulur; testler gecici dizinler kullanir.
- BootRecovery.recover: status == "ACTIVE" kalan (yarim) run'lar ->
  "ABORTED" + reason="vps_restart"; terminal durumlar (COMPLETED/FAILED/
  ABORTED) DEGISMEZ.
- should_start_scan: ayni gun+revision icin COMPLETED run varsa False
  (cift tarama YOK); ABORTED varsa True (yeniden denenebilir).
- PublishedStore: atomik yazim (tmp + os.replace); restart son yayini
  SILMEZ.
- verify_autostart: systemd .service/.timer dosyalarinda "[Install]" +
  "WantedBy" arar (repo systemd/ dizini parametre olarak verilir).
- Puan/bildirim kilidi: bu modul puan/sinyal/musteri bildirimi uretmez.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from app.services.stock_scanning.orchestration.runs import (
    RUN_ABORTED,
    RUN_ACTIVE,
    RUN_COMPLETED,
    TERMINAL_STATUSES,
)

ABORT_REASON_VPS_RESTART = "vps_restart"


def _utc_now() -> datetime:
    """Default clock sarici (enjekte clock kullanilmadiginda)."""
    return datetime.now(timezone.utc)


class FileRunStateStore:
    """Run durumlarini JSON dosyasinda tutan kalici depo (atomik yazim)."""

    def __init__(self, path: str, clock: Optional[Callable[[], datetime]] = None):
        self.path = str(path)
        self._clock = clock or _utc_now

    def _load(self) -> Dict[str, object]:
        if not os.path.isfile(self.path):
            return {"runs": {}}
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (ValueError, OSError):
            return {"runs": {}}
        if not isinstance(data, dict) or not isinstance(data.get("runs"), dict):
            return {"runs": {}}
        return data

    def _save(self, data: Dict[str, object]) -> None:
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=True, indent=2, sort_keys=True)
        os.replace(tmp_path, self.path)

    def upsert(self, run_id: str, status: str, payload: Optional[dict] = None) -> None:
        """Run'i olustur/guncelle; payload alanlari korunarak birlestirilir."""
        data = self._load()
        runs = data["runs"]
        run = dict(runs.get(run_id) or {})
        if payload:
            run.update(payload)
        run["run_id"] = run_id
        run["status"] = status
        runs[run_id] = run
        self._save(data)

    def list_runs(self) -> List[dict]:
        """Tum run'larin kopya listesi: [{"run_id", "status", ...}]."""
        runs = self._load()["runs"]
        return [dict(run) for run in runs.values()]

    def mark(self, run_id: str, status: str, reason: Optional[str] = None) -> None:
        """Run durumunu isaretle; reason verilirse kayda eklenir."""
        data = self._load()
        runs = data["runs"]
        run = dict(runs.get(run_id) or {"run_id": run_id})
        run["status"] = status
        if reason is not None:
            run["reason"] = reason
        runs[run_id] = run
        self._save(data)


class BootRecovery:
    """Servis acilisinda cagrilir: yarim kalan run'lari guvenli kapatir."""

    def __init__(self, store: FileRunStateStore, clock: Optional[Callable[[], datetime]] = None):
        self._store = store
        self._clock = clock or _utc_now

    def recover(self) -> dict:
        """ACTIVE kalan run'lari ABORTED + reason=vps_restart yapar.

        Rapor: {"aborted": [run_id...], "already_terminal": n}.
        Terminal durumlar degismez.
        """
        aborted: List[str] = []
        already_terminal = 0
        for run in self._store.list_runs():
            status = run.get("status")
            if status == RUN_ACTIVE:
                self._store.mark(
                    str(run.get("run_id")),
                    RUN_ABORTED,
                    reason=ABORT_REASON_VPS_RESTART,
                )
                aborted.append(str(run.get("run_id")))
            elif status in TERMINAL_STATUSES:
                already_terminal += 1
        return {"aborted": aborted, "already_terminal": already_terminal}

    def should_start_scan(self, day: str, revision: int = 1) -> bool:
        """Ayni gun+revision COMPLETED run varsa False; ABORTED varsa True."""
        for run in self._store.list_runs():
            if run.get("day") != day:
                continue
            if int(run.get("revision", 1)) != int(revision):
                continue
            if run.get("status") == RUN_COMPLETED:
                return False
        return True


class PublishedStore:
    """Son yayinlanmis veri — restart'ta KAYBOLMAZ (atomik yazim)."""

    def __init__(self, path: str):
        self.path = str(path)

    def save(self, envelope: dict) -> None:
        """Atomik yazim: once tmp dosyaya, sonra os.replace ile yerine."""
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(envelope, fh, ensure_ascii=True, indent=2, sort_keys=True)
        os.replace(tmp_path, self.path)

    def load_last(self) -> Optional[dict]:
        """Son yayini oku; dosya yoksa None. Restart bunu SILMEZ."""
        if not os.path.isfile(self.path):
            return None
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (ValueError, OSError):
            return None
        return data if isinstance(data, dict) else None


def verify_autostart(units_dir: str) -> dict:
    """systemd .service/.timer dosyalarinda [Install] + WantedBy arar.

    Rapor: {"units": [{"file": ..., "autostart": bool}...], "all_ok": bool}.
    """
    units: List[dict] = []
    directory = Path(str(units_dir))
    files: List[Path] = []
    if directory.is_dir():
        files = sorted(directory.glob("*.service")) + sorted(directory.glob("*.timer"))
    for unit_file in files:
        try:
            text = unit_file.read_text(encoding="utf-8")
        except OSError:
            text = ""
        autostart = ("[Install]" in text) and ("WantedBy" in text)
        units.append({"file": unit_file.name, "autostart": autostart})
    return {"units": units, "all_ok": all(unit["autostart"] for unit in units)}
