"""BLOK 15 - Ana sayfa aciklama metni (display.py).

Sabit kural (SPEC BLOK 15 bolum 8) — DEGISTIRILEMEZ:

    "Bu oran verinin tamlik ve dogrulama seviyesidir, hissenin
     yukselme ihtimali degil."

- `DISCLAIMER_TEXT` sabiti; ConfidenceResult.disclaimer alani bu metni
  tasir.
- `set_disclaimer_text` ile degistirme girisimi her zaman
  DisclaimerLockedError hatasi verir (kilit kurali).
- `get_disclaimer` metni okur (tek kaynak).

stdlib only; gercek ag YOK; deterministik.
"""
from __future__ import annotations

# Ana sayfa aciklama metni — sabit kural, degistirilemez.
DISCLAIMER_TEXT = (
    "Bu oran verinin tamlik ve dogrulama seviyesidir, "
    "hissenin yukselme ihtimali degil."
)


class DisclaimerLockedError(Exception):
    """Disclaimer metni degistirme girisimi — kilit ihlali."""

    code = "DISCLAIMER_LOCKED"

    def __init__(self, message: str = "Disclaimer metni sabittir, degistirilemez"):
        super().__init__(message)
        self.message = message


def get_disclaimer() -> str:
    """Sabit aciklama metnini dondurur (tek kaynak)."""
    return DISCLAIMER_TEXT


def set_disclaimer_text(new_text: str) -> None:
    """Metni degistirme girisimi — HER ZAMAN hata verir (kilit kurali).

    Yeni metin degeri okunmaz bile; kural sabittir.
    """
    raise DisclaimerLockedError(
        "Disclaimer metni sabittir, degistirilemez (kilit kurali): %r" % (new_text,)
    )
