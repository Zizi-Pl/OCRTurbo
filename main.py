import flet as ft

from ui import UIManager
from views import ViewsManager


async def main(page: ft.Page):
    # Czyścimy pozostałości po ewentualnym nagłym zamknięciu aplikacji w poprzedniej sesji
    import core
    core.wyczysc_pliki_robocze()

    # Parametry strony i motywu
    page.title = "ocrLmm Mobilny"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 16
    page.scroll = ft.ScrollMode.AUTO

    # Rejestracja systemowych serwisów Flet
    serwis_udostepniania = ft.Share()
    picker_foto = ft.FilePicker()
    picker_bazy = ft.FilePicker()
    picker_mapowan = ft.FilePicker()
    picker_backup = ft.FilePicker()

    page.services.extend([
        serwis_udostepniania,
        picker_foto,
        picker_bazy,
        picker_mapowan,
        picker_backup
    ])

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

    # Inicjalne odświeżenie etykiety bazy towarowej
    ui_manager.odswiez_status_bazy()

    # Osadzenie widoków na stronie
    page.add(
        ft.Column([
            views_manager.widok_menu,
            views_manager.widok_pz,
            views_manager.widok_dokument,
            views_manager.widok_skanera
        ], horizontal_alignment=ft.CrossAxisAlignment.STRETCH, spacing=0)
    )


if __name__ == "__main__":
    ft.run(main)
