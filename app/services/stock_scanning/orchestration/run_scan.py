"""BLOK 14/22 - Sabah taramasi CLI giris noktasi.

systemd xk100-hisse-tarama.service tarafindan
`python -m app.services.stock_scanning.orchestration.run_scan` ile cagrilir.
Modul import edildiginde hicbir is YAPMAZ; yalnizca main() cagrildiginda
calisir (gercek veri kaynaklari yoksa bile import hatasiz yuklenir).

Kurallar ozeti:
- stdlib only; gercek ag/subprocess YOK: gercek toplayicilar (lisansli fiyat
  API'si, KAP akisi, haber kaynaklari) dis katmandan enjekte edilir; bu
  giris noktasi tek basina sahte veri URETMEZ.
- Evren listesi bu modulde URETILMEZ: resmi XK100 listesi provider'dan
  enjekte edilir (BLOK 5 kurali — liste uydurma kaynaktan gelmez).
- Puan/bildirim kilidi: bu modul puan/sinyal/musteri bildirimi uretmez.
- Cikis kodlari: 0 = akis tamamlandi; 2 = evren/collector enjeksiyonu
  eksik (tarama BASLATILMADI — sahte basari raporu yazilmaz).
"""
from __future__ import annotations

import os
import sys
from typing import Callable, Dict, List, Optional

from app.services.stock_scanning.orchestration.orchestrator import (
    FLOW_COMPLETED,
    ScanOrchestrator,
)

ENV_DATABASE_PATH = "DATABASE_PATH"
EXIT_OK = 0
EXIT_NOT_READY = 2


def build_orchestrator(
    collectors: Optional[Dict[str, Callable[[str], object]]] = None,
) -> ScanOrchestrator:
    """VPS uzerinde dis katmanin enjekte ettigi collector'larla kurucu.

    collectors=None ise bos sozluk kullanilir — bu durumda orchestrator
    her hisse icin PARTIAL_DATA (collector_missing) uretir; sahte veri
    yazilmaz, sistem durmaz.
    """
    return ScanOrchestrator(collectors=dict(collectors or {}))


def main(
    universe: Optional[List[str]] = None,
    collectors: Optional[Dict[str, Callable[[str], object]]] = None,
) -> int:
    """Sabah taramasini calistirir; cikis kodu dondurur.

    universe=None veya bos ise tarama BASLATILMAZ (resmi liste enjekte
    edilmeden evren uydurulmaz) ve EXIT_NOT_READY doner.
    """
    if not universe:
        print(
            "[XK100][run_scan] TARAMA BASLATILMADI: resmi evren listesi ve/veya "
            "veri toplayicilari enjekte edilmedi (sahte veri uretilmez).",
            file=sys.stderr,
        )
        return EXIT_NOT_READY
    orchestrator = build_orchestrator(collectors)
    result = orchestrator.run_morning_flow(list(universe))
    state = getattr(result, "state", result)
    print(
        "[XK100][run_scan] akis sonucu: %s (db=%s)"
        % (state, os.environ.get(ENV_DATABASE_PATH, "db/xk100.db"))
    )
    return EXIT_OK if state == FLOW_COMPLETED or state is not None else EXIT_NOT_READY


if __name__ == "__main__":  # pragma: no cover - CLI giris noktasi
    raise SystemExit(main())
