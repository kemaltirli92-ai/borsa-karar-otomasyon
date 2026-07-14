"""BLOK 6 - KAP link dogrulama (periyodik).

KapVerifier http_client'i disaridan alir (testte mock). http_client yoksa
gercek ag cagrisi YAPILMAZ ve KAP_LINK_UNCHECKED doner.

http_client protokolu: head(url) veya get(url) -> response; response'un
status_code niteligi okunur. 200 => KAP_LINK_VALID, diger/timeout/exception
=> KAP_LINK_BROKEN.
"""
from __future__ import annotations

from typing import Dict, Optional

from app.models.stock_identity import KapLinkStatus
from app.services.stock_scanning.symbol_identity import (
    REASON_KAP_LINK_BROKEN,
    SymbolIdentityService,
)

# Ard arda bu kadar basarisizlikta kayit pending kuyruguna duser
DEFAULT_FAIL_THRESHOLD = 3


class KapVerifier:
    """KAP linklerini dogrular ve sonuclari servise yazar."""

    def __init__(
        self,
        service: SymbolIdentityService,
        http_client=None,
        fail_threshold: int = DEFAULT_FAIL_THRESHOLD,
    ):
        self.service = service
        self.http_client = http_client
        self.fail_threshold = fail_threshold

    def _probe(self, url: str) -> bool:
        """HEAD/GET ile URL'yi yoklar. True: 200 dondu."""
        try:
            if hasattr(self.http_client, "head"):
                resp = self.http_client.head(url)
            else:
                resp = self.http_client.get(url)
            return getattr(resp, "status_code", None) == 200
        except Exception:
            # timeout / baglanti hatasi / DNS hatasi -> bozuk sayilir
            return False

    def verify(self, stock_id: str) -> KapLinkStatus:
        """Tek hissenin KAP linkini dogrular.

        - http_client yoksa: ag cagrisi yapilmaz, KAP_LINK_UNCHECKED.
        - 200: KAP_LINK_VALID, fail_count sifirlanir.
        - 404/timeout/diger: KAP_LINK_BROKEN, fail_count artar;
          fail_threshold ard arda basarisizlikta kayit
          SYMBOL_VERIFICATION_PENDING kuyruguna duser.
        """
        link = self.service.get_kap_link(stock_id)
        if link is None or self.http_client is None:
            return KapLinkStatus.KAP_LINK_UNCHECKED

        ok = self._probe(link.url)
        link.last_checked_at = self.service.now()
        if ok:
            link.status = KapLinkStatus.KAP_LINK_VALID
            link.fail_count = 0
        else:
            link.status = KapLinkStatus.KAP_LINK_BROKEN
            link.fail_count += 1
            if link.fail_count >= self.fail_threshold:
                self.service.mark_pending(stock_id, REASON_KAP_LINK_BROKEN)
        return link.status

    def run_periodic_check(self) -> Dict[str, KapLinkStatus]:
        """Tum acik KAP linklerini dogrular, sonuclari gunceller.

        Returns: {stock_id: KapLinkStatus}
        """
        results: Dict[str, KapLinkStatus] = {}
        for stock_id in self.service.all_kap_link_stock_ids():
            results[stock_id] = self.verify(stock_id)
        return results
