import asyncio
import flet as ft
from ui import UIManager

from module_pz import ModulPZMixin
from module_doc import ModulDocMixin
from module_scan import ModulScanMixin


class ViewsManager(ModulPZMixin, ModulDocMixin, ModulScanMixin):
    def __init__(self, page: ft.Page, ui_manager: UIManager, serwis_udostepniania: ft.Share, pickery: dict):
        self.page = page
        self.ui = ui_manager
        self.serwis_udostepniania = serwis_udostepniania
        self.pickery = pickery

        self.ui.views_manager = self
        self.ui.on_foto_captured = self.przypisz_zrobione_foto

        self.stan_weryfikacji = {
            "dane": None,
            "baza": [],
            "uzywa_bazy": True,
            "status_sum": "BRAK_DANYCH",
            "info_sumy": "",
            "indeks_edytowany": -1
        }
        self.blokada_analizy = False
        self.ostatnia_sciezka_edi = {"sciezka": None}

        self.aktualne_zdjecie_pz = {"sciezka": None}
        self.zdjecie_dok = {"sciezka": None}
        self.zdjecie_skan = {"sciezka": None, "oryginal": None}

        # Inicjalizacja komponentów
        self._inicjalizuj_modul_pz()
        self._inicjalizuj_modul_dokument()
        self._inicjalizuj_modul_skanera()
        self._inicjalizuj_menu_glowne()

    def przypisz_zrobione_foto(self, sciezka: str, modul: str):
        if modul == "pz":
            self.ustaw_nowy_obraz_pz(sciezka)
        elif modul in ("dok", "dokument"):
            self.ustaw_nowy_obraz_dok(sciezka)
        elif modul == "skaner":
            self.ustaw_nowy_obraz_skan(sciezka)

    def _pobierz_deltas(self, e):
        dx = getattr(e, "delta", None)
        if dx is not None:
            return e.delta.x, e.delta.y
        loc = getattr(e, "local_delta", None)
        if loc is not None:
            return e.local_delta.x, e.local_delta.y
        return getattr(e, "delta_x", 0.0), getattr(e, "delta_y", 0.0)

    def _inicjalizuj_menu_glowne(self):
        def kafel_wyboru(tytul: str, podtytul: str, ikona, bg_kolor, ikona_kolor, cel):
            return ft.Container(
                content=ft.Row([
                    ft.Icon(ikona, size=36, color=ikona_kolor),
                    ft.Column([
                        ft.Text(tytul, size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                        ft.Text(podtytul, size=12, color=ft.Colors.GREY_300)
                    ], expand=True, spacing=2)
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                padding=16,
                bgcolor=bg_kolor,
                border_radius=10,
                ink=True,
                on_click=lambda e: asyncio.create_task(self.przelacz_widok(cel))
            )

        self.widok_menu = ft.Column([
            ft.Row([
                ft.Column([
                    ft.Text("ocrLmm Hub", size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400),
                    ft.Text("Wybierz moduł roboczy", size=13, color=ft.Colors.GREY_400)
                ], spacing=2),
                ft.IconButton(ft.Icons.SETTINGS, tooltip="Ustawienia połączenia", on_click=self.ui.otworz_ustawienia)
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
            kafel_wyboru("Faktura / PZ (Dla PC-Market)", "Pełna analiza towarowa, kody, sumy, baza i generowanie EDI.", ft.Icons.RECEIPT_LONG, ft.Colors.GREEN_900, ft.Colors.GREEN_300, "pz"),
            kafel_wyboru("Odczyt Dokumentu (Układ 1:1)", "Odczyt pism, umów i tabel z zachowaniem układu do edytora tekstu.", ft.Icons.ARTICLE, ft.Colors.BLUE_900, ft.Colors.BLUE_300, "dokument"),
            kafel_wyboru("Szybki Skaner Graficzny", "Kadrowanie z podglądem na żywo i filtry czarno-białe (offline).", ft.Icons.CROP_FREE, ft.Colors.DEEP_ORANGE_900, ft.Colors.ORANGE_300, "skaner")
        ], spacing=12, visible=True)

    async def przelacz_widok(self, nazwa: str):
        plat = getattr(self.page, "platform", None)
        if plat in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS, "android", "ios"):
            try:
                if hasattr(self.page, "set_allowed_device_orientations"):
                    if nazwa in ("skaner", "dokument"):
                        await self.page.set_allowed_device_orientations([
                            ft.DeviceOrientation.PORTRAIT_UP
                        ])
                    else:
                        await self.page.set_allowed_device_orientations([
                            ft.DeviceOrientation.PORTRAIT_UP,
                            ft.DeviceOrientation.LANDSCAPE_LEFT,
                            ft.DeviceOrientation.LANDSCAPE_RIGHT,
                        ])
            except Exception:
                pass

        self.widok_menu.visible = (nazwa == "menu")
        self.widok_pz.visible = (nazwa == "pz")
        self.widok_dokument.visible = (nazwa == "dokument")
        self.widok_skanera.visible = (nazwa == "skaner")

        # Reset widoków do stanu początkowego (pokazujemy formularz główny, ukrywamy pełny kadr)
        if hasattr(self, "kolumna_glowna_pz") and hasattr(self, "widok_kadrowania_pz"):
            self.kolumna_glowna_pz.visible = True
            self.widok_kadrowania_pz.visible = False

        if hasattr(self, "kolumna_glowna_dok") and hasattr(self, "widok_kadrowania_dok"):
            self.kolumna_glowna_dok.visible = True
            self.widok_kadrowania_dok.visible = False

        if hasattr(self, "kolumna_glowna_skan") and hasattr(self, "widok_kadrowania_skan"):
            self.kolumna_glowna_skan.visible = True
            self.widok_kadrowania_skan.visible = False

        if nazwa in ("skaner", "dokument"):
            self.page.scroll = None
        else:
            self.page.scroll = ft.ScrollMode.AUTO

        self.page.update()
