"""BLOK 6 - BLOK 5 (evren modulu) entegrasyon adaptor."""
from __future__ import annotations

from typing import Dict, List, Optional

from app.services.stock_scanning.symbol_identity import (
    REASON_UNRESOLVED_UNIVERSE_SYMBOL,
    SymbolIdentityService,
)


class IdentityAdapter:
    """BLOK 5 evren modulunun cagiracagi arayuz."""

    def __init__(self, service: SymbolIdentityService):
        self.service = service

    def resolve_universe_symbols(
        self, symbols: List[str]
    ) -> Dict[str, Optional[str]]:
        """Her sembol icin stock_id cozumler.

        Bulunamayan semboller icin deger None doner ve sembol
        SYMBOL_VERIFICATION_PENDING kuyruguna eklenir
        (service.get_pending_queue() uzerinden izlenebilir).

        Returns: {sembol: stock_id veya None}
        """
        result: Dict[str, Optional[str]] = {}
        for symbol in symbols:
            resolved = self.service.resolve(symbol)
            if resolved is None:
                result[symbol] = None
                self.service.mark_pending(
                    None,
                    REASON_UNRESOLVED_UNIVERSE_SYMBOL,
                    query=symbol,
                )
            else:
                result[symbol] = resolved.stock_id
        return result

    def get_pending_symbols(self) -> List[str]:
        """Cozulememis evren sembollerinin listesi."""
        return [
            item.query
            for item in self.service.get_pending_queue()
            if item.reason == REASON_UNRESOLVED_UNIVERSE_SYMBOL and item.query
        ]
