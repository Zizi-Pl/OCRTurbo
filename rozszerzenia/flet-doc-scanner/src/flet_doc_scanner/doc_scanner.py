import json
from dataclasses import dataclass, field
from typing import Optional

import flet as ft

__all__ = ["DocScanner", "WynikSkanu"]


@dataclass
class WynikSkanu:
    """Wynik sesji skanowania.

    status:
        "ok"          - zeskanowano strony (lista `obrazy`, opcjonalnie `pdf`)
        "anulowano"   - użytkownik zamknął skaner
        "niedostepny" - platforma inna niż Android
        "blad"        - skaner nie wystartował (np. brak Usług Google Play);
                        szczegóły w `blad`
    """

    status: str
    obrazy: list[str] = field(default_factory=list)
    pdf: Optional[str] = None
    blad: str = ""


_STATUSY = {
    "ok": "ok",
    "cancelled": "anulowano",
    "unsupported": "niedostepny",
    "error": "blad",
}


@ft.control("DocScanner")
class DocScanner(ft.Service):
    """Systemowy skaner dokumentów Google (ML Kit) – ten sam co w Plikach Google.

    Wykrywa krawędzie kartki, prostuje perspektywę, ma filtry i obsługuje
    wiele stron. Działa tylko na Androidzie z Usługami Google Play; aplikacja
    nie potrzebuje uprawnienia do aparatu.
    """

    async def skanuj(
        self,
        max_stron: int = 10,
        import_z_galerii: bool = True,
        tryb: str = "full",
        pdf: bool = False,
    ) -> WynikSkanu:
        """Otwiera skaner i czeka, aż użytkownik skończy.

        Args:
            max_stron: maksymalna liczba stron w jednej sesji.
            import_z_galerii: czy pozwolić wybrać zdjęcie z galerii w skanerze.
            tryb: "base" (bez filtrów), "filter" (z filtrami) lub
                "full" (filtry + usuwanie cieni/plam, czyszczenie obrazu).
            pdf: czy dodatkowo zwrócić wszystkie strony jako jeden plik PDF.
        """
        surowy = await self._invoke_method(
            method_name="scan",
            arguments={
                "page_limit": int(max_stron),
                "gallery_import": bool(import_z_galerii),
                "mode": tryb,
                "pdf": bool(pdf),
            },
            # Skanowanie kilku stron może trwać kilka minut.
            timeout=3600,
        )
        try:
            dane = json.loads(surowy) if isinstance(surowy, str) else dict(surowy or {})
        except (TypeError, ValueError):
            return WynikSkanu(status="blad", blad=f"Nieoczekiwana odpowiedź: {surowy!r}")

        return WynikSkanu(
            status=_STATUSY.get(dane.get("status"), "blad"),
            obrazy=[str(p) for p in (dane.get("images") or [])],
            pdf=dane.get("pdf") or None,
            blad=str(dane.get("error") or ""),
        )
