"""BLOK 6 - Ana servis: kayit, eslestirme, gecmis.

SymbolIdentityService tum sistemin merkezi stock_id kaynagidir.

Eslestirme kurallari:
- Sembol eslesmesi platform bazinda birebirdir (normalize sonrasi tam esitlik).
- Sirket adi eslesmesi normalize + TAM TOKEN esitligidir (substring degil).
- Kisa kodlar ("IS", "TK", "A") hicbir zaman daha uzun bir kelimenin/sembolun
  icinde yakalanamaz ("ISCTR" icinde "IS" eslesmez).
- Case-insensitive + Turkce karakter normalize (İ/I, ı/i, Ş, Ç, Ğ, Ö, Ü).
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Callable, List, Optional

from app.models.stock_identity import (
    VALID_PLATFORMS,
    KapLink,
    ResolveResult,
    StockIdentity,
    SymbolAuditEntry,
    SymbolRecord,
    VerificationQueueItem,
    VerificationStatus,
)

# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------
REASON_SYMBOL_VERIFICATION_PENDING = "SYMBOL_VERIFICATION_PENDING"
REASON_AMBIGUOUS_SYMBOL = "AMBIGUOUS_SYMBOL"
REASON_AMBIGUOUS_COMPANY_NAME = "AMBIGUOUS_COMPANY_NAME"
REASON_AMBIGUOUS_HISTORICAL_SYMBOL = "AMBIGUOUS_HISTORICAL_SYMBOL"
REASON_KAP_LINK_BROKEN = "KAP_LINK_BROKEN"
REASON_UNRESOLVED_UNIVERSE_SYMBOL = "UNRESOLVED_UNIVERSE_SYMBOL"

SYSTEM_USER = "system"

# ---------------------------------------------------------------------------
# Turkce karakter normalizasyonu
# ---------------------------------------------------------------------------
_TR_MAP = str.maketrans(
    {
        "İ": "I",
        "I": "I",
        "ı": "i",
        "i": "i",
        "Ş": "S",
        "ş": "s",
        "Ç": "C",
        "ç": "c",
        "Ğ": "G",
        "ğ": "g",
        "Ö": "O",
        "ö": "o",
        "Ü": "U",
        "ü": "u",
    }
)

_TOKEN_RE = re.compile(r"[A-Z0-9]+")


def normalize_text(text: Optional[str]) -> str:
    """Case-insensitive + Turkce karakter normalize.

    Ornek: "Türkiye İş Bankası" -> "TURKIYE IS BANKASI"
    """
    if text is None:
        return ""
    return str(text).strip().translate(_TR_MAP).upper()


def normalize_symbol(symbol: Optional[str]) -> str:
    """Sembol normalizasyonu (nokta, tire, iki nokta korunur)."""
    return normalize_text(symbol)


def tokenize(text: Optional[str]) -> List[str]:
    """Normalize edilmis metni TAM TOKEN listesine ayirir."""
    return _TOKEN_RE.findall(normalize_text(text))


def parse_date(value) -> date:
    """date/datetime/"YYYY-MM-DD" girdisini date'e cevirir."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value.strip())
    raise ValueError(f"Gecersiz tarih degeri: {value!r}")


# ---------------------------------------------------------------------------
# Hata siniflari (her hatanin makine okunur kodu vardir)
# ---------------------------------------------------------------------------
class SymbolIdentityError(Exception):
    """BLOK 6 temel hata sinifi."""

    code = "SYMBOL_IDENTITY_ERROR"

    def __init__(self, message: str, **details):
        super().__init__(message)
        self.message = message
        self.details = details


class StockAlreadyExistsError(SymbolIdentityError):
    code = "STOCK_ALREADY_EXISTS"


class StockNotFoundError(SymbolIdentityError):
    code = "STOCK_NOT_FOUND"


class InvalidPlatformError(SymbolIdentityError):
    code = "INVALID_PLATFORM"


class SymbolConflictError(SymbolIdentityError):
    code = "SYMBOL_CONFLICT"


class DuplicateSymbolError(SymbolIdentityError):
    code = "DUPLICATE_SYMBOL"


class SymbolNotFoundError(SymbolIdentityError):
    code = "SYMBOL_NOT_FOUND"


class QueueItemNotFoundError(SymbolIdentityError):
    code = "QUEUE_ITEM_NOT_FOUND"


# ---------------------------------------------------------------------------
# Ana servis
# ---------------------------------------------------------------------------
class SymbolIdentityService:
    """Merkezi sirket kimligi ve sembol eslestirme servisi.

    Deterministik: ayni girdi sirasi -> ayni stock_id (counter tabanli).
    clock enjekte edilebilir (testte sabit saat).
    """

    def __init__(self, clock: Optional[Callable[[], datetime]] = None):
        self._clock: Callable[[], datetime] = clock or datetime.now
        self._stocks: dict[str, StockIdentity] = {}
        self._symbols: List[SymbolRecord] = []
        self._kap_links: dict[str, KapLink] = {}
        self._audit: List[SymbolAuditEntry] = []
        self._queue: List[VerificationQueueItem] = []
        self._stock_counter = 0
        self._audit_counter = 0
        self._queue_counter = 0

    # -- yardimcilar -------------------------------------------------------
    def now(self) -> datetime:
        return self._clock()

    def _next_stock_id(self) -> str:
        self._stock_counter += 1
        return f"STK-{self._stock_counter:06d}"

    def _next_audit_id(self) -> str:
        self._audit_counter += 1
        return f"AUD-{self._audit_counter:06d}"

    def _next_queue_id(self) -> str:
        self._queue_counter += 1
        return f"Q-{self._queue_counter:06d}"

    def _validate_platform(self, platform) -> str:
        p = str(platform).strip().lower()
        if p not in VALID_PLATFORMS:
            raise InvalidPlatformError(
                f"Gecersiz platform: {platform!r}. Gecerli: {VALID_PLATFORMS}",
                platform=platform,
            )
        return p

    # -- kayit -------------------------------------------------------------
    def register_stock(self, company_name: str, isin: Optional[str] = None) -> str:
        """Yeni hisse kaydeder; ayni isim+ISIN tekrar kaydedilemez.

        Kural: normalize isim esit VE (ISIN'ler esit YA DA herhangi biri yok)
        ise kayit reddedilir. Ayni isim + farkli ISIN'ler ayri sirket sayilir.
        """
        if not company_name or not str(company_name).strip():
            raise ValueError("company_name bos olamaz")
        norm_name = normalize_text(company_name)
        norm_isin = normalize_text(isin) if isin else None
        for st in self._stocks.values():
            if normalize_text(st.company_name) != norm_name:
                continue
            existing_isin = normalize_text(st.isin) if st.isin else None
            if norm_isin is None or existing_isin is None or existing_isin == norm_isin:
                raise StockAlreadyExistsError(
                    f"Sirket zaten kayitli: {company_name!r} (mevcut: {st.stock_id})",
                    existing_stock_id=st.stock_id,
                    company_name=company_name,
                    isin=isin,
                )
        stock_id = self._next_stock_id()
        self._stocks[stock_id] = StockIdentity(
            stock_id=stock_id,
            company_name=str(company_name).strip(),
            isin=str(isin).strip() if isin else None,
            created_at=self.now(),
            status=VerificationStatus.VERIFIED,
        )
        return stock_id

    def get_stock(self, stock_id: str) -> StockIdentity:
        st = self._stocks.get(stock_id)
        if st is None:
            raise StockNotFoundError(
                f"Hisse bulunamadi: {stock_id!r}", stock_id=stock_id
            )
        return st

    # -- sembol yonetimi ---------------------------------------------------
    def add_symbol(
        self,
        stock_id: str,
        platform: str,
        symbol: str,
        valid_from=None,
    ) -> SymbolRecord:
        """Aktif sembol ekler.

        - Ayni hisse+platformda acik sembol varsa SYMBOL_CONFLICT hatasi.
        - Ayni platform+sembol baska bir hisseye aktif olarak bagliysa
          DUPLICATE_SYMBOL hatasi.
        """
        self.get_stock(stock_id)
        platform = self._validate_platform(platform)
        if not symbol or not str(symbol).strip():
            raise ValueError("symbol bos olamaz")
        norm = normalize_symbol(symbol)
        vf = parse_date(valid_from) if valid_from is not None else self.now().date()

        for rec in self._symbols:
            if (
                rec.platform == platform
                and rec.is_active
                and rec.stock_id != stock_id
                and normalize_symbol(rec.symbol) == norm
            ):
                raise DuplicateSymbolError(
                    f"{platform}/{symbol!r} zaten {rec.stock_id} hissesine bagli",
                    existing_stock_id=rec.stock_id,
                    attempted_stock_id=stock_id,
                    platform=platform,
                    symbol=str(symbol).strip(),
                )
        for rec in self._symbols:
            if rec.stock_id == stock_id and rec.platform == platform and rec.is_active:
                raise SymbolConflictError(
                    f"{stock_id}/{platform} icin zaten acik sembol var: {rec.symbol!r}",
                    stock_id=stock_id,
                    platform=platform,
                    existing_symbol=rec.symbol,
                )

        rec = SymbolRecord(
            stock_id=stock_id,
            platform=platform,
            symbol=str(symbol).strip(),
            valid_from=vf,
            valid_to=None,
            is_active=True,
        )
        self._symbols.append(rec)
        return rec

    def change_symbol(
        self,
        stock_id: str,
        platform: str,
        new_symbol: str,
        effective_date,
        admin_user: str = SYSTEM_USER,
        reason: Optional[str] = None,
    ) -> SymbolRecord:
        """Sembol degisikligi. ESKI SEMBOL SILINMEZ:
        eskinin valid_to'su kapanir, yenisi acilir, audit yazilir.
        """
        self.get_stock(stock_id)
        platform = self._validate_platform(platform)
        old = self._active_record(stock_id, platform)
        if old is None:
            raise SymbolNotFoundError(
                f"{stock_id}/{platform} icin aktif sembol yok",
                stock_id=stock_id,
                platform=platform,
            )
        if not new_symbol or not str(new_symbol).strip():
            raise ValueError("new_symbol bos olamaz")
        new_norm = normalize_symbol(new_symbol)
        if new_norm == normalize_symbol(old.symbol):
            raise ValueError("Yeni sembol eskisiyle ayni olamaz")
        eff = parse_date(effective_date)
        if eff < old.valid_from:
            raise ValueError(
                f"effective_date ({eff}) mevcut valid_from'dan ({old.valid_from}) once olamaz"
            )
        for rec in self._symbols:
            if (
                rec.platform == platform
                and rec.is_active
                and rec.stock_id != stock_id
                and normalize_symbol(rec.symbol) == new_norm
            ):
                raise DuplicateSymbolError(
                    f"{platform}/{new_symbol!r} zaten {rec.stock_id} hissesine bagli",
                    existing_stock_id=rec.stock_id,
                    attempted_stock_id=stock_id,
                    platform=platform,
                    symbol=str(new_symbol).strip(),
                )
        old.valid_to = eff
        old.is_active = False
        new_rec = SymbolRecord(
            stock_id=stock_id,
            platform=platform,
            symbol=str(new_symbol).strip(),
            valid_from=eff,
            valid_to=None,
            is_active=True,
        )
        self._symbols.append(new_rec)
        self._write_audit(
            stock_id, "CHANGE_SYMBOL", platform, old.symbol, new_rec.symbol,
            admin_user, reason,
        )
        return new_rec

    def _active_record(self, stock_id: str, platform: str) -> Optional[SymbolRecord]:
        for rec in self._symbols:
            if rec.stock_id == stock_id and rec.platform == platform and rec.is_active:
                return rec
        return None

    def get_active_symbol(self, stock_id: str, platform: str) -> Optional[str]:
        self.get_stock(stock_id)
        platform = self._validate_platform(platform)
        rec = self._active_record(stock_id, platform)
        return rec.symbol if rec else None

    def get_symbol_history(
        self, stock_id: str, platform: Optional[str] = None
    ) -> List[SymbolRecord]:
        """Tum gecmis kayitlar (valid_from sirasina gore)."""
        self.get_stock(stock_id)
        if platform is not None:
            platform = self._validate_platform(platform)
        recs = [
            rec
            for rec in self._symbols
            if rec.stock_id == stock_id and (platform is None or rec.platform == platform)
        ]
        return sorted(recs, key=lambda r: (r.valid_from, r.symbol))

    # -- eslestirme (resolve) ----------------------------------------------
    def _follow_merge(self, stock_id: str) -> str:
        """Birlestirilmis hisse zincirini son aktif hisseye kadar takip eder."""
        seen = set()
        current = stock_id
        while True:
            st = self._stocks.get(current)
            if st is None or st.merged_into is None or current in seen:
                return current
            seen.add(current)
            current = st.merged_into

    def resolve(
        self,
        query: str,
        platform: Optional[str] = None,
        on_date=None,
    ) -> Optional[ResolveResult]:
        """Sembol/sirket adindan stock_id cozumler.

        - Sembol eslesmesi: platform bazinda birebir (tam esitlik).
        - Sirket adi eslesmesi: normalize + TAM TOKEN esitligi (substring degil).
        - Iki aday bulunursa sonuc dondurmez; adaylari
          SYMBOL_VERIFICATION_PENDING kuyruguna atar ve None doner.
        """
        if not query or not str(query).strip():
            return None
        q = str(query).strip()
        if platform is not None:
            platform = self._validate_platform(platform)
        d = parse_date(on_date) if on_date is not None else None
        norm = normalize_symbol(q)

        # 1) Sembol eslesmesi (tam esitlik - word boundary)
        matched: List[SymbolRecord] = []
        for rec in self._symbols:
            if platform is not None and rec.platform != platform:
                continue
            if normalize_symbol(rec.symbol) != norm:
                continue
            if d is not None:
                if rec.valid_from <= d and (rec.valid_to is None or d < rec.valid_to):
                    matched.append(rec)
            elif rec.is_active:
                matched.append(rec)

        stock_ids: List[str] = []
        for rec in matched:
            if rec.stock_id not in stock_ids:
                stock_ids.append(rec.stock_id)

        if len(stock_ids) == 1:
            found = stock_ids[0]
            final = self._follow_merge(found)
            rec = matched[0]
            return ResolveResult(
                stock_id=final,
                matched_by="symbol",
                platform=rec.platform,
                matched_symbol=rec.symbol,
                historical=(not rec.is_active) or (final != found),
            )
        if len(stock_ids) > 1:
            for sid in stock_ids:
                self.mark_pending(sid, REASON_AMBIGUOUS_SYMBOL, query=q)
            return None

        # 2) Sirket adi eslesmesi: normalize + TAM TOKEN esitligi
        q_tokens = set(tokenize(q))
        if not q_tokens:
            return None
        name_matches = [
            st
            for st in self._stocks.values()
            if st.merged_into is None and set(tokenize(st.company_name)) == q_tokens
        ]
        if len(name_matches) == 1:
            st = name_matches[0]
            return ResolveResult(
                stock_id=st.stock_id, matched_by="company_name", historical=False
            )
        if len(name_matches) > 1:
            for st in name_matches:
                self.mark_pending(st.stock_id, REASON_AMBIGUOUS_COMPANY_NAME, query=q)
            return None
        return None

    def resolve_old_code(self, old_symbol: str, platform: str) -> Optional[ResolveResult]:
        """Gecmis (kapanmis) sembolle bile stock_id bulur.

        Sonuc historical=True ile isaretlenir. Birden fazla aday varsa
        None doner ve adaylari pending kuyruguna atar.
        """
        platform = self._validate_platform(platform)
        norm = normalize_symbol(old_symbol)
        stock_ids: List[str] = []
        for rec in self._symbols:
            if (
                rec.platform == platform
                and normalize_symbol(rec.symbol) == norm
                and rec.stock_id not in stock_ids
            ):
                stock_ids.append(rec.stock_id)
        if not stock_ids:
            return None
        if len(stock_ids) > 1:
            for sid in stock_ids:
                self.mark_pending(sid, REASON_AMBIGUOUS_HISTORICAL_SYMBOL, query=old_symbol)
            return None
        found = stock_ids[0]
        final = self._follow_merge(found)
        rec = next(
            r
            for r in self._symbols
            if r.stock_id == found
            and r.platform == platform
            and normalize_symbol(r.symbol) == norm
        )
        return ResolveResult(
            stock_id=final,
            matched_by="historical_symbol",
            platform=platform,
            matched_symbol=rec.symbol,
            historical=(not rec.is_active) or (final != found),
        )

    # -- KAP linkleri ------------------------------------------------------
    def set_kap_link(self, stock_id: str, url: str) -> KapLink:
        self.get_stock(stock_id)
        if not url or not str(url).strip():
            raise ValueError("url bos olamaz")
        link = KapLink(stock_id=stock_id, url=str(url).strip())
        self._kap_links[stock_id] = link
        return link

    def get_kap_link(self, stock_id: str) -> Optional[KapLink]:
        self.get_stock(stock_id)
        return self._kap_links.get(stock_id)

    def all_kap_link_stock_ids(self) -> List[str]:
        return list(self._kap_links.keys())

    # -- dogrulama kuyrugu --------------------------------------------------
    def mark_pending(
        self,
        stock_id: Optional[str],
        reason: str,
        query: Optional[str] = None,
    ) -> VerificationQueueItem:
        """Dogrulanamayan kaydi kuyruga ekler.

        Ayni (stock_id, query) icin acik kayit varsa tekrar eklemez
        (idempotent). stock_id verildiyse hisse durumu
        SYMBOL_VERIFICATION_PENDING olur.
        """
        if stock_id is not None:
            self.get_stock(stock_id)
        for item in self._queue:
            if not item.resolved and item.stock_id == stock_id and item.query == query:
                return item
        item = VerificationQueueItem(
            queue_id=self._next_queue_id(),
            stock_id=stock_id,
            reason=reason,
            created_at=self.now(),
            query=query,
        )
        self._queue.append(item)
        if stock_id is not None:
            self.get_stock(stock_id).status = VerificationStatus.SYMBOL_VERIFICATION_PENDING
        return item

    def get_pending_queue(self, include_resolved: bool = False) -> List[VerificationQueueItem]:
        return [
            item for item in self._queue if include_resolved or not item.resolved
        ]

    def get_queue_item(self, queue_id: str) -> VerificationQueueItem:
        for item in self._queue:
            if item.queue_id == queue_id:
                return item
        raise QueueItemNotFoundError(
            f"Kuyruk kaydi bulunamadi: {queue_id!r}", queue_id=queue_id
        )

    # -- audit --------------------------------------------------------------
    def _write_audit(
        self,
        stock_id: str,
        action: str,
        platform: str,
        old_symbol: Optional[str],
        new_symbol: Optional[str],
        admin_user: str,
        reason: Optional[str] = None,
    ) -> SymbolAuditEntry:
        entry = SymbolAuditEntry(
            audit_id=self._next_audit_id(),
            stock_id=stock_id,
            action=action,
            platform=platform,
            old_symbol=old_symbol,
            new_symbol=new_symbol,
            admin_user=admin_user,
            timestamp=self.now(),
            reason=reason,
        )
        self._audit.append(entry)
        return entry

    def get_audit_log(self, stock_id: Optional[str] = None) -> List[SymbolAuditEntry]:
        if stock_id is None:
            return list(self._audit)
        return [e for e in self._audit if e.stock_id == stock_id]
