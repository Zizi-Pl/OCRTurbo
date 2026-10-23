"""
Obsługa systemowego skanera dokumentów Google (ML Kit) – jak w Plikach Google.

Skaner sam wykrywa krawędzie kartki, prostuje perspektywę, czyści obraz
i obsługuje wiele stron. Działa tylko na Androidzie z Usługami Google Play.
Na innych platformach (lub gdy rozszerzenie nie jest zainstalowane)
`dostepny()` zwraca False i aplikacja używa dotychczasowego aparatu.
"""

import os
import shutil
from datetime import datetime

import flet as ft

import config

try:
    from flet_doc_scanner import DocScanner, WynikSkanu
except ImportError:  # np. uruchomienie na PC bez zainstalowanego rozszerzenia
    DocScanner = None
    WynikSkanu = None

# Maksymalna liczba stron w jednej sesji skanowania.
MAKS_STRON = 10

_skaner = None


def zarejestruj(page: ft.Page) -> bool:
    """Rejestruje usługę skanera na stronie. Wywołać raz w main()."""
    global _skaner
    if DocScanner is None or page.platform != ft.PagePlatform.ANDROID:
        # Na PC klient Flet nie zna tej kontrolki - nie rejestrujemy jej.
        return False
    if _skaner is None:
        _skaner = DocScanner()
        page.services.append(_skaner)
    return True


def dostepny(page: ft.Page) -> bool:
    return _skaner is not None and page.platform == ft.PagePlatform.ANDROID


def _znacznik_czasu() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def _przenies_do_katalogu(zrodlo: str, docelowy: str) -> str:
    """Kopiuje plik wynikowy skanera do katalogu danych aplikacji, a oryginał
    z pamięci podręcznej skanera usuwa."""
    shutil.copyfile(zrodlo, docelowy)
    try:
        os.remove(zrodlo)
    except OSError:
        pass
    return docelowy


def skopiuj_wyniki(obrazy: list[str], pdf: str | None = None) -> tuple[list[str], str | None]:
    """Przenosi strony (JPG) i opcjonalny PDF do katalogu danych aplikacji.

    Nazwy foto_skan_*.jpg / skan_*.pdf są sprzątane przez
    core.wyczysc_pliki_robocze() przy starcie aplikacji.
    """
    ts = _znacznik_czasu()
    katalog = config.KATALOG_DANYCH
    strony = []
    for nr, sciezka in enumerate(obrazy, start=1):
        if sciezka and os.path.exists(sciezka):
            cel = os.path.join(katalog, f"foto_skan_{ts}_s{nr}.jpg")
            strony.append(_przenies_do_katalogu(sciezka, cel))

    pdf_docelowy = None
    if pdf and os.path.exists(pdf):
        pdf_docelowy = _przenies_do_katalogu(pdf, os.path.join(katalog, f"skan_{ts}.pdf"))
    return strony, pdf_docelowy


async def skanuj(page: ft.Page, pdf: bool = False, max_stron: int = MAKS_STRON):
    """Otwiera skaner Google i zwraca WynikSkanu ze ścieżkami w katalogu aplikacji.

    Zwraca None, gdy skaner nie jest dostępny na tej platformie.
    """
    if not dostepny(page):
        return None

    wynik = await _skaner.skanuj(
        max_stron=max_stron,
        import_z_galerii=True,
        tryb="full",
        pdf=pdf,
    )
    if wynik.status == "ok":
        wynik.obrazy, wynik.pdf = skopiuj_wyniki(wynik.obrazy, wynik.pdf)
        if not wynik.obrazy:
            wynik.status = "blad"
            wynik.blad = "Skaner nie zwrócił żadnej strony."
    return wynik
