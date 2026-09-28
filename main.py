import flet as ft

from ui import UIManager
from views import ViewsManager


async def main(page: ft.Page):
    # Czyścimy pozostałości po ewentualnym nagłym zamknięciu aplikacji w poprzedniej sesji
    import core
    core.wyczysc_pliki_robocze()

    # Parametry strony i motywu
    page.title = "ocrTurbo Mobilny"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 0

    # Rejestracja systemowego serwisu udostępniania
    serwis_udostepniania = ft.Share()
    page.services.append(serwis_udostepniania)

    # W Flet 0.85+ FilePicker NIE trafia do page.overlay!
    picker_foto = ft.FilePicker()
    picker_bazy = ft.FilePicker()
    picker_mapowan = ft.FilePicker()
    picker_backup = ft.FilePicker()

    pickery = {
        "foto": picker_foto,
        "baza": picker_bazy,
        "mapa": picker_mapowan,
        "backup": picker_backup
    }

    # Powołanie menedżera dialogów (okna modalne)
    ui_manager = UIManager(page, serwis_udostepniania, pickery)

    # Powołanie menedżera widoków roboczych (Hub, PZ, Dokument 1:1, Skaner)
    views_manager = ViewsManager(page, ui_manager, serwis_udostepniania, pickery)

    # Spięcie referencji zwrotnej z menedżerem widoków
    ui_manager.views_manager = views_manager
    ui_manager.on_foto_captured = views_manager.przypisz_zrobione_foto   

    # Inicjalne odświeżenie etykiety bazy towarowej
    ui_manager.odswiez_status_bazy()

    # Dynamiczna reakcja na rozmiar ekranu / zmianę wymiarów okna w Windows
    def on_page_resized(e):
        edytory = [
            getattr(views_manager, "edytor_pelny_pz", None),
            getattr(views_manager, "edytor_pelny_dok", None),
            getattr(views_manager, "edytor_pelny_skan", None)
        ]
        wymaga_update = False
        for edytor in edytory:
            if edytor and hasattr(edytor, "dostosuj_do_wymiarow_ekranu") and getattr(edytor, "sciezka_aktualna", None):
                edytor.dostosuj_do_wymiarow_ekranu()
                wymaga_update = True
        if wymaga_update:
            page.update()

    page.on_resized = on_page_resized

    # Główny kontener osadzający widoki z pełnym dopasowaniem wysokości do okna
    glowna_kolumna = ft.Column(
        controls=[
            views_manager.widok_menu,
            views_manager.widok_pz,
            views_manager.widok_dokument,
            views_manager.widok_skan
        ],
        expand=True,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        spacing=0
    )

    page.add(glowna_kolumna)


if __name__ == "__main__":
    ft.run(main)
